"""End-to-end tests for the curation steps that edit articles: citation, renumbering, amend."""

import json
import re
from pathlib import Path

from .harness import Kb, run_git

RUN_RE = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
ARTICLE = (
    "---\ntitle: Workflow\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n"
    "sources:\n  - observations/archived/older.md\n---\n\n# Workflow\n\n"
    "## First\n\nFirst fact.\n\n## Second\n\n"
    "<!-- kb-section: verified=2026-10-01; sources=observations/archived/older.md -->\n\n"
    "Second fact.\n"
)


def _batch(kb: Kb, *names: str) -> str:
    pending = kb.content / "observations" / "pending"
    for name in names:
        (pending / name).write_text(
            f"---\ntitle: {name}\ncreated: 2026-10-24\n---\n\nEvidence for {name}.\n",
            encoding="utf-8",
        )
    (kb.content / "observations" / "archived").mkdir(parents=True, exist_ok=True)
    (kb.content / "observations" / "archived" / "older.md").write_text(
        "---\ntitle: older\ncreated: 2026-09-01\n---\n\nOlder evidence.\n", encoding="utf-8"
    )
    _article(kb).write_text(ARTICLE, encoding="utf-8")
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Prepare the curation fixture")
    started = kb("curate", "start", "--no-sync", "--max-bytes", "100000", *names)
    assert started.returncode == 0, started.stderr
    match = RUN_RE.search(started.stdout)
    assert match is not None, started.stdout
    return match.group(1)


def _article(kb: Kb) -> Path:
    return kb.content / "knowledge" / "workflow.md"


def _destinations(kb: Kb, run: str, filename: str) -> list[dict[str, str]]:
    manifest = kb.content / "observations" / "batches" / f"{run}.json"
    batch = json.loads(manifest.read_text(encoding="utf-8"))
    member = next(item for item in batch["members"] if item["filename"] == filename)
    return list(member["destinations"])


def test_complete_cites_the_archive_in_front_matter_or_section_sources(git_kb: Kb) -> None:
    run = _batch(git_kb, "front.md", "section.md")

    front = git_kb(
        "curate",
        "complete",
        run,
        "front.md",
        "--disposition",
        "incorporated",
        "knowledge/workflow.md#1",
    )
    section = git_kb(
        "curate",
        "complete",
        run,
        "section.md",
        "--disposition",
        "duplicate",
        "knowledge/workflow.md#2",
    )

    assert front.returncode == 0, front.stderr
    assert front.stdout.endswith("Cited: observations/archived/front.md in knowledge/workflow.md\n")
    assert section.returncode == 0, section.stderr
    assert section.stdout.endswith(
        "Cited: observations/archived/section.md in knowledge/workflow.md#2\n"
    )
    text = _article(git_kb).read_text(encoding="utf-8")
    assert "sources:\n  - observations/archived/front.md\n  - observations/archived/older.md\n" in (
        text
    )
    assert "sources=observations/archived/older.md, observations/archived/section.md -->" in text
    linted = git_kb("lint", "--require-ttl", "knowledge/workflow.md")
    assert linted.returncode == 0, linted.stdout + linted.stderr


def test_an_article_that_cannot_be_cited_refuses_completion_before_archiving(git_kb: Kb) -> None:
    run = _batch(git_kb, "front.md")
    _article(git_kb).write_text(
        ARTICLE.replace(
            "sources:\n  - observations/archived/older.md\n",
            "sources: observations/archived/older.md\n",
        ),
        encoding="utf-8",
    )

    result = git_kb(
        "curate",
        "complete",
        run,
        "front.md",
        "--disposition",
        "incorporated",
        "knowledge/workflow.md#1",
    )

    assert result.returncode == 1
    assert result.stderr == (
        "curate: cannot cite the archive in knowledge/workflow.md: "
        "front matter sources is not a block list\n"
    )
    assert (git_kb.content / "observations" / "pending" / "front.md").is_file()


def test_finish_renumbers_a_destination_whose_heading_moved(git_kb: Kb) -> None:
    run = _batch(git_kb, "front.md")
    completed = git_kb(
        "curate",
        "complete",
        run,
        "front.md",
        "--disposition",
        "incorporated",
        "knowledge/workflow.md#2",
    )
    assert completed.returncode == 0, completed.stderr
    inserted = git_kb(
        "edit", "insert", "knowledge/workflow.md", "--after", "top", stdin="## Zeroth\n\nText."
    )
    assert inserted.returncode == 0, inserted.stderr

    finished = git_kb("curate", "finish", run, "--no-push")

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.startswith(
        "Renumbered destination: front.md: knowledge/workflow.md#2 -> "
        "knowledge/workflow.md#3 | Second\n"
    )
    assert _destinations(git_kb, run, "front.md") == [
        {"locator": "knowledge/workflow.md#3", "heading": "Second"}
    ]


def test_a_removed_destination_heading_names_amend_and_amend_fixes_it(git_kb: Kb) -> None:
    run = _batch(git_kb, "front.md")
    completed = git_kb(
        "curate",
        "complete",
        run,
        "front.md",
        "--disposition",
        "incorporated",
        "knowledge/workflow.md#1",
    )
    assert completed.returncode == 0, completed.stderr
    renamed = git_kb(
        "edit", "replace", "knowledge/workflow.md#1", stdin="## Renamed\n\nFirst fact."
    )
    assert renamed.returncode == 0, renamed.stderr

    refused = git_kb("curate", "finish", run, "--no-push")
    amended = git_kb("curate", "amend", run, "front.md", "knowledge/workflow.md#2")
    finished = git_kb("curate", "finish", run, "--no-push")

    assert refused.returncode == 1
    assert refused.stderr == (
        "curate: a destination heading changed for front.md; correct it with: "
        f"kb curate amend {run} front.md LOCATOR...\n"
    )
    assert amended.returncode == 0, amended.stderr
    assert amended.stdout == (
        "Amended: front.md -> knowledge/workflow.md#2\n"
        "Cited: observations/archived/front.md in knowledge/workflow.md#2\n"
    )
    assert finished.returncode == 0, finished.stderr
    assert _destinations(git_kb, run, "front.md") == [
        {"locator": "knowledge/workflow.md#2", "heading": "Second"}
    ]


def test_amend_refuses_members_that_are_not_completed_with_destinations(git_kb: Kb) -> None:
    run = _batch(git_kb, "front.md", "brief.md")
    git_kb(
        "curate",
        "complete",
        run,
        "brief.md",
        "--disposition",
        "ephemeral",
        "--reason",
        "Session detail",
    )

    pending = git_kb("curate", "amend", run, "front.md", "knowledge/workflow.md#1")
    ephemeral = git_kb("curate", "amend", run, "brief.md", "knowledge/workflow.md#1")
    usage = git_kb("curate", "amend", run, "front.md")

    message = "curate: only a completed incorporated or duplicate member can be amended\n"
    assert pending.stderr == message
    assert ephemeral.stderr == message
    assert usage.stderr == "Usage: kb curate amend RUN FILENAME LOCATOR...\n"

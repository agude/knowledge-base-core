"""End-to-end tests for compatibility with the old scripts in ~/Knowledge/scripts.

Skipped unless KB_OLD_TOOLING is set to a checkout of the old tooling. `just
test-compat` sets it. Each test copies the fixture into a temporary Git
repository, points the old scripts at it with KB_CONTENT_DIR, and leaves the
real content untouched.
"""

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .harness import Kb

OLD_TOOLING = os.environ.get("KB_OLD_TOOLING", "")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
BATCH_ID = re.compile(r"Created batch: ([0-9]{8}T[0-9]{6}-[0-9a-f]{8})\n")
WROTE_PREFIX = "Wrote: observations/pending/"
pytestmark = pytest.mark.skipif(not OLD_TOOLING, reason="KB_OLD_TOOLING is not set")


def old_script(name: str) -> Path:
    """The file `name` in the scripts directory of the checkout that KB_OLD_TOOLING names.

    Raises AssertionError when the checkout does not have it.
    """
    path = Path(OLD_TOOLING).expanduser() / "scripts" / name
    assert path.is_file(), f"KB_OLD_TOOLING has no scripts/{name}: {path}"
    return path


def run_old(
    kb: Kb,
    name: str,
    *args: str,
    env: Mapping[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an old script with the test's content repository as its content directory."""
    overrides = {"KB_CONTENT_DIR": str(kb.content), **(env or {})}
    return subprocess.run(
        [str(old_script(name)), *args],
        cwd=kb.home,
        env=kb.environment(overrides),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def written_name(result: subprocess.CompletedProcess[str]) -> str:
    """The file name from a successful run's Wrote line, whichever script printed it."""
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(WROTE_PREFIX), result.stdout
    assert result.stdout.endswith("\n"), result.stdout
    return result.stdout[len(WROTE_PREFIX) : -1]


def read_pending(kb: Kb, name: str) -> str:
    """The text of a file in observations/pending."""
    return (kb.content / "observations" / "pending" / name).read_text(encoding="utf-8")


def without_created_or_attribution(text: str) -> list[str]:
    """The lines that must match between the two scripts: all but created, project, and host."""
    return [
        line
        for line in text.splitlines(keepends=True)
        if not line.startswith(("created: ", "project: ", "host: "))
    ]


def old_field(kb: Kb, field: str, name: str) -> str:
    """The value that the old frontmatter_field prints for one field of a pending file."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" && frontmatter_field "$2" "$3"',
            "bash",
            str(old_script("_lib.sh")),
            field,
            str(kb.content / "observations" / "pending" / name),
        ],
        cwd=kb.home,
        env=kb.environment({"KB_CONTENT_DIR": str(kb.content)}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.removesuffix("\n")


def old_question_field(kb: Kb, field: str, name: str) -> str:
    """Read a question field with the old tooling's YAML front-matter helper."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1" && frontmatter_field "$2" "$3"',
            "bash",
            str(old_script("_lib.sh")),
            field,
            str(kb.content / "questions" / "open" / name),
        ],
        cwd=kb.home,
        env=kb.environment({"KB_CONTENT_DIR": str(kb.content)}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.removesuffix("\n")


def test_kb_observe_writes_what_the_old_script_writes_plus_attribution(git_kb: Kb) -> None:
    title = 'Say "hi" \\ there'
    body = "Written by both scripts."
    old = run_old(git_kb, "observe", "--title", title, "--body", body)
    new = git_kb("observe", "--title", title, "--body", body)
    old_text = read_pending(git_kb, written_name(old))
    new_text = read_pending(git_kb, written_name(new))
    assert without_created_or_attribution(new_text) == without_created_or_attribution(old_text)
    assert "project: " not in old_text
    assert "host: " not in old_text
    assert "project: " in new_text
    assert "host: " in new_text
    assert git_kb.git("log", "--format=%s", "-2") == f"Observe: {title}\n" * 2


def test_old_frontmatter_field_reads_kb_files_as_it_reads_old_files(git_kb: Kb) -> None:
    old = written_name(run_old(git_kb, "observe", "--title", "Field check", "--body", "Read."))
    new = written_name(git_kb("observe", "--title", "Field check", "--body", "Read."))
    for field in ("title", "source"):
        assert old_field(git_kb, field, new) == old_field(git_kb, field, old)
    assert old_field(git_kb, "title", new) == "Field check"
    assert old_field(git_kb, "source", new) == "session"
    for name in (old, new):
        assert TIMESTAMP.fullmatch(old_field(git_kb, "created", name))


def test_old_stale_and_lint_accept_an_article_written_by_kb_verify(git_kb: Kb) -> None:
    article = git_kb.content / "knowledge" / "infra" / "nas.md"
    text = article.read_text(encoding="utf-8")
    article.write_text(
        text.replace('title: "NAS"\n', 'title: "NAS"\nupdated: 2026-10-20\n'), encoding="utf-8"
    )

    verified = git_kb("verify", "knowledge/infra/nas.md")
    assert verified.returncode == 0, verified.stderr

    linted = run_old(git_kb, "lint", "--path", "knowledge/infra/nas.md")
    assert linted.returncode == 0, linted.stderr
    assert "0 error(s)" in linted.stdout

    today_epoch = int(datetime(2026, 10, 26, tzinfo=UTC).timestamp())
    stale = run_old(
        git_kb,
        "stale",
        "--path",
        "knowledge/infra",
        env={"FRESHNESS_TODAY_EPOCH": str(today_epoch)},
    )
    assert stale.returncode == 0, stale.stderr
    assert "knowledge/infra/nas.md" not in stale.stdout


def test_old_pending_lists_a_kb_observation_with_its_title(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Listed title", "--body", "Listed body."))
    listing = run_old(git_kb, "pending")
    assert listing.returncode == 0, listing.stderr
    assert "Listed title" in listing.stdout
    assert f"[{name}]" in listing.stdout


def test_old_archive_moves_a_kb_observation_and_commits_it(git_kb: Kb) -> None:
    name = written_name(git_kb("observe", "--title", "Archived title", "--body", "Archived body."))
    archived = run_old(git_kb, "archive", name)
    assert archived.returncode == 0, archived.stderr
    assert archived.stdout == f"Archived: observations/pending/{name}\n"
    assert not (git_kb.content / "observations" / "pending" / name).exists()
    assert (git_kb.content / "observations" / "archived" / name).is_file()
    assert git_kb.git("log", "-1", "--format=%s") == "Archive: 1 observation(s)\n"
    assert git_kb.git("status", "--porcelain") == ""


def test_old_questions_and_resolve_accept_a_gap_with_quoted_unicode_fields(git_kb: Kb) -> None:
    title = 'Where is "München" \\ backup?'
    context = "knowledge/infra/nas.md"
    body = "The answer is not recorded."
    result = git_kb("gap", "--title", title, "--body", body, "--context", context)
    assert result.returncode == 0, result.stderr
    prefix = "Wrote: questions/open/"
    assert result.stdout.startswith(prefix), result.stdout
    name = result.stdout[len(prefix) :].removesuffix("\n")

    listing = run_old(git_kb, "questions")
    assert listing.returncode == 0, listing.stderr
    assert f"- {title} ({context})" in listing.stdout
    inspection = run_old(git_kb, "questions", "--file", name)
    assert inspection.returncode == 0, inspection.stderr
    assert body in inspection.stdout
    assert old_question_field(git_kb, "title", name) == title
    assert old_question_field(git_kb, "context", name) == context
    assert old_question_field(git_kb, "source", name) == "session"

    answer = "See the archived note: café backup remains unknown."
    resolved = run_old(git_kb, "resolve", "--file", name, "--answer", answer)
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout == f"Resolved: questions/open/{name} -> questions/resolved/{name}\n"
    resolved_path = git_kb.content / "questions" / "resolved" / name
    resolved_text = resolved_path.read_text(encoding="utf-8")
    assert resolved_text.startswith(inspection.stdout.split("\n\n## Resolution", 1)[0])
    assert answer in resolved_text
    assert 'title: "Where is \\"München\\" \\\\ backup?"\n' in resolved_text
    assert f'context: "{context}"\n' in resolved_text
    assert 'project: "' in resolved_text
    assert 'host: "' in resolved_text
    assert git_kb.git("log", "-1", "--format=%s") == f"Resolve: {title}\n"
    assert not (git_kb.content / "questions" / "open" / name).exists()
    assert git_kb.git("status", "--porcelain") == ""


def test_old_questions_reads_a_question_resolved_by_kb_resolve(git_kb: Kb) -> None:
    gap = git_kb(
        "gap",
        "--title",
        "Old questions reads resolved answers",
        "--body",
        "The old reader must find this answer.",
        "--context",
        "infra",
    )
    assert gap.returncode == 0, gap.stderr
    name = gap.stdout.removeprefix("Wrote: questions/open/").removesuffix("\n")
    new = git_kb("resolve", f"questions/open/{name}", "--answer", "Retired.", "--obsolete")
    assert new.returncode == 0, new.stderr

    old = run_old(git_kb, "questions", "--file", name)

    assert old.returncode == 0, old.stderr
    assert "The old reader must find this answer." in old.stdout
    assert "## Resolution (2026-10-26)" in old.stdout


def test_kb_questions_all_reads_a_question_resolved_by_the_old_script(git_kb: Kb) -> None:
    gap = git_kb(
        "gap",
        "--title",
        "New questions reads old resolutions",
        "--body",
        "The new reader must list this answer.",
        "--context",
        "infra",
    )
    assert gap.returncode == 0, gap.stderr
    name = gap.stdout.removeprefix("Wrote: questions/open/").removesuffix("\n")
    old = run_old(git_kb, "resolve", "--file", name, "--answer", "Retired.")
    assert old.returncode == 0, old.stderr

    new = git_kb("questions", "--all")

    assert new.returncode == 0, new.stderr
    assert f"questions/resolved/{name} |" in new.stdout
    assert "| resolved | knowledge/infra | New questions reads old resolutions" in new.stdout


def test_kb_observe_waits_for_a_legacy_lock_until_the_old_script_releases_it(
    git_kb: Kb,
) -> None:
    holder = subprocess.Popen(
        [
            "bash",
            "-c",
            'source "$1" && acquire_lock && echo locked && { read -r _ || true; } && release_lock',
            "bash",
            str(old_script("_lib.sh")),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=git_kb.environment({"KB_CONTENT_DIR": str(git_kb.content)}),
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        observer = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kb",
                "observe",
                "--title",
                "After the lock",
                "--body",
                "Waited for the old lock.",
            ],
            cwd=git_kb.home,
            env=git_kb.environment({"KB_LOCK_WAIT": "10"}),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        time.sleep(1.5)
        assert observer.poll() is None, "kb observe finished while the old lock was held"
        holder.stdin.close()
        stdout, stderr = observer.communicate(timeout=30)
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert observer.returncode == 0, stderr
    assert stdout.startswith(WROTE_PREFIX)
    assert git_kb.git("log", "-1", "--format=%s") == "Observe: After the lock\n"
    assert not (git_kb.content / ".observe.lock").exists()


def test_old_and_new_readers_accept_new_and_legacy_archives(git_kb: Kb) -> None:
    archived_directory = git_kb.content / "observations" / "archived"
    archived_directory.mkdir(parents=True, exist_ok=True)
    (archived_directory / "legacy-no-metadata.md").write_text(
        "---\ntitle: Legacy archive without metadata\ncreated: 2020-01-01\n---\n"
        "\n## 1. Legacy evidence\n\nAtoll copper lattice measurements.\n",
        encoding="utf-8",
    )
    (archived_directory / "legacy-processed.md").write_text(
        "---\ntitle: Legacy processed outcome\ndisposition: processed\n---\n"
        "\n## 1. Legacy outcome\n\nAmber whirlpool oscillator records.\n",
        encoding="utf-8",
    )
    git_kb.git("add", "--all")
    git_kb.git("commit", "-q", "-m", "Add legacy archive fixtures")

    observed = git_kb(
        "observe",
        "--title",
        "Quartz pendulum calibration",
        "--body",
        "## 1. Calibration\n\nQuartz pendulum calibration measurements.",
    )
    name = written_name(observed)
    started = git_kb("curate", "start", "--no-sync", "--max-bytes", "65536", name)
    assert started.returncode == 0, started.stderr
    match = BATCH_ID.search(started.stdout)
    assert match is not None, started.stdout
    run_id = match.group(1)
    manifest = json.loads(
        (git_kb.content / "observations" / "batches" / f"{run_id}.json").read_text(encoding="utf-8")
    )
    assert [member["filename"] for member in manifest["members"]] == [name]

    article = git_kb.content / "knowledge" / "archive-compatibility.md"
    article.write_text(
        "---\ntitle: Archive compatibility\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\nsources:\n"
        f"  - observations/archived/{name}#1-calibration\n"
        "---\n# Archive compatibility\n\n## 1. Imported finding\n\n"
        "The calibrated values remain available.\n",
        encoding="utf-8",
    )
    archived = git_kb(
        "curate",
        "complete",
        run_id,
        name,
        "--disposition",
        "incorporated",
        "knowledge/archive-compatibility.md#1",
    )
    assert archived.returncode == 0, archived.stderr

    old_pending = run_old(git_kb, "pending")
    assert old_pending.returncode == 0, old_pending.stderr
    assert "Quartz pendulum calibration" not in old_pending.stdout
    old_search = run_old(
        git_kb,
        "search",
        "--query",
        "Quartz pendulum calibration",
        "--corpus",
        "archive",
    )
    assert old_search.returncode == 0, old_search.stderr
    assert f"observations/archived/{name}" in old_search.stdout
    old_lint = run_old(git_kb, "lint", "--path", "knowledge/archive-compatibility.md")
    assert old_lint.returncode == 0, old_lint.stderr

    for legacy, phrase in (
        ("legacy-no-metadata.md", "Atoll copper lattice measurements."),
        ("legacy-processed.md", "Amber whirlpool oscillator records."),
    ):
        read = git_kb("read", f"observations/archived/{legacy}#1")
        assert read.returncode == 0, read.stderr
        assert phrase in read.stdout
    recalled = git_kb("recall", "amber whirlpool oscillator")
    assert recalled.returncode == 0, recalled.stderr
    assert "observations/archived/legacy-processed.md" in recalled.stdout


def test_kb_finish_commits_through_the_old_hook_and_old_tools_read_the_result(
    remote_git_kb: Kb,
) -> None:
    kb = remote_git_kb
    hook = kb.content / ".git" / "hooks" / "pre-commit"
    hook.symlink_to(old_script("hooks/pre-commit"))
    _write(
        kb.content / "knowledge" / "compat-finish.md",
        "---\ntitle: Compat finish\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
        "# Compat finish\n\n## 1. Fact\n\nA fact finished through kb.\n",
    )
    _write(
        kb.content / "observations" / "pending" / "compat-note.md",
        "---\ntitle: Compat note\ncreated: 2026-10-24\n---\n\n## 1. Note\n\nA note.\n",
    )
    kb.git("add", "--all")
    kb.git("commit", "-q", "-m", "Prepare compatibility batch")
    started = kb("curate", "start", "--max-bytes", "100000", "compat-note.md")
    assert started.returncode == 0, started.stderr
    run = BATCH_ID.search(started.stdout)
    assert run is not None, started.stdout
    completed = kb(
        "curate",
        "complete",
        run.group(1),
        "compat-note.md",
        "--disposition",
        "incorporated",
        "knowledge/compat-finish.md#1",
    )
    assert completed.returncode == 0, completed.stderr

    finished = kb("curate", "finish", run.group(1))

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert "Published: origin/main\n" in finished.stdout
    linted = run_old(kb, "lint", "--path", "knowledge/compat-finish.md")
    assert linted.returncode == 0, linted.stdout + linted.stderr
    section = run_old(kb, "section", "--file", "knowledge/compat-finish.md", "--number", "1")
    assert section.returncode == 0, section.stderr
    assert "A fact finished through kb." in section.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_hook_that_kb_setup_installs_takes_old_writes_and_stamps_a_new_edit(git_kb: Kb) -> None:
    shim = git_kb.home / "bin" / "kb"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    installed = git_kb("setup", "--content", str(git_kb.content), "--kb", str(shim))
    assert installed.returncode == 0, installed.stderr

    name = written_name(
        run_old(
            git_kb, "observe", "--title", "Compat hook", "--body", "Written by the old observe."
        )
    )
    archived = run_old(git_kb, "archive", name)
    assert archived.returncode == 0, archived.stderr
    assert git_kb.git("log", "-1", "--format=%s") == "Archive: 1 observation(s)\n"

    article = git_kb.content / "knowledge" / "infra" / "backups.md"
    article.write_text(
        "---\ntitle: Backups\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
        "# Backups\n\n## 1. Schedule\n\nNightly and weekly.\n",
        encoding="utf-8",
    )
    git_kb.git("add", "--", "knowledge/infra/backups.md")
    commit = subprocess.run(
        ["git", "commit", "-q", "-m", "Describe the backup schedule"],
        cwd=git_kb.content,
        env=git_kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert commit.returncode == 0, commit.stderr
    assert "hook: stamped updated: 2026-10-26 on 1 article(s)" in commit.stderr
    assert "updated: 2026-10-26\n" in git_kb.git("show", "HEAD:knowledge/infra/backups.md")

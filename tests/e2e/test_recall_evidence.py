"""End-to-end tests for the evidence parts of `kb recall`."""

import shutil
from pathlib import Path

import pytest

from .harness import Kb, make_kb

EVIDENCE_CONTENT = Path(__file__).resolve().parents[1] / "fixtures" / "evidence-content"
CONTINUATION = "observations/archived/20261021T120000-abcd1234.md"
SUBAGENT = "observations/pending/20261022T090000-dcba4321.md"


@pytest.fixture
def evidence_kb(tmp_path: Path) -> Kb:
    """A kb runner with synthetic addressable transcripts and mixed evidence."""
    runner = make_kb(tmp_path)
    shutil.copytree(EVIDENCE_CONTENT, runner.content, dirs_exist_ok=True)
    return runner


def add_question(kb: Kb, name: str, title: str, context: str, body: str) -> None:
    """Add a synthetic open question to this test's private content copy."""
    path = kb.content / "questions" / "open" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\ncontext: {context}\ncreated: 2026-10-26\n---\n\n{body}\n",
        encoding="utf-8",
    )


def uncurated_rows(output: str) -> list[list[str]]:
    """The four uncurated evidence columns without their visual padding."""
    block = output.split("Uncurated (pending, not yet verified):\n", 1)[1]
    block = block.split("Read with: kb read <locator>", 1)[0]
    return [
        [column.strip() for column in line[2:].split(" | ", 3)]
        for line in block.splitlines()
        if line.startswith("  ")
    ]


def test_no_curated_match_lists_archived_evidence(kb: Kb) -> None:
    result = kb("recall", "label", "printer", "driver")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "label printer driver".\n'
        "Evidence:\n"
        "  observations/archived/20260615T083000-9a8b7c6d.md | 2026-06-15 | observation | "
        "Old label printer note\n"
        "Read with: kb read <locator>\n"
    )


def test_transcript_evidence_shows_the_best_matching_line(kb: Kb) -> None:
    result = kb("recall", "outage", "start", "services", "order")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "outage start services order".\n'
        "Evidence:\n"
        "  observations/archived/20260903T120000-c3d4e5f6.md | 2026-09-03 | transcript | "
        "After the outage, what order should the services start in?\n"
        "Read with: kb read <locator>\n"
    )


def test_open_question_is_evidence_with_its_kind(kb: Kb) -> None:
    result = kb("recall", "disk", "owner", "listed")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "disk owner listed".\n'
        "Evidence:\n"
        "  questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open question | "
        "Who owns the backup disk?\n"
        "Read with: kb read <locator>\n"
    )


def test_pending_observation_is_evidence_when_nothing_curated_matches(kb: Kb) -> None:
    result = kb("recall", "firmware", "upgrade", "plex")
    assert result.returncode == 0
    assert result.stdout == (
        'No curated knowledge matches "firmware upgrade plex".\n'
        "Evidence:\n"
        "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 | observation | "
        "NAS restart after the update\n"
        "Read with: kb read <locator>\n"
    )


def test_uncurated_pending_transcript_shows_its_matching_line(kb: Kb) -> None:
    result = kb("recall", "family", "share")
    assert result.returncode == 0
    assert result.stdout == (
        "knowledge/infra/syncthing.md#1 | Folder layout | fresh, verified 2026-10-20 | 0 sources\n"
        "## Folder layout\n"
        "\n"
        "The family share is /srv/sync/family, one folder per family member.\n"
        "\n"
        "knowledge/infra/syncthing.md#top | Syncthing | fresh, verified 2026-10-20 | 0 sources\n"
        "# Syncthing\n"
        "\n"
        "Syncthing keeps the family folders in step across the laptops.\n"
        "\n"
        "Uncurated (pending, not yet verified):\n"
        "  observations/pending/20261025T180000-1f2e3d4c.md | 2026-10-25 | transcript | "
        "Which folder does the family share use on the NAS?\n"
        "Read with: kb read <locator>\n"
    )


def test_pending_observation_is_uncurated_beside_curated_results(kb: Kb) -> None:
    result = kb("recall", "nas", "restart", "order")
    assert result.returncode == 0
    assert result.stdout.endswith(
        "Uncurated (pending, not yet verified):\n"
        "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 | observation | "
        "NAS restart after the update\n"
        "Read with: kb read <locator>\n"
    )


def test_matching_open_question_appears_beside_curated_results(evidence_kb: Kb) -> None:
    result = evidence_kb("recall", "backup", "disk")
    assert result.returncode == 0
    assert "knowledge/infra/backups.md#top" in result.stdout
    assert "Uncurated (pending, not yet verified):\n" in result.stdout
    rows = uncurated_rows(result.stdout)
    assert any(
        row[0] == "questions/open/20261001T090000-bbbb2222.md"
        and row[2] == "open question"
        and row[3] == "Who owns the backup disk?"
        for row in rows
    )
    assert any(row[0] == f"{SUBAGENT}#1" and row[2] == "transcript" for row in rows)
    assert "questions/resolved/" not in result.stdout
    assert "observations/archived/" not in result.stdout


def test_curated_hit_uses_message_locator_for_pending_transcripts(evidence_kb: Kb) -> None:
    result = evidence_kb("recall", "backup", "disk")
    assert result.returncode == 0
    assert any(
        row[0] == f"{SUBAGENT}#1" and row[1] == "2026-10-22" and row[2] == "transcript"
        for row in uncurated_rows(result.stdout)
    )


def test_fallback_uses_addressable_message_date_and_locator(evidence_kb: Kb) -> None:
    result = evidence_kb("recall", "queue", "credentials")
    assert result.returncode == 0
    assert result.stdout.startswith(
        'No curated knowledge matches "queue credentials".\nEvidence:\n'
    )
    assert f"{CONTINUATION}#2 | 2026-10-20 | transcript | The queue waited for credentials." in (
        result.stdout
    )


def test_question_context_can_match_a_curated_file_scope(kb: Kb) -> None:
    result = kb("recall", "disk", "owner", "listed", "--in", "knowledge/infra/backups.md")
    assert result.returncode == 0
    assert result.stdout.startswith(
        'No curated knowledge matches "disk owner listed".\nEvidence:\n'
    )
    assert "questions/open/20261001T090000-bbbb2222.md" in result.stdout
    assert "| open question | Who owns the backup disk?" in result.stdout
    assert "observations/" not in result.stdout


def test_question_storage_scope_still_works_for_non_area_paths(kb: Kb) -> None:
    result = kb("recall", "disk", "owner", "listed", "--in", "questions/open")
    assert result.returncode == 0
    assert "questions/open/20261001T090000-bbbb2222.md" in result.stdout


def test_question_context_resolves_legacy_and_explicit_paths(kb: Kb) -> None:
    add_question(
        kb,
        "explicit-context.md",
        "Who owns the explicit backup disk?",
        "knowledge/infra",
        "The backup disk owner should be listed.",
    )
    add_question(
        kb,
        "ambiguous-context.md",
        "Who owns the ambiguous backup disk?",
        "backups.md",
        "The backup disk owner should be listed.",
    )
    add_question(
        kb,
        "unrelated-context.md",
        "Who owns the unrelated backup disk?",
        "knowledge/home",
        "The backup disk owner should be listed.",
    )
    add_question(
        kb,
        "missing-context.md",
        "Who owns the missing-context backup disk?",
        "",
        "The backup disk owner should be listed.",
    )

    unfiltered = kb("recall", "disk", "owner", "listed")
    assert "questions/open/missing-context.md" in unfiltered.stdout

    result = kb("recall", "disk", "owner", "listed", "--in", "nas.md")
    assert result.returncode == 0
    assert "questions/open/20261001T090000-bbbb2222.md" in result.stdout
    assert "questions/open/explicit-context.md" in result.stdout
    assert "questions/open/ambiguous-context.md" not in result.stdout
    assert "questions/open/unrelated-context.md" not in result.stdout
    assert "questions/open/missing-context.md" not in result.stdout


def test_question_context_uses_component_boundaries(kb: Kb) -> None:
    infrared = kb.content / "knowledge" / "infrared.md"
    infrared.write_text("# Infrared\n\nAn unrelated article.\n", encoding="utf-8")
    result = kb("recall", "disk", "owner", "listed", "--in", "knowledge/infrared.md")
    assert result.returncode == 0
    assert result.stdout == 'No curated knowledge matches "disk owner listed".\n'


def test_matching_context_does_not_qualify_a_question_without_text_match(kb: Kb) -> None:
    result = kb("recall", "quantum", "--in", "knowledge/infra")
    assert result.returncode == 0
    assert result.stdout == 'No curated knowledge matches "quantum".\n'


def test_deleted_context_is_filterable_without_inference_to_a_moved_article(kb: Kb) -> None:
    moved = kb.content / "knowledge" / "projects" / "shapez2" / "new-routing.md"
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text(
        "---\ntitle: New route notes\n---\n\nUnrelated route notes.\n", encoding="utf-8"
    )
    add_question(
        kb,
        "deleted-context.md",
        "Who owns the route selector?",
        "knowledge/projects/shapez2/routing.md",
        "The route selector owner is unknown.",
    )

    directory = kb("recall", "route", "selector", "owner", "--in", "knowledge/projects/shapez2")
    assert directory.returncode == 0
    assert "questions/open/deleted-context.md" in directory.stdout

    moved_file = kb(
        "recall", "route", "selector", "owner", "--in", "knowledge/projects/shapez2/new-routing.md"
    )
    assert moved_file.returncode == 0
    assert moved_file.stdout == 'No curated knowledge matches "route selector owner".\n'

"""End-to-end tests for deliberate evidence search."""

import shutil
from pathlib import Path

import pytest

from .harness import Kb, make_kb

EVIDENCE_CONTENT = Path(__file__).resolve().parents[1] / "fixtures" / "evidence-content"
CONTINUATION = "observations/archived/20261021T120000-abcd1234.md"
SUBAGENT = "observations/pending/20261022T090000-dcba4321.md"


@pytest.fixture
def kb(tmp_path: Path) -> Kb:
    """A fixture content repo with the synthetic evidence records overlaid."""
    runner = make_kb(tmp_path)
    shutil.copytree(EVIDENCE_CONTENT, runner.content, dirs_exist_ok=True)
    return runner


def evidence_rows(output: str) -> list[list[str]]:
    """The four columns between the Evidence heading and the read hint."""
    lines = output.splitlines()
    start = lines.index("Evidence:") + 1
    stop = lines.index("Read with: kb read <locator>")
    return [
        [column.strip() for column in line.strip().split(" | ", 3)] for line in lines[start:stop]
    ]


def test_help_registers_the_evidence_command(kb: Kb) -> None:
    result = kb("evidence", "--help")
    assert result.returncode == 0
    assert result.stdout.startswith(
        "Usage: kb evidence QUERY... [--kind KIND] [--since DATE] [--until DATE] [--limit N]\n"
    )


def test_searches_observations_and_questions_together(kb: Kb) -> None:
    result = kb("evidence", "backup", "disk")
    assert result.returncode == 0
    rows = evidence_rows(result.stdout)
    assert {row[2] for row in rows} == {"observation", "open question", "transcript"}
    assert any(row[0] == "observations/pending/20261023T090000-1234abcd.md" for row in rows)
    assert any(row[0] == "questions/open/20261001T090000-bbbb2222.md" for row in rows)
    matching_transcripts = [row for row in rows if row[0].startswith(SUBAGENT)]
    assert matching_transcripts == [
        next(row for row in rows if row[0] == f"{SUBAGENT}#1" and row[2] == "transcript")
    ]


def test_kind_filters_select_each_supported_kind(kb: Kb) -> None:
    cases = (
        ("observation", ("backup", "disk"), "observations/pending/20261023T090000-1234abcd.md"),
        ("transcript", ("backup", "disk"), f"{SUBAGENT}#1"),
        ("open-question", ("backup", "disk"), "questions/open/20261001T090000-bbbb2222.md"),
        ("resolved-question", ("plex", "cache"), "questions/resolved/20260915T120000-cccc3333.md"),
    )
    for kind, query, locator in cases:
        result = kb("evidence", *query, "--kind", kind)
        assert result.returncode == 0
        rows = evidence_rows(result.stdout)
        assert rows
        assert all(row[2].replace(" ", "-") == kind for row in rows)
        assert any(row[0] == locator for row in rows)


def test_legacy_transcripts_keep_file_locators(kb: Kb) -> None:
    result = kb("evidence", "outage", "start", "services", "order", "--kind", "transcript")
    assert result.returncode == 0
    rows = evidence_rows(result.stdout)
    assert len(rows) == 1
    assert rows[0][0] == "observations/archived/20260903T120000-c3d4e5f6.md"
    assert rows[0][2] == "transcript"
    assert rows[0][1] == "2026-09-03"


def test_addressable_message_locator_uses_utc_message_date(kb: Kb) -> None:
    result = kb(
        "evidence",
        "queue",
        "credentials",
        "--since",
        "2026-10-20",
        "--until",
        "2026-10-20",
    )
    assert result.returncode == 0
    rows = evidence_rows(result.stdout)
    assert len(rows) == 1
    assert rows[0][0] == f"{CONTINUATION}#2"
    assert rows[0][1] == "2026-10-20"
    assert rows[0][2] == "transcript"
    assert "queue" in rows[0][3]


def test_message_search_includes_shell_commands_and_ignores_fenced_headings(kb: Kb) -> None:
    command = kb("evidence", "journalctl", "cache", "refresh")
    assert command.returncode == 0
    assert evidence_rows(command.stdout)[0][0] == f"{CONTINUATION}#3"

    fenced = kb("evidence", "fenced", "sentinel")
    assert fenced.returncode == 0
    assert evidence_rows(fenced.stdout)[0][0] == f"{CONTINUATION}#4"


def test_cross_message_match_keeps_the_file_locator(kb: Kb) -> None:
    result = kb("evidence", "upload", "queue", "forward", "server")
    assert result.returncode == 0
    rows = evidence_rows(result.stdout)
    assert any(row[0] == CONTINUATION for row in rows)


def test_title_only_transcript_match_keeps_file_date_and_excerpt(kb: Kb) -> None:
    result = kb("evidence", "backup", "handoff")
    assert result.returncode == 0
    rows = evidence_rows(result.stdout)
    row = next(row for row in rows if row[0] == CONTINUATION)
    assert row[1] == "2026-10-21"
    assert row[3]


def test_date_bounds_are_inclusive_and_exclude_messages_outside_the_range(kb: Kb) -> None:
    result = kb(
        "evidence",
        "queue",
        "credentials",
        "--since",
        "2026-10-21",
        "--until",
        "2026-10-21",
    )
    assert result.returncode == 0
    assert result.stdout == 'No evidence matches "queue credentials".\n'

    created_date = kb(
        "evidence",
        "backup",
        "disk",
        "--kind",
        "observation",
        "--since",
        "2026-10-23",
        "--until",
        "2026-10-23",
    )
    assert created_date.returncode == 0
    assert evidence_rows(created_date.stdout)[0][1] == "2026-10-23"


def test_unknown_created_dates_are_shown_but_excluded_by_date_bounds(kb: Kb) -> None:
    unfiltered = kb("evidence", "undated", "raven")
    assert unfiltered.returncode == 0
    row = evidence_rows(unfiltered.stdout)[0]
    assert row[0] == "observations/pending/20261026T100000-9876abcd.md"
    assert row[1] == ""

    filtered = kb("evidence", "undated", "raven", "--since", "2026-10-01")
    assert filtered.returncode == 0
    assert filtered.stdout == 'No evidence matches "undated raven".\n'


def test_limit_applies_after_ranking_and_each_file_appears_once(kb: Kb) -> None:
    result = kb("evidence", "backup", "disk", "--limit", "1")
    assert result.returncode == 0
    assert len(evidence_rows(result.stdout)) == 1


def test_no_match_output(kb: Kb) -> None:
    result = kb("evidence", "zzqx", "frobnicate")
    assert result.returncode == 0
    assert result.stdout == 'No evidence matches "zzqx frobnicate".\n'


def test_selected_message_locator_is_readable(kb: Kb) -> None:
    result = kb("read", f"{CONTINUATION}#2")
    assert result.returncode == 0
    assert "## 2. assistant, 2026-10-20T10:01:00Z" in result.stdout
    assert "The queue waited for credentials." in result.stdout


def test_invalid_dates_and_reversed_range_are_rejected(kb: Kb) -> None:
    for option, value in (("--since", "2026-2-01"), ("--until", "2026-02-30")):
        result = kb("evidence", "backup", option, value)
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == f"evidence: {option} must be YYYY-MM-DD\n"

    reversed_range = kb("evidence", "backup", "--since", "2026-10-23", "--until", "2026-10-22")
    assert reversed_range.returncode == 1
    assert reversed_range.stdout == ""
    assert reversed_range.stderr == "evidence: --since must not be after --until\n"


def test_invalid_kind_and_limit_are_rejected(kb: Kb) -> None:
    invalid_kind = kb("evidence", "backup", "--kind", "question")
    assert invalid_kind.returncode == 1
    assert invalid_kind.stdout == ""
    assert invalid_kind.stderr == (
        "evidence: --kind must be one of observation, transcript, open-question, resolved-question\n"
    )

    invalid_limit = kb("evidence", "backup", "--limit", "0")
    assert invalid_limit.returncode == 1
    assert invalid_limit.stdout == ""
    assert invalid_limit.stderr == "Option --limit must be a positive integer\n"


def test_query_is_required(kb: Kb) -> None:
    result = kb("evidence", "--kind", "observation")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Usage: kb evidence QUERY... [--kind KIND] [--since DATE] [--until DATE] [--limit N]\n"
    )

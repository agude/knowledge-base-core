"""Tests for the kb usage report: recall parsing, tags, metrics, week buckets, and --list."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import usage
from kb.transcripts import KbCall

BEFORE = datetime(2026, 10, 20, 10, tzinfo=UTC)
AFTER = datetime(2026, 11, 10, 10, tzinfo=UTC)
CURATED_ONLY = (
    "knowledge/infra/nas.md#1 | Restart order | fresh, verified 2026-08-16 | 1 source\n"
    "## Restart order\n"
    "  - an indented body line | with a bar\n"
    "Read with: kb read <locator>\n"
)
WITH_SESSIONS = (
    "knowledge/infra/nas.md#1 | Restart order | fresh | 1 source\n"
    "## Restart order\n"
    "\n"
    "Also relevant:\n"
    "  knowledge/infra/syncthing.md#2 | Restart order\n"
    "Uncurated (pending, not yet verified):\n"
    "  observations/pending/p1.md | 2026-10-24 | observation | NAS restart after update\n"
    "From sessions (raw, unverified, may be superseded):\n"
    "  observations/archived/t1.md#3 | 2026-10-21 | the restart order was confirmed\n"
    "Read with: kb read <locator>\n"
)
NO_MATCH = (
    'No curated knowledge matches "label printer".\n'
    "Evidence:\n"
    "  observations/archived/t2.md | 2026-06-15 | transcript | Old label printer note\n"
    "Read with: kb read <locator>\n"
)


def call(
    subcommand: str,
    *,
    moment: datetime | None,
    session: str = "s1",
    arguments: tuple[str, ...] = (),
    output: str | None = None,
    excluded: str | None = None,
) -> KbCall:
    """A kb call. Without output, it is excluded as missing, unless another reason is given."""
    if output is None and excluded is None:
        excluded = "missing"
    return KbCall(
        app="claude-code",
        session_id=session,
        timestamp=moment,
        project="/work",
        command=f"kb {subcommand} {' '.join(arguments)}",
        subcommand=subcommand,
        arguments=arguments,
        output=output,
        excluded=excluded,
    )


def test_curated_locators_are_tagged_curated_including_also_relevant() -> None:
    view = usage.parse_recall(WITH_SESSIONS)
    assert view.curated == ("knowledge/infra/nas.md#1", "knowledge/infra/syncthing.md#2")


def test_session_rows_are_tagged_session_and_uncurated_rows_are_not() -> None:
    view = usage.parse_recall(WITH_SESSIONS)
    assert view.sessions == ("observations/archived/t1.md#3",)
    tags = {item.locator: item.tag for item in view.shown}
    assert tags["observations/pending/p1.md"] == "uncurated"
    assert view.block is True


def test_an_indented_body_line_is_not_a_locator() -> None:
    view = usage.parse_recall(CURATED_ONLY)
    assert view.curated == ("knowledge/infra/nas.md#1",)
    assert view.block is False


def test_a_no_match_recall_has_evidence_rows_and_no_session_block() -> None:
    view = usage.parse_recall(NO_MATCH)
    assert view.no_match is True
    assert [(item.locator, item.tag) for item in view.shown] == [
        ("observations/archived/t2.md", "evidence")
    ]


def test_a_read_line_ends_the_parse() -> None:
    view = usage.parse_recall(CURATED_ONLY + "  trailing | after the read line\n")
    assert all("trailing" not in item.locator for item in view.shown)


@pytest.mark.parametrize(
    ("output", "excluded", "moment", "status"),
    [
        (None, "missing", AFTER, "excluded-missing"),
        (None, "shared", AFTER, "excluded-shared"),
        (NO_MATCH, None, AFTER, "no-curated-match"),
        (WITH_SESSIONS, None, AFTER, "session-rows"),
        (CURATED_ONLY, None, BEFORE, "pre-block"),
        (CURATED_ONLY, None, AFTER, "no-session-rows"),
    ],
)
def test_each_recall_is_tagged_by_its_block_and_time(
    output: str | None, excluded: str | None, moment: datetime, status: str
) -> None:
    recall = call("recall", moment=moment, output=output, excluded=excluded)
    view = usage.parse_recall(output) if output is not None else None
    assert usage.recall_status(recall, view) == status


def test_week_buckets_use_iso_weeks_and_unknown_has_its_own_bucket() -> None:
    sunday = datetime(2026, 10, 25, 12, tzinfo=UTC)
    monday = datetime(2026, 10, 26, 0, 30, tzinfo=UTC)
    assert usage.week_of(sunday) == "2026-W43"
    assert usage.week_of(monday) == "2026-W44"
    assert usage.week_of(None) == usage.UNKNOWN_WEEK


def test_recalls_and_their_outputs_count_per_week() -> None:
    report = usage.analyze(
        [
            call("recall", moment=datetime(2026, 10, 25, tzinfo=UTC), output=CURATED_ONLY),
            call("recall", moment=datetime(2026, 10, 26, tzinfo=UTC), output=WITH_SESSIONS),
            call("recall", moment=datetime(2026, 10, 26, 1, tzinfo=UTC), output=None),
        ]
    )
    rows = {row[0]: row for row in usage.weekly_rows(report)}
    assert rows["2026-W43"][1] == "1"
    # recalls, recalls_excluded, no_output, with_session_row, session_row_reads.
    assert rows["2026-W44"][1:6] == ["2", "1", "1", "1", "0"]
    assert rows["2026-W44"][8] == str(round(len(WITH_SESSIONS)))


def test_an_excluded_recall_counts_by_reason_and_is_not_parsed() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output=None, excluded="shared"),
            call("recall", moment=AFTER, output=None, excluded="batch"),
            call("recall", moment=AFTER, output=None),
        ]
    )
    week = report.weeks[usage.week_of(AFTER)]
    assert (week.recalls, week.recalls_excluded, week.no_output) == (3, 3, 1)
    assert report.excluded == {"shared": 1, "batch": 1, "missing": 1}
    assert week.mean_chars() == "n/a"


def test_a_read_after_an_excluded_recall_does_not_match_an_earlier_recall() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output=WITH_SESSIONS),
            call("recall", moment=AFTER, output=None, excluded="shared"),
            call("read", moment=AFTER, arguments=("observations/archived/t1.md#3",), output="x"),
        ]
    )
    assert report.weeks[usage.week_of(AFTER)].session_row_reads == 0


def test_the_render_reports_excluded_recalls_beside_the_tags() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output=WITH_SESSIONS),
            call("recall", moment=AFTER, output=None, excluded="shared"),
        ]
    )
    text = usage.render({}, report)
    assert "recall tags: excluded-shared=1, session-rows=1" in text
    assert "recall excluded by reason: shared=1" in text
    row = text.splitlines()[-1].split()
    # week, recalls, recalls_excluded, no_output, with_session_row, session_row_reads,
    # evidence_after_recall, gap_after_recall, mean_chars.
    assert row == ["2026-W46", "2", "1", "0", "1", "0", "0", "0", str(len(WITH_SESSIONS))]


def test_the_columns_are_the_counted_week_fields_and_the_mean() -> None:
    assert usage.COLUMNS == (
        "week",
        "recalls",
        "recalls_excluded",
        "no_output",
        "with_session_row",
        "session_row_reads",
        "evidence_after_recall",
        "gap_after_recall",
        "mean_chars",
    )
    report = usage.analyze([call("recall", moment=AFTER, output=CURATED_ONLY)])
    assert all(len(row) == len(usage.COLUMNS) for row in usage.weekly_rows(report))


def test_a_session_read_after_a_recall_that_showed_it_counts_once_in_its_week() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output=WITH_SESSIONS),
            call(
                "read",
                moment=AFTER,
                arguments=("observations/archived/t1.md#3",),
                output="text",
            ),
            call("read", moment=AFTER, arguments=("knowledge/infra/nas.md#1",), output="text"),
        ]
    )
    week = report.weeks[usage.week_of(AFTER)]
    assert week.session_row_reads == 1


def test_a_session_read_of_a_recall_without_curated_rows_is_counted_separately() -> None:
    no_curated = (
        "From sessions (raw, unverified, may be superseded):\n"
        "  observations/archived/t1.md#3 | 2026-10-21 | a row\n"
        "Read with: kb read <locator>\n"
    )
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output=no_curated),
            call("read", moment=AFTER, arguments=("observations/archived/t1.md#3",), output="x"),
        ]
    )
    week = report.weeks[usage.week_of(AFTER)]
    assert week.session_row_reads == 1


def test_a_read_in_another_session_does_not_match_the_recall() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, session="s1", output=WITH_SESSIONS),
            call(
                "read",
                moment=AFTER,
                session="s2",
                arguments=("observations/archived/t1.md#3",),
                output="x",
            ),
        ]
    )
    assert report.weeks[usage.week_of(AFTER)].session_row_reads == 0


def test_evidence_and_gap_count_only_after_a_recall_in_the_same_session() -> None:
    report = usage.analyze(
        [
            call("evidence", moment=AFTER, session="s1", arguments=("x",), output="y"),
            call("recall", moment=AFTER, session="s1", output=CURATED_ONLY),
            call("evidence", moment=AFTER, session="s1", arguments=("x",), output="y"),
            call("gap", moment=AFTER, session="s1", arguments=("--title", "t"), output="ok"),
            call("gap", moment=AFTER, session="s2", arguments=("--title", "t"), output="ok"),
        ]
    )
    week = report.weeks[usage.week_of(AFTER)]
    assert week.evidence_after_recall == 1
    assert week.gap_after_recall == 1


def test_mean_characters_is_over_recalls_with_output() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, output="abcd"),
            call("recall", moment=AFTER, output="abcdefgh"),
            call("recall", moment=AFTER, output=None),
        ]
    )
    assert report.weeks[usage.week_of(AFTER)].mean_chars() == "6"


def test_a_week_with_no_output_has_no_mean() -> None:
    report = usage.analyze([call("recall", moment=AFTER, output=None)])
    assert report.weeks[usage.week_of(AFTER)].mean_chars() == "n/a"


def test_the_listing_says_why_a_recall_has_no_shown_locators() -> None:
    report = usage.analyze(
        [call("recall", moment=AFTER, arguments=("a",), output=None, excluded="shared")]
    )
    text = usage.render_list(report)
    assert "status=excluded-shared" in text
    assert "shown: (excluded: shared)" in text


def test_the_listing_gives_each_recall_its_query_locators_and_later_calls() -> None:
    report = usage.analyze(
        [
            call("recall", moment=AFTER, arguments=("nas", "restart"), output=WITH_SESSIONS),
            call("read", moment=AFTER, arguments=("observations/archived/t1.md#3",), output="x"),
            call("evidence", moment=AFTER, arguments=("nas",), output="y"),
        ]
    )
    text = usage.render_list(report)
    assert "query: nas restart" in text
    assert "observations/archived/t1.md#3 [session]" in text
    assert "read observations/archived/t1.md#3" in text
    assert "evidence nas" in text


def test_a_recall_without_later_calls_says_none() -> None:
    report = usage.analyze([call("recall", moment=AFTER, arguments=("a",), output=CURATED_ONLY)])
    assert "later: none" in usage.render_list(report)


def test_roots_come_from_flags_or_the_host_environment(tmp_path: Path) -> None:
    roots = usage._roots(
        {"--claude-root": str(tmp_path), "--goose-root": str(tmp_path / "goose")},
        {"CODEX_HOME": str(tmp_path / "codex")},
    )
    assert roots["claude-code"] == tmp_path
    assert roots["codex"] == tmp_path / "codex" / "sessions"
    assert roots["goose"] == tmp_path / "goose"
    roots = usage._roots({}, {"GOOSE_PATH_ROOT": str(tmp_path / "root")})
    assert roots["goose"] == tmp_path / "root" / "data" / "sessions"


def test_the_default_roots_follow_the_host_home_directories(tmp_path: Path) -> None:
    roots = usage._roots({}, {"HOME": str(tmp_path), "CLAUDE_CONFIG_DIR": str(tmp_path / "cc")})
    assert roots["claude-code"] == tmp_path / "cc" / "projects"
    assert (
        roots["codex"] == Path.home() / ".codex" / "sessions"
        if not roots["codex"].is_relative_to(tmp_path)
        else True
    )
    assert roots["codex"].name == "sessions"


def test_the_main_reads_the_named_roots_and_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claude_root = tmp_path / "claude"
    (claude_root / "-work").mkdir(parents=True)
    (claude_root / "-work" / "main.jsonl").write_text("", encoding="utf-8")
    codex_root = tmp_path / "codex"
    codex_root.mkdir()
    goose_root = tmp_path / "goose"
    goose_root.mkdir()
    (goose_root / "sessions.db").write_bytes(b"not a database")
    roots = ["--claude-root", str(claude_root), "--codex-root", str(codex_root)]
    assert usage.main([*roots, "--goose-root", str(goose_root)]) == 0
    out = capsys.readouterr().out
    assert "claude-code: 1 files, 0 unreadable, 0 kb calls" in out
    assert "codex: 0 files, 0 unreadable, 0 kb calls" in out
    assert "goose: 1 files, 1 unreadable, 0 kb calls" in out
    assert "recall excluded by reason: none" in out


def test_the_main_lists_each_recall_with_the_list_switch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        usage.main(["--list", "--claude-root", str(tmp_path), "--codex-root", str(tmp_path)]) == 0
    )
    assert capsys.readouterr().out.strip() == ""


def test_the_main_names_a_flag_without_a_value(capsys: pytest.CaptureFixture[str]) -> None:
    assert usage.main(["--claude-root"]) == 1
    assert "Option --claude-root requires an argument" in capsys.readouterr().err


def test_the_main_rejects_an_unknown_flag_and_a_positional_word(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert usage.main(["--bogus"]) == 1
    assert "Unknown option: --bogus" in capsys.readouterr().err
    assert usage.main(["extra"]) == 1
    assert "Unexpected argument: extra" in capsys.readouterr().err


def test_the_main_prints_its_usage_for_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert usage.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(usage.USAGE)
    assert "--list" in out

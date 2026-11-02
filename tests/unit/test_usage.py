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
) -> KbCall:
    return KbCall(
        app="claude-code",
        session_id=session,
        timestamp=moment,
        project="/work",
        command=f"kb {subcommand} {' '.join(arguments)}",
        subcommand=subcommand,
        arguments=arguments,
        output=output,
        shared=False,
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
    ("output", "moment", "status"),
    [
        (None, AFTER, "no-output"),
        (NO_MATCH, AFTER, "no-curated-match"),
        (WITH_SESSIONS, AFTER, "session-rows"),
        (CURATED_ONLY, BEFORE, "pre-block"),
        (CURATED_ONLY, AFTER, "no-session-rows"),
    ],
)
def test_each_recall_is_tagged_by_its_block_and_time(
    output: str | None, moment: datetime, status: str
) -> None:
    recall = call("recall", moment=moment, output=output)
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
    assert rows["2026-W44"][1:5] == ["2", "1", "1", "0"]
    assert rows["2026-W44"][8] == str(round(len(WITH_SESSIONS)))


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
    assert week.reads_after_no_curated == 0


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
    assert week.reads_after_no_curated == 1


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
        ["--claude-root", str(tmp_path)],
        {"CODEX_HOME": str(tmp_path / "codex")},
    )
    assert roots["claude-code"] == tmp_path
    assert roots["codex"] == tmp_path / "codex" / "sessions"


def test_the_default_roots_follow_the_host_home_directories(tmp_path: Path) -> None:
    roots = usage._roots([], {"HOME": str(tmp_path)})
    assert roots["claude-code"].name == "projects"
    assert roots["codex"].name == "sessions"

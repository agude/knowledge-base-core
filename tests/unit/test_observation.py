"""Tests of the observation file's rules: validation, escaping, rendering, names, and messages."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb import observation
from kb.observation import InvalidArgument

WHEN = datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC)
EXPECTED = (
    "---\n"
    'title: "Say \\"hi\\" \\\\ there"\n'
    "source: session\n"
    'project: "/work/tool"\n'
    'host: "fedora"\n'
    "created: 2026-10-26T12:00:05Z\n"
    "---\n"
    "\n"
    "Plain text.\n"
)


@pytest.mark.parametrize("title", ["", "   ", "\t \t"])
def test_a_blank_title_is_refused(title: str) -> None:
    with pytest.raises(InvalidArgument):
        observation.check_title(title)


@pytest.mark.parametrize("title", ["one\ntwo", "one\rtwo", "one\r\ntwo", "\nleading"])
def test_a_title_with_a_line_break_is_refused(title: str) -> None:
    with pytest.raises(InvalidArgument):
        observation.check_title(title)


def test_a_title_with_text_is_accepted() -> None:
    observation.check_title("  Spaces around the text are kept  ")


@pytest.mark.parametrize("body", ["", " ", "\n", " \n\t "])
def test_a_blank_body_is_refused(body: str) -> None:
    with pytest.raises(InvalidArgument):
        observation.check_body(body)


def test_a_body_with_text_is_accepted() -> None:
    observation.check_body("\nText.\n")


def test_escape_doubles_backslashes_then_escapes_quotes() -> None:
    assert observation.escape('a"b\\c') == 'a\\"b\\\\c'


def test_escape_leaves_tabs_newlines_and_single_quotes_alone() -> None:
    assert observation.escape("tab\tnew\nline 'single' \\\\") == "tab\tnew\nline 'single' \\\\\\\\"


def test_host_is_cut_at_its_first_dot() -> None:
    assert observation.short_host("fedora.local") == "fedora"
    assert observation.short_host("a.b.c") == "a"
    assert observation.short_host("plain") == "plain"


def test_created_is_utc_in_the_plan_format() -> None:
    local = datetime(2026, 10, 26, 5, 0, 5, tzinfo=timezone(timedelta(hours=-7)))
    assert observation.created_text(local) == "2026-10-26T12:00:05Z"


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        observation.created_text(datetime(2026, 10, 26, 12, 0, 5))


def test_file_name_is_the_utc_time_and_the_suffix() -> None:
    assert observation.file_name(WHEN, "abcdef01") == "20261026T120005-abcdef01.md"


@pytest.mark.parametrize("suffix", ["ABCDEF01", "abc", "abcdef012", "abcdefg0", ""])
def test_a_suffix_that_is_not_eight_lowercase_hex_digits_is_refused(suffix: str) -> None:
    with pytest.raises(ValueError, match="8 lowercase hex digits"):
        observation.file_name(WHEN, suffix)
    with pytest.raises(ValueError, match="8 lowercase hex digits"):
        observation.temporary_name(suffix)


def test_temporary_name_carries_the_suffix() -> None:
    assert observation.temporary_name("abcdef01") == "observation-abcdef01.md"


def test_render_writes_section_2_exactly() -> None:
    text = observation.render('Say "hi" \\ there', "Plain text.", "/work/tool", "fedora", WHEN)
    assert text == EXPECTED


def test_render_adds_exactly_one_newline_after_a_body_that_has_one() -> None:
    text = observation.render("Title", "Line.\n", "/p", "h", WHEN)
    assert text.endswith("Line.\n\n")


def test_render_escapes_the_project_and_the_host() -> None:
    text = observation.render("T", "B", 'C:\\a "b"', 'h"ost', WHEN)
    assert 'project: "C:\\\\a \\"b\\""\n' in text
    assert 'host: "h\\"ost"\n' in text


def test_scan_text_puts_the_title_on_line_one_and_the_body_from_line_three() -> None:
    text = observation.scan_text('a"b', "first\nsecond")
    assert text == 'title: "a\\"b"\n\nfirst\nsecond\n'
    assert text.splitlines()[2] == "first"


def test_a_finding_in_the_title_is_reported_at_title() -> None:
    assert observation.location(1) == "at title"


def test_a_finding_on_scan_line_three_is_body_line_one() -> None:
    assert observation.location(3) == "at body line 1"
    assert observation.location(7) == "at body line 5"


def test_the_blank_scan_line_holds_no_agent_text() -> None:
    with pytest.raises(ValueError, match="holds no agent text"):
        observation.location(2)


def test_refusal_names_each_finding_then_gives_the_instruction() -> None:
    assert observation.refusal_lines([("Secret Keyword", 4)]) == [
        "observe: refused: possible secret (Secret Keyword) at body line 2",
        "observe: remove or redact it, then run kb observe again",
    ]


def test_refusal_keeps_the_order_of_the_findings() -> None:
    assert observation.refusal_lines([("Slack Token", 1), ("AWS Access Key", 7)]) == [
        "observe: refused: possible secret (Slack Token) at title",
        "observe: refused: possible secret (AWS Access Key) at body line 5",
        "observe: remove or redact it, then run kb observe again",
    ]

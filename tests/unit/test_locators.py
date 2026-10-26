"""Tests for locators: parsing, the outline, selection, and the header line."""

import pytest

from kb import locators
from kb.model import parse

DOC = parse(
    "x/doc.md",
    "---\ntitle: Doc Title\n---\n# Lead\n\nIntro.\n\n"
    "## Alpha\n\nAlpha text.\n\n### Sub\n\nSub text.\n\n## Beta\n\nBeta text.\n",
)
UNTITLED = parse("x/plain.md", "# Plain\n\n## One\n")


@pytest.mark.parametrize(
    ("text", "path", "fragment"),
    [
        ("knowledge/a.md", "knowledge/a.md", None),
        ("a.md#title", "a.md", "title"),
        ("a.md#top", "a.md", "top"),
        ("a.md#2", "a.md", "2"),
        ("a.md#02.01", "a.md", "2.1"),
        ("a.md#2.1.3", "a.md", "2.1.3"),
        ("a.md#", "a.md", ""),
    ],
)
def test_parse_locator_splits_at_the_first_hash(text: str, path: str, fragment: str | None) -> None:
    assert locators.parse_locator(text) == locators.Locator(path, fragment)


def test_display_title_prefers_the_title_then_the_h1_then_the_file_name() -> None:
    assert locators.display_title(DOC) == "Doc Title"
    assert locators.display_title(UNTITLED) == "Plain"
    assert locators.display_title(parse("x/bare.md", "text\n")) == "bare"


def test_outline_lists_the_title_then_each_section_with_h3_indented() -> None:
    assert locators.outline(DOC) == [
        "x/doc.md#title | Doc Title",
        "x/doc.md#1 | Alpha",
        "  x/doc.md#1.1 | Sub",
        "x/doc.md#2 | Beta",
    ]


def test_outline_without_a_title_has_no_title_line() -> None:
    assert locators.outline(UNTITLED) == ["x/plain.md#1 | One"]


def test_select_title_returns_the_title_or_nothing() -> None:
    selection = locators.select(DOC, "title")
    assert selection is not None
    assert selection.lines == ("Doc Title",)
    assert locators.select(UNTITLED, "title") is None


def test_select_top_uses_the_h1_then_the_title() -> None:
    top = locators.select(DOC, "top")
    assert top is not None
    assert top.heading == "Lead"
    assert top.lines == ("# Lead", "", "Intro.")
    no_h1 = locators.select(parse("x/t.md", "---\ntitle: T\n---\ntext\n"), "top")
    assert no_h1 is not None
    assert no_h1.heading == "T"
    empty = locators.select(parse("x/e.md", ""), "top")
    assert empty is not None
    assert empty.heading == ""
    assert empty.lines == ()


def test_select_section_returns_its_heading_lines_and_section() -> None:
    selection = locators.select(DOC, "1")
    assert selection is not None
    assert selection.heading == "Alpha"
    assert selection.section is DOC.section("1")
    assert selection.lines[-1] == "Sub text."


def test_select_missing_section_is_none() -> None:
    assert locators.select(DOC, "9") is None
    assert locators.select(DOC, "1.5") is None


def test_header_adds_status_and_a_singular_or_plural_source_count() -> None:
    assert locators.header("a.md#1", "Heading", "fresh, verified 2026-01-01", 1) == (
        "a.md#1 | Heading | fresh, verified 2026-01-01 | 1 source"
    )
    assert locators.header("a.md#1", "Heading", "unknown", 0) == (
        "a.md#1 | Heading | unknown | 0 sources"
    )


def test_header_without_status_or_sources_is_locator_and_heading() -> None:
    assert locators.header("obs.md", "Title", None, None) == "obs.md | Title"


def test_block_joins_the_header_and_lines_and_ends_with_a_newline() -> None:
    assert locators.block("head", ["one", "two"]) == "head\none\ntwo\n"
    assert locators.block("head", []) == "head\n"

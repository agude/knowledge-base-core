"""Tests for byte-preserving edits to front matter."""

import pytest

from kb.model import FrontMatterEditError, edit_front_matter, parse


def test_replacing_a_scalar_changes_only_its_line_and_reparses() -> None:
    original = (
        "---\n"
        'title: "Quoted \\"title\\""\n'
        "updated: 2026-10-19\n"
        'verified: "2026-10-01"\n'
        "aliases:\n"
        "  - first\n"
        "  - second\n"
        "---\n"
        "# Title\n"
    )

    result = edit_front_matter(original, "verified", "2026-10-20")

    assert result == original.replace('verified: "2026-10-01"', "verified: 2026-10-20")
    assert parse("test.md", result).scalar("verified") == "2026-10-20"


def test_inserting_after_a_named_field_adds_one_line() -> None:
    original = "---\ntitle: Example\nverified: 2026-10-20\n---\n# Example\n"

    result = edit_front_matter(original, "ttl", "domain", after="verified")

    assert result == "---\ntitle: Example\nverified: 2026-10-20\nttl: domain\n---\n# Example\n"
    assert parse("test.md", result).scalar("ttl") == "domain"


def test_inserting_at_the_end_goes_before_the_closing_delimiter() -> None:
    original = "---\ntitle: Example\n\n---\n# Example"

    result = edit_front_matter(original, "verified", "2026-10-20")

    assert result == "---\ntitle: Example\n\nverified: 2026-10-20\n---\n# Example"
    assert parse("test.md", result).scalar("verified") == "2026-10-20"


def test_replacement_quotes_a_scalar_without_changing_its_value() -> None:
    original = "---\ntitle: Old\nupdated: 2026-10-20\n---\n# Old\n"
    value = '  Quoted "title" with \\ slash  '

    result = edit_front_matter(original, "title", value)

    original_lines = original.splitlines(keepends=True)
    result_lines = result.splitlines(keepends=True)
    assert [
        index
        for index, lines in enumerate(zip(original_lines, result_lines, strict=True))
        if lines[0] != lines[1]
    ] == [1]
    assert parse("test.md", result).scalar("title") == value


def test_crlf_and_quoted_values_are_preserved_when_inserting() -> None:
    original = (
        '---\r\ntitle: "Quoted title"\r\nverified: 2026-10-20\r\n'
        'aliases:\r\n  - "quoted alias"\r\n---\r\n# Title\r\n'
    )

    result = edit_front_matter(original, "ttl", "people", after="verified")

    assert result == (
        '---\r\ntitle: "Quoted title"\r\nverified: 2026-10-20\r\n'
        'ttl: people\r\naliases:\r\n  - "quoted alias"\r\n---\r\n# Title\r\n'
    )
    document = parse("test.md", result)
    assert document.scalar("ttl") == "people"
    assert all("\r" not in line for line in document.lines)


@pytest.mark.parametrize(
    ("text", "name", "after", "message"),
    [
        ("# Title\n", "verified", None, "front matter is missing"),
        ("---\ntitle: Example\n", "verified", None, "front matter is unclosed"),
        (
            "---\nttl: domain\nttl: status\n---\n",
            "ttl",
            None,
            "front matter field is duplicated: ttl",
        ),
        (
            "---\nttl:\n  - domain\n---\n",
            "ttl",
            None,
            "front matter field is a block list: ttl",
        ),
        (
            "---\ntitle: Example\ntitle: Second\n---\n",
            "verified",
            "title",
            "insertion anchor is duplicated: title",
        ),
        (
            "---\ntitle: Example\n---\n",
            "verified",
            "missing",
            "insertion anchor is missing: missing",
        ),
        (
            "---\naliases:\n  - one\n---\n",
            "verified",
            "aliases",
            "insertion anchor is a block list: aliases",
        ),
    ],
)
def test_unsafe_or_ambiguous_edits_are_refused(
    text: str, name: str, after: str | None, message: str
) -> None:
    with pytest.raises(FrontMatterEditError, match=message):
        edit_front_matter(text, name, "value", after=after)


def test_a_field_name_or_value_cannot_inject_another_line() -> None:
    text = "---\ntitle: Example\n---\n"

    with pytest.raises(FrontMatterEditError, match="invalid field name"):
        edit_front_matter(text, "bad name", "value")
    with pytest.raises(FrontMatterEditError, match="must be a single line"):
        edit_front_matter(text, "verified", "2026-10-20\nextra: field")

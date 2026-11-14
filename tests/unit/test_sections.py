"""Unit tests for placing writer-supplied section text in an article."""

import pytest

from kb import model, sections

ARTICLE = """---
title: T
updated: 2026-01-01
verified: 2026-01-01
sources:
  - observations/archived/a.md
---

# T

Intro.

## One

<!-- kb-section: verified=2026-02-02; sources=observations/archived/x.md -->

Body one.

### Sub

Sub body.

## Two

Body two.
"""


def _outline(text: str) -> list[tuple[str, str]]:
    return [(item.key, item.heading) for item in model.parse("a.md", text).sections]


def test_replace_keeps_the_metadata_comment_that_the_rewrite_omits() -> None:
    edited = sections.replace(ARTICLE, "1", "## One\n\nNew body.\n\n### Sub\n\nNew sub.\n")

    assert "<!-- kb-section: verified=2026-02-02;" in edited.text
    assert "Body one." not in edited.text
    assert "New body.\n\n### Sub\n\nNew sub.\n\n## Two\n" in edited.text
    assert _outline(edited.text) == [("1", "One"), ("1.1", "Sub"), ("2", "Two")]
    document = model.parse("a.md", edited.text)
    assert document.section("1") is not None
    assert document.section("1").meta["verified"] == "2026-02-02"  # type: ignore[union-attr]


def test_replace_with_two_sections_splits_one_and_renumbers_the_rest() -> None:
    edited = sections.replace(ARTICLE, "2", "## Two\n\nFirst half.\n\n## Three\n\nSecond half.")

    assert _outline(edited.text)[-2:] == [("2", "Two"), ("3", "Three")]
    assert edited.text.endswith("## Three\n\nSecond half.\n")


def test_replace_refuses_text_of_another_level() -> None:
    with pytest.raises(sections.EditError, match="is an H2"):
        sections.replace(ARTICLE, "1", "### One\n\nText.")


def test_append_lands_before_the_sections_own_h3() -> None:
    edited = sections.append(ARTICLE, "1", "- Added bullet.")

    assert "Body one.\n\n- Added bullet.\n\n### Sub\n" in edited.text
    assert edited.written is not None


def test_append_refuses_headings() -> None:
    with pytest.raises(sections.EditError, match="must not contain"):
        sections.append(ARTICLE, "2", "## New\n\nText.")


def test_insert_after_an_h2_lands_after_its_h3s() -> None:
    edited = sections.insert(ARTICLE, "1", "after", "## Middle\n\nText.")

    assert _outline(edited.text) == [("1", "One"), ("1.1", "Sub"), ("2", "Middle"), ("3", "Two")]


def test_insert_after_top_makes_a_new_first_h2() -> None:
    edited = sections.insert(ARTICLE, "top", "after", "## Zero\n\nText.")

    assert "Intro.\n\n## Zero\n\nText.\n\n## One\n" in edited.text


def test_insert_an_h3_before_an_h3() -> None:
    edited = sections.insert(ARTICLE, "1.1", "before", "### Pre\n\nText.")

    assert _outline(edited.text)[:3] == [("1", "One"), ("1.1", "Pre"), ("1.2", "Sub")]


@pytest.mark.parametrize(
    ("anchor", "placement", "text", "message"),
    [
        ("1.1", "after", "## New\n\nText.", "relative to an H2"),
        ("1", "before", "### New\n\nText.", "an H3 goes --after an H2"),
        ("top", "before", "## New\n\nText.", "only an H2"),
        ("9", "after", "## New\n\nText.", "no section 9"),
        ("1", "after", "Prose first.\n\n## New", "must start with an H2 or H3"),
        ("1", "after", "## New\n\n# Title", "H1"),
        ("1", "after", "## New\n\n```\nopen fence", "unclosed code fence"),
        ("1", "after", "---\n## New", "front matter delimiter"),
        ("1", "after", "\n\n", "empty"),
    ],
)
def test_insert_refuses_text_or_anchors_that_cannot_be_placed(
    anchor: str, placement: sections.Placement, text: str, message: str
) -> None:
    with pytest.raises(sections.EditError, match=message):
        sections.insert(ARTICLE, anchor, placement, text)


def test_move_an_h2_to_the_front_and_back() -> None:
    moved = sections.move(ARTICLE, "2", "top", "after")
    assert _outline(moved.text) == [("1", "Two"), ("2", "One"), ("2.1", "Sub")]

    back = sections.move(moved.text, "1", "2", "after")
    assert back.text == ARTICLE


def test_move_refuses_itself_and_its_own_h3() -> None:
    with pytest.raises(sections.EditError, match="itself"):
        sections.move(ARTICLE, "1", "1", "after")
    with pytest.raises(sections.EditError, match="relative to an H2"):
        sections.move(ARTICLE, "1", "1.1", "before")


def test_remove_the_last_section_leaves_one_final_newline() -> None:
    edited = sections.remove(ARTICLE, "2")

    assert edited.text.endswith("Sub body.\n")
    assert edited.written is None


def test_unrelated_line_endings_are_preserved() -> None:
    crlf = ARTICLE.replace("\n", "\r\n")

    edited = sections.append(crlf, "2", "Added.")

    assert edited.text == crlf.replace("Body two.\r\n", "Body two.\r\n\r\nAdded.\r\n")


def test_add_front_source_prepends_once() -> None:
    once = sections.add_front_source(ARTICLE, "observations/archived/b.md")
    twice = sections.add_front_source(once, "observations/archived/b.md")

    assert "sources:\n  - observations/archived/b.md\n  - observations/archived/a.md\n" in once
    assert twice == once


def test_a_fragment_citation_of_the_same_file_counts_as_present() -> None:
    cited = ARTICLE.replace("archived/a.md", "archived/b.md#2")

    assert sections.add_front_source(cited, "observations/archived/b.md") == cited
    assert sections.add_section_source(cited, "1", "observations/archived/x.md") == cited


def test_add_front_source_creates_the_field() -> None:
    bare = ARTICLE.replace("sources:\n  - observations/archived/a.md\n", "")

    edited = sections.add_front_source(bare, "observations/archived/b.md")

    assert "verified: 2026-01-01\nsources:\n  - observations/archived/b.md\n---\n" in edited


def test_add_front_source_refuses_a_scalar_field() -> None:
    scalar = ARTICLE.replace(
        "sources:\n  - observations/archived/a.md\n", "sources: observations/archived/a.md\n"
    )

    with pytest.raises(sections.EditError, match="not a block list"):
        sections.add_front_source(scalar, "observations/archived/b.md")


def test_section_sources_are_found_through_the_parent_h2() -> None:
    document = model.parse("a.md", ARTICLE)

    owner = sections.section_source_owner(document, "1.1")
    assert owner is not None
    assert owner.key == "1"
    assert sections.section_source_owner(document, "2") is None

    edited = sections.add_section_source(ARTICLE, "1.1", "observations/archived/c.md")
    assert "sources=observations/archived/x.md, observations/archived/c.md -->" in edited
    assert sections.add_section_source(edited, "1", "observations/archived/c.md") == edited


def test_set_ttl_goes_after_verified_and_leaves_it_alone() -> None:
    edited = sections.set_ttl(ARTICLE, "180")

    assert "verified: 2026-01-01\nttl: 180\nsources:" in edited

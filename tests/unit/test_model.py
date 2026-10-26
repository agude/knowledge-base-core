"""Tests for the Markdown parser: front matter, headings, sections, and metadata."""

from pathlib import Path

import pytest

from kb import model
from kb.model import Document

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CONTENT = FIXTURES / "content"


def load(relpath: str) -> Document:
    """Parse one file of the content fixture, keeping its bytes exact."""
    return model.parse(relpath, (CONTENT / relpath).read_bytes().decode("utf-8"))


def parse(text: str) -> Document:
    return model.parse("test.md", text)


def heading_texts(document: Document) -> list[str]:
    return [section.heading for section in document.sections]


def test_every_markdown_file_in_every_fixture_corpus_parses() -> None:
    files = sorted(FIXTURES.rglob("*.md"))
    assert len(files) >= 40
    for path in files:
        relpath = str(path.relative_to(FIXTURES))
        document = model.parse(relpath, path.read_bytes().decode("utf-8"))
        assert document.path == relpath


def test_unclosed_front_matter_is_body_text() -> None:
    document = load("knowledge/rules/unclosed-front-matter.md")
    assert document.front == {}
    assert document.body_start == 0
    assert document.title is None
    assert document.lines[0] == "---"


def test_a_rule_later_in_the_file_is_not_front_matter() -> None:
    document = load("knowledge/rules/no-front-matter.md")
    assert document.front == {}
    assert document.title is None
    assert document.h1 == "Heading Title Only"
    assert "title: this line is body text, not front matter" in document.lines


def test_quoted_title_unescapes_quotes_and_backslashes() -> None:
    assert load("knowledge/rules/frontmatter-quoted.md").title == (
        'Quoted "title" with a \\ backslash'
    )


def test_single_quotes_unwrap_and_the_first_key_wins() -> None:
    assert load("knowledge/rules/frontmatter-block-lists.md").title == "Single 'quoted' title"


def test_block_lists_hold_plain_double_and_single_quoted_items() -> None:
    document = load("knowledge/rules/frontmatter-block-lists.md")
    assert document.items("aliases") == ("plain alias", "quoted alias", "single alias")
    assert document.items("sources") == (
        "observations/archived/20260412T101500-a1b2c3d4.md",
        "sources/vendor-guide.md",
    )


def test_quoted_scalars_are_read_as_their_values() -> None:
    document = load("knowledge/rules/frontmatter-block-lists.md")
    assert document.scalar("verified") == "2026-10-20"
    assert document.scalar("ttl") == "people"


def test_inline_brackets_are_a_plain_scalar_not_a_list() -> None:
    document = parse("---\naliases: [one, two]\n---\n")
    assert document.items("aliases") == ("[one, two]",)


def test_a_key_without_items_is_an_empty_string() -> None:
    document = parse("---\nsources:\n---\n")
    assert document.front == {"sources": ""}
    assert document.items("sources") == ()


def test_unparseable_lines_are_ignored_and_blank_lines_keep_a_list_open() -> None:
    document = parse("---\nnot a key\naliases:\n  - one\n\n  - two\nstray line\n  - three\n---\n")
    assert document.items("aliases") == ("one", "two")


def test_items_after_a_duplicate_key_are_ignored() -> None:
    document = parse("---\ntitle: First\ntitle:\n  - ignored\n---\n")
    assert document.title == "First"
    assert document.items("title") == ("First",)


def test_an_unterminated_quote_is_a_plain_scalar() -> None:
    assert parse('---\ntitle: "open\n---\n').title == '"open'


def test_a_single_quoted_value_keeps_its_doubled_quote_as_one() -> None:
    assert parse("---\ntitle: 'it''s'\n---\n").title == "it's"


def test_an_empty_title_is_none() -> None:
    assert parse("---\ntitle:\n---\n").title is None


def test_crlf_line_endings_are_removed() -> None:
    document = parse("---\r\ntitle: A\r\n---\r\n\r\n# A\r\n\r\n## B\r\nText\r\n")
    assert document.title == "A"
    assert all("\r" not in line for line in document.lines)
    assert heading_texts(document) == ["B"]


def test_text_without_a_final_newline_keeps_its_last_line() -> None:
    document = parse("# A\n\n## B\nlast")
    assert document.lines[-1] == "last"


def test_an_empty_file_has_no_lines() -> None:
    document = parse("")
    assert document.lines == ()
    assert document.sections == ()
    assert document.top_lines() == ()


def test_sections_are_numbered_and_h3_sections_nest_under_their_h2() -> None:
    document = load("knowledge/rules/sections-structure.md")
    assert [(s.key, s.heading, s.parent) for s in document.sections] == [
        ("1", "First section", None),
        ("1.1", "First sub", "1"),
        ("1.2", "Second sub", "1"),
        ("2", "Second section", None),
        ("3", "Third section", None),
    ]


def test_an_h3_before_the_first_h2_belongs_to_the_top() -> None:
    document = load("knowledge/rules/sections-structure.md")
    assert "### Early H3 before any H2" in document.top_lines()
    assert "Early H3 before any H2" in document.top_headings
    assert document.h1 == "Section Structure"
    assert document.section("0.1") is None


def test_code_fences_hide_headings() -> None:
    document = load("knowledge/rules/sections-structure.md")
    lines = document.section_lines(document.section("1.1"))  # type: ignore[arg-type]
    assert "## Not a heading inside a fence" in lines
    assert "### Not a sub heading inside a fence" in lines
    assert not any("Not a" in heading for heading in heading_texts(document))


def test_fourth_level_headings_are_body_text() -> None:
    document = load("knowledge/rules/sections-structure.md")
    assert "#### Deep heading" in document.section_lines(document.section("1.1"))  # type: ignore[arg-type]


def test_closing_hashes_are_dropped_and_an_empty_heading_is_body_text() -> None:
    document = load("knowledge/rules/sections-structure.md")
    section = document.section("2")
    assert section is not None
    assert section.heading == "Second section"
    assert "## ##" in document.section_lines(section)


def test_top_lines_drop_surrounding_blank_lines() -> None:
    assert load("knowledge/infra/nas.md").top_lines() == (
        "# NAS",
        "",
        "The NAS runs Traefik, Syncthing, and Plex. Its disks are in one pool.",
    )


def test_section_lines_drop_trailing_blank_lines() -> None:
    document = load("knowledge/infra/nas.md")
    section = document.section("1")
    assert section is not None
    assert document.section_lines(section) == (
        "## Restart order",
        "",
        "Traefik first, then Syncthing, then Plex.",
    )


def test_a_transcript_has_no_sections_and_its_turns_are_top_lines() -> None:
    document = load("observations/pending/20261025T180000-1f2e3d4c.md")
    assert document.sections == ()
    assert "### user" in document.top_lines()


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("## Two ##", ["Two"]),
        ("## C#", ["C#"]),
        ("##\tTab", ["Tab"]),
        ("## #tag", ["#tag"]),
        ("## ##", []),
        ("##nospace", []),
        ("####### seven", []),
        ("##", []),
    ],
)
def test_heading_forms(line: str, expected: list[str]) -> None:
    assert heading_texts(parse(line + "\n")) == expected


def test_a_tilde_fence_closes_at_a_longer_marker() -> None:
    document = parse("~~~~\n## no\n~~~~~\n## yes\n")
    assert heading_texts(document) == ["yes"]


def test_a_backtick_info_string_with_a_backtick_does_not_open_a_fence() -> None:
    assert heading_texts(parse("```a`b\n## yes\n")) == ["yes"]


def test_a_fence_may_be_indented_by_up_to_three_spaces() -> None:
    assert heading_texts(parse("   ```\n## no\n```\n## yes\n")) == ["yes"]
    assert heading_texts(parse("    ```\n## yes\n")) == ["yes"]


def test_a_fence_closes_only_at_a_bare_marker() -> None:
    document = parse("```\n## no\n```python\nstill\n```\n## yes\n")
    assert heading_texts(document) == ["yes"]


def test_h1_is_recorded_but_is_not_a_section() -> None:
    document = parse("# Title\n\n## One\n\n# Second title\n")
    assert document.h1 == "Title"
    assert heading_texts(document) == ["One"]


def test_metadata_is_read_at_each_position_in_the_corpus() -> None:
    document = load("knowledge/rules/section-metadata.md")
    expected = {
        "1": {
            "verified": "2026-08-01",
            "ttl": "process",
            "sources": (
                "observations/archived/20260412T101500-a1b2c3d4.md, "
                "observations/archived/20260903T120000-c3d4e5f6.md"
            ),
        },
        "1.1": {"ttl": "people"},
        "2": {"verified": "2026-07-01"},
        "3": {"verified": "2026-05-05", "ttl": "status"},
        "4": {},
        "5": {},
        "6": {},
        "7": {"verified": "2026-04-04", "ttl": "process"},
    }
    for key, meta in expected.items():
        section = document.section(key)
        assert section is not None
        assert dict(section.meta) == meta, key


def test_an_h3_inherits_from_its_h2_and_a_section_inherits_from_the_article() -> None:
    document = load("knowledge/rules/section-metadata.md")
    sub = document.section("1.1")
    assert document.scalar("verified", sub) == "2026-08-01"
    assert document.scalar("ttl", sub) == "people"
    assert document.items("sources", document.section("1")) == (
        "observations/archived/20260412T101500-a1b2c3d4.md",
        "observations/archived/20260903T120000-c3d4e5f6.md",
    )
    plain = document.section("4")
    assert document.scalar("verified", plain) == "2026-09-01"
    assert document.scalar("ttl", plain) == "domain"
    assert document.scalar("conflict") == "unresolved"
    assert document.items("sources", plain) == ()


def test_a_section_sources_override_the_article_with_an_empty_list() -> None:
    document = parse("---\nsources:\n  - a.md\n---\n## One\n<!-- kb-section: sources= -->\n")
    section = document.section("1")
    assert section is not None
    assert document.items("sources", section) == ()


def test_a_comment_after_a_blank_line_and_with_leading_spaces_is_valid() -> None:
    section = parse("## A\n\n   <!-- kb-section: ttl=people -->\n").section("1")
    assert section is not None
    assert dict(section.meta) == {"ttl": "people"}


def test_the_first_occurrence_of_a_metadata_key_wins() -> None:
    section = parse("## A\n<!-- kb-section: ttl=people; ttl=domain -->\n").section("1")
    assert section is not None
    assert dict(section.meta) == {"ttl": "people"}


def test_a_comment_before_the_first_h2_is_ignored() -> None:
    section = parse("# Title\n<!-- kb-section: ttl=people -->\n## A\n").section("1")
    assert section is not None
    assert dict(section.meta) == {}


def test_a_comment_after_body_text_or_a_level_four_heading_is_ignored() -> None:
    assert dict(parse("## A\n#### x\n<!-- kb-section: ttl=people -->\n").section("1").meta) == {}  # type: ignore[union-attr]
    assert dict(parse("## A\nText.\n<!-- kb-section: ttl=people -->\n").section("1").meta) == {}  # type: ignore[union-attr]


def test_an_unclosed_comment_is_ignored() -> None:
    section = parse("## A\n<!-- kb-section: verified=2026-01-01\nText\n").section("1")
    assert section is not None
    assert dict(section.meta) == {}


def test_a_comment_with_text_after_its_close_is_ignored() -> None:
    section = parse("## A\n<!-- kb-section: ttl=people --> trailing\n").section("1")
    assert section is not None
    assert dict(section.meta) == {}


def test_a_comment_after_an_h3_applies_to_the_h3_only() -> None:
    document = parse("## A\n### B\n<!-- kb-section: ttl=people -->\n")
    assert dict(document.section("1.1").meta) == {"ttl": "people"}  # type: ignore[union-attr]
    assert dict(document.section("1").meta) == {}  # type: ignore[union-attr]


def test_a_comment_inside_a_fence_is_not_metadata() -> None:
    section = parse("## A\n```\n<!-- kb-section: ttl=people -->\n```\n").section("1")
    assert section is not None
    assert dict(section.meta) == {}


def test_a_fence_right_after_a_heading_blocks_the_comment_search() -> None:
    section = parse("## A\n```\n```\n<!-- kb-section: ttl=people -->\n").section("1")
    assert section is not None
    assert dict(section.meta) == {}


def test_a_comment_after_a_heading_without_blank_lines_is_read() -> None:
    section = parse("## A\n<!-- kb-section: ttl=people;\n     verified=2026-01-01 -->\n").section(
        "1"
    )
    assert section is not None
    assert dict(section.meta) == {"ttl": "people", "verified": "2026-01-01"}


def test_unknown_keys_and_entries_without_equals_are_ignored() -> None:
    document = load("knowledge/rules/section-metadata.md")
    section = document.section("7")
    assert section is not None
    assert dict(section.meta) == {"verified": "2026-04-04", "ttl": "process"}


def test_a_section_at_the_end_of_the_file_runs_to_its_last_line() -> None:
    document = parse("## A\nfirst\n\nlast")
    section = document.section("1")
    assert section is not None
    assert section.end == len(document.lines)
    assert document.section_lines(section) == ("## A", "first", "", "last")


def test_a_section_with_no_body_has_only_its_heading() -> None:
    document = parse("## A\n## B\n")
    section = document.section("1")
    assert section is not None
    assert document.section_lines(section) == ("## A",)


def test_items_reads_a_plain_scalar_as_one_item() -> None:
    assert parse("---\nsources: one.md\n---\n").items("sources") == ("one.md",)


def test_scalar_ignores_a_list_value() -> None:
    assert parse("---\naliases:\n  - one\n---\n").scalar("aliases") is None


def test_a_missing_field_is_none_or_empty() -> None:
    document = parse("## A\n")
    assert document.scalar("verified") is None
    assert document.items("aliases") == ()
    assert document.items("sources", document.section("1")) == ()


def test_section_lookup_returns_none_for_unknown_keys() -> None:
    assert parse("## A\n").section("9") is None


def test_prose_leaves_out_headings_and_valid_metadata_comments() -> None:
    document = load("knowledge/rules/section-metadata.md")
    section = document.section("1")
    assert section is not None
    prose = [line for line in document.prose(section.start, section.end) if line]
    assert prose == [
        "Text after the valid comment.",
        "This H3 takes verified from its H2 and ttl from its own comment.",
    ]


def test_invalid_metadata_comments_stay_as_prose() -> None:
    document = load("knowledge/rules/section-metadata.md")
    section = document.section("5")
    assert section is not None
    assert document.prose(section.start, section.end) == (
        "<!-- kb-section: verified=2026-06-01 --> trailing prose",
    )


def test_heading_and_comment_line_sets_are_recorded() -> None:
    document = parse("## A\n<!-- kb-section: ttl=people;\n   verified=2026-01-01 -->\nText\n")
    assert document.heading_lines == frozenset({0})
    assert document.comment_lines == frozenset({1, 2})

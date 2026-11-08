"""One inheritance rule for metadata fields: section, then its H2, then the article."""

from dataclasses import replace

from kb import meta, model
from kb.meta import Located

ARTICLE = (
    "---\n"  # 1
    "title: Example\n"  # 2
    "verified: 2026-09-01\n"  # 3
    "ttl: domain\n"  # 4
    "---\n"  # 5
    "# Example\n"  # 6
    "## Front only\n"  # 7
    "Text.\n"  # 8
    "## Overridden\n"  # 9
    "<!-- kb-section: verified=2026-10-01 -->\n"  # 10
    "### Inherits\n"  # 11
    "Text.\n"  # 12
    "### Overrides\n"  # 13
    "<!-- kb-section: ttl=people;\n"  # 14
    "     verified=2026-10-05 -->\n"  # 15
)


def document() -> model.Document:
    return model.parse("knowledge/example.md", ARTICLE)


def section(key: str) -> model.Section:
    found = document().section(key)
    assert found is not None
    return found


def test_a_value_only_in_front_matter_comes_from_its_line() -> None:
    assert meta.resolve(document(), section("1"), "verified") == Located("2026-09-01", 3)


def test_an_h2_metadata_comment_overrides_front_matter() -> None:
    assert meta.resolve(document(), section("2"), "verified") == Located("2026-10-01", 10)


def test_an_h3_inherits_from_its_h2() -> None:
    assert meta.resolve(document(), section("2.1"), "verified") == Located("2026-10-01", 10)


def test_an_h3_overrides_its_h2() -> None:
    assert meta.resolve(document(), section("2.2"), "verified") == Located("2026-10-05", 15)
    assert meta.resolve(document(), section("2.2"), "ttl") == Located("people", 14)


def test_an_h3_without_an_override_reaches_front_matter() -> None:
    assert meta.resolve(document(), section("2.1"), "ttl") == Located("domain", 4)


def test_a_missing_field_resolves_to_none() -> None:
    assert meta.resolve(document(), section("2.2"), "effective") is None
    assert meta.resolve(document(), None, "effective") is None


def test_without_a_section_the_article_value_is_used() -> None:
    assert meta.resolve(document(), None, "verified") == Located("2026-09-01", 3)


def test_resolve_agrees_with_document_scalar() -> None:
    parsed = document()
    for current in (None, *parsed.sections):
        for name in ("verified", "ttl", "title", "effective"):
            resolved = meta.resolve(parsed, current, name)
            expected = parsed.scalar(name, current)
            assert (None if resolved is None else resolved.value) == expected


def test_a_front_value_without_a_recorded_field_is_on_line_one() -> None:
    parsed = document()
    bare = replace(parsed, front_fields=())

    assert meta.resolve(bare, None, "verified") == Located("2026-09-01", 1)

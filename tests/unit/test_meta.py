"""One inheritance rule for metadata fields: section, then its H2, then the article."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

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


def test_a_front_value_without_a_recorded_field_is_on_line_one() -> None:
    parsed = document()
    bare = replace(parsed, front_fields=())

    assert meta.resolve(bare, None, "verified") == Located("2026-09-01", 1)


TRANSCRIPT = (
    "---\n"
    'title: "Saved transcript"\n'
    "source: session-transcript\n"
    'host: "test-host"\n'
    "app: codex\n"
    'session: "s-1"\n'
    "part: 2\n"
    'first_message: "m-1"\n'
    'last_message: "m-2"\n'
    "started: 2026-10-26T09:00:00Z\n"
    "ended: 2026-10-26T04:30:00-05:00\n"
    "created: 2026-10-26T12:00:00Z\n"
    'forked_from: "parent"\n'
    "message_ids:\n"
    '  - "m-1"\n'
    '  - "m-2"\n'
    "---\n\n## 1. user, 2026-10-26T09:00:00Z\n\nHi.\n"
)


def transcript(text: str = TRANSCRIPT) -> meta.TranscriptMeta:
    return meta.TranscriptMeta.read(model.parse("observations/pending/x.md", text))


def test_a_complete_transcript_record_is_converted() -> None:
    assert transcript() == meta.TranscriptMeta(
        source="session-transcript",
        host="test-host",
        app="codex",
        session="s-1",
        part=2,
        first_message="m-1",
        last_message="m-2",
        started=datetime(2026, 10, 26, 9, tzinfo=UTC),
        ended=datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
        created=datetime(2026, 10, 26, 12, tzinfo=UTC),
        forked_from="parent",
        message_ids=("m-1", "m-2"),
    )


def test_missing_optional_fields_read_as_none() -> None:
    text = "---\nsource: session-transcript\nhost: h\n---\nBody.\n"

    assert transcript(text) == meta.TranscriptMeta(
        "session-transcript", "h", None, None, None, None, None, None, None, None, None, None
    )


@pytest.mark.parametrize(
    "field", ["started: 2026-10-26T09:00:00\n", "ended: yesterday\n", "created: \n"]
)
def test_an_invalid_timestamp_reads_as_none(field: str) -> None:
    name = field.split(":", 1)[0]

    assert getattr(transcript(f"---\nsource: session-transcript\n{field}---\n"), name) is None


@pytest.mark.parametrize(
    ("part", "expected"),
    [
        ("2", 2),
        ("0", 0),
        ("-1", None),
        ("1.5", None),
        ("٣", None),
        ("two", None),
        ("", None),
        pytest.param("9" * 5000, None, id="oversized"),
    ],
)
def test_part_reads_as_ascii_digits_only(part: str, expected: int | None) -> None:
    assert transcript(f"---\npart: {part}\n---\n").part == expected


@pytest.mark.parametrize("app", ["claude-code", "codex", "goose"])
def test_a_known_app_is_kept(app: str) -> None:
    assert transcript(f"---\napp: {app}\n---\n").app == app


def test_an_unknown_app_or_scalar_message_ids_read_as_none() -> None:
    record = transcript("---\napp: other\nmessage_ids: m-1\n---\n")

    assert (record.app, record.message_ids) == (None, None)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.mark.parametrize(
    "path",
    sorted(path for path in FIXTURES.rglob("*.md") if path.is_file()),
    ids=lambda path: str(path.relative_to(FIXTURES)),
)
def test_parse_front_matter_matches_parse(path: Path) -> None:
    text = path.read_bytes().decode("utf-8", errors="replace")

    full = model.parse(path.name, text)
    front = model.parse_front_matter(path.name, text)

    assert front.front == full.front
    assert front.front_fields == full.front_fields
    assert front.front_matter_span == full.front_matter_span
    assert (front.front_matter_opened, front.front_matter_closed) == (
        full.front_matter_opened,
        full.front_matter_closed,
    )
    assert front.sections == ()


def article(front: str, body: str = "# Example\n") -> model.Document:
    return model.parse("knowledge/example.md", f"---\n{front}---\n{body}")


# After two front matter fields, the body starts on line 5.
INHERITING = (
    "# Example\n"  # 5
    "## Parent\n"  # 6
    "<!-- kb-section: verified=2026-10-01; ttl=people -->\n"  # 7
    "### Child\n"  # 8
    "Text.\n"  # 9
)


def test_article_fields_are_converted() -> None:
    document = article(
        "title: Example\n"  # 2
        "updated: 2026-10-02\n"  # 3
        "verified: 2026-09-01\n"  # 4
        "ttl: 30\n"  # 5
        "conflict: unresolved\n"  # 6
        "sources:\n"
        "  - sources/a.md\n"
        "aliases:\n"
        "  - nickname\n"
    )

    assert meta.ArticleMeta.read(document) == meta.ArticleMeta(
        title="Example",
        updated=date(2026, 10, 2),
        verified=Located(date(2026, 9, 1), 4),
        ttl=Located(30, 5),
        conflict="unresolved",
        synced=None,
        sources=("sources/a.md",),
        aliases=("nickname",),
    )


def test_invalid_article_fields_keep_their_text_and_line() -> None:
    document = article("updated: 2026-13-01\nverified: soon\nttl: weekly\n")

    read = meta.ArticleMeta.read(document)

    assert read.updated == meta.Invalid("2026-13-01", 2)
    assert read.verified == meta.Invalid("soon", 3)
    assert read.ttl == meta.Invalid("weekly", 4)


def test_a_ttl_beyond_the_limit_is_invalid_and_zero_converts() -> None:
    assert meta.ArticleMeta.read(article("ttl: 1000001\n")).ttl == meta.Invalid("1000001", 2)
    assert meta.ArticleMeta.read(article("ttl: 0\n")).ttl == Located(0, 2)


def test_missing_article_fields_read_as_none_or_empty() -> None:
    read = meta.ArticleMeta.read(article("title: Example\n"))

    assert (read.updated, read.verified, read.ttl, read.conflict, read.synced) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert (read.sources, read.aliases) == ((), ())


def test_a_front_matter_list_is_not_a_scalar_field() -> None:
    read = meta.ArticleMeta.read(article("verified:\n  - 2026-09-01\nttl:\n  - 30\n"))

    assert (read.verified, read.ttl) == (None, None)


def test_verified_and_ttl_are_inherited_from_a_section() -> None:
    document = article("verified: 2026-09-01\nttl: domain\n", INHERITING)
    child = document.section("1.1")
    assert child is not None

    read = meta.ArticleMeta.read(document, child)

    assert read.verified == Located(date(2026, 10, 1), 7)
    assert read.ttl == Located(14, 7)


def test_an_invalid_inherited_value_keeps_the_section_line() -> None:
    document = article(
        "verified: 2026-09-01\n",
        "# Example\n## Parent\n<!-- kb-section: verified=bad; ttl=0x10 -->\n### Child\n",
    )
    child = document.section("1.1")
    assert child is not None

    read = meta.ArticleMeta.read(document, child)

    assert read.verified == meta.Invalid("bad", 6)
    assert read.ttl == meta.Invalid("0x10", 6)


def test_synced_is_read_for_a_section_and_updated_only_for_the_article() -> None:
    document = model.parse(
        "sources/copy.md",
        "---\nsynced: 2026-08-01\nupdated: 2026-08-02\n---\n# Copy\n"
        "## Part\n<!-- kb-section: synced=bad; updated=2026-01-01 -->\n",
    )
    section = document.section("1")
    assert section is not None

    read = meta.ArticleMeta.read(document, section)

    assert read.synced == meta.Invalid("bad", 7)
    assert read.updated == date(2026, 8, 2)
    assert meta.ArticleMeta.read(document).synced == date(2026, 8, 1)

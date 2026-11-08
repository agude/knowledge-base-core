"""One inheritance rule for metadata fields: section, then its H2, then the article."""

from dataclasses import replace
from datetime import UTC, datetime
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
    [("2", 2), ("0", 0), ("-1", None), ("1.5", None), ("٣", None), ("two", None), ("", None)],
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

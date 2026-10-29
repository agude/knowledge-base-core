"""Byte-preserving rendering of curation archive provenance."""

import pytest

from kb import archive, curation
from kb.model import FrontMatterEditError, parse

RUN = "20261028T120000-a1b2c3d4"
HASH = "a" * 64


def test_incorporated_archive_records_legacy_fields_then_batch_and_heading() -> None:
    original = (
        '---\ntitle: "Résumé"\ncreated: 2026-10-28T11:00:00Z\n---\n'
        "\n# Résumé\n\nFirst transcript turn.\n\n## Later\n\nSecond turn.\n"
    )
    destinations = (
        curation.Destination("knowledge/network.md#2", "VPN access"),
        curation.Destination("knowledge/people.md", None),
    )

    rendered = archive.render(original, "incorporated", HASH, RUN, destinations)

    assert rendered == (
        '---\ntitle: "Résumé"\ncreated: 2026-10-28T11:00:00Z\n'
        "disposition: incorporated\n"
        'destination: "knowledge/network.md#2"\n'
        f"original_sha256: {HASH}\n"
        f"curation_batch: {RUN}\n"
        'destination_heading: "VPN access"\n'
        "---\n\n# Résumé\n\nFirst transcript turn.\n\n## Later\n\nSecond turn.\n"
    )
    front = parse("observations/archived/item.md", rendered).front
    assert front["destination"] == "knowledge/network.md#2"
    assert front["destination_heading"] == "VPN access"
    assert rendered.endswith(original[original.index("\n---\n") + 5 :])


def test_duplicate_archive_keeps_whole_article_destination_without_heading() -> None:
    original = "---\ntitle: Duplicate\n---\n\nDuplicate evidence.\n"

    rendered = archive.render(
        original,
        "duplicate",
        HASH,
        RUN,
        [curation.Destination("knowledge/network.md", None)],
    )

    assert 'disposition: duplicate\ndestination: "knowledge/network.md"\n' in rendered
    assert "destination_heading:" not in rendered
    assert "curation_batch: " + RUN in rendered


def test_ephemeral_archive_records_its_reason_after_legacy_fields() -> None:
    original = "---\ntitle: Ephemeral\n---\n\nTemporary detail.\n"

    rendered = archive.render(original, "ephemeral", HASH, RUN, reason="Not durable")

    assert rendered == (
        "---\ntitle: Ephemeral\n"
        "disposition: ephemeral\n"
        f"original_sha256: {HASH}\n"
        f"curation_batch: {RUN}\n"
        'curation_reason: "Not durable"\n'
        "---\n\nTemporary detail.\n"
    )


def test_renderer_preserves_bom_crlf_unicode_and_transcript_body_bytes() -> None:
    original = (
        '\ufeff---\r\ntitle: "会話"\r\nsource: session-transcript\r\n'
        "created: 2026-10-28T11:00:00Z\r\n---\r\n\r\n"
        "## 1. user, 2026-10-28T11:00:00Z\r\n\r\nFirst turn: café.\r\n\r\n"
        "## 2. assistant, 2026-10-28T11:01:00Z\r\n\r\nSecond turn: 東京.\r\n"
    )
    body = original[original.index("\r\n---\r\n") + len("\r\n---\r\n") :]

    rendered = archive.render(original, "ephemeral", HASH, RUN, reason="Session-only notes")

    assert rendered.startswith("\ufeff---\r\n")
    assert "\r\ndisposition: ephemeral\r\n" in rendered
    assert rendered.endswith(body)


@pytest.mark.parametrize(
    "original",
    [
        "# Missing front matter\n",
        "---\ntitle: Unclosed\n",
        "---\ntitle: Existing\ndisposition: processed\n---\nBody.\n",
        "---\ntitle: Existing\noriginal_sha256:\n  - bad\n---\nBody.\n",
        "---\ntitle: Existing\ndestination: one\ndestination: two\n---\nBody.\n",
    ],
)
def test_renderer_refuses_missing_unclosed_and_unsafe_existing_front_matter(
    original: str,
) -> None:
    with pytest.raises(FrontMatterEditError):
        archive.render(original, "ephemeral", HASH, RUN, reason="Temporary")


@pytest.mark.parametrize(
    ("disposition", "destinations", "reason"),
    [
        ("incorporated", (), None),
        ("duplicate", (), None),
        ("ephemeral", (curation.Destination("knowledge/network.md", None),), "reason"),
        ("ephemeral", (), None),
        ("ephemeral", (), "two\nlines"),
    ],
)
def test_renderer_refuses_invalid_outcome_shapes(
    disposition: archive.Disposition,
    destinations: tuple[curation.Destination, ...],
    reason: str | None,
) -> None:
    with pytest.raises(curation.StateError):
        archive.render(
            disposition=disposition,
            destinations=destinations,
            reason=reason,
            original="---\ntitle: A\n---\n",
            original_sha256=HASH,
            batch_id=RUN,
        )


def test_renderer_refuses_invalid_original_hash_and_batch_identifier() -> None:
    original = "---\ntitle: A\n---\n"
    with pytest.raises(curation.StateError, match="original_sha256"):
        archive.render(original, "ephemeral", "bad", RUN, reason="Temporary")
    with pytest.raises(curation.StateError, match="unsafe batch id"):
        archive.render(original, "ephemeral", HASH, "../unsafe", reason="Temporary")

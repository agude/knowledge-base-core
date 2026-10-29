"""Tests for question front matter and field-aware secret refusal."""

from datetime import UTC, datetime

import pytest

from kb import question

WHEN = datetime(2026, 10, 26, 12, 0, 5, tzinfo=UTC)


def test_render_writes_fields_in_contract_order_and_escapes_quoted_values() -> None:
    text = question.render(
        'Say "hi" \\ café',
        'knowledge/infra/owner"s.md',
        "The owner is unknown.",
        "/work/one\\two",
        'fedora"local',
        WHEN,
    )
    assert text == (
        "---\n"
        'title: "Say \\"hi\\" \\\\ café"\n'
        'context: "knowledge/infra/owner\\"s.md"\n'
        "source: session\n"
        'project: "/work/one\\\\two"\n'
        'host: "fedora\\"local"\n'
        "created: 2026-10-26T12:00:05Z\n"
        "---\n"
        "\n"
        "The owner is unknown.\n"
    )


def test_scan_text_maps_findings_to_title_context_and_body_lines() -> None:
    assert question.scan_text("Title", "knowledge/infra", "First.\nSecond.") == (
        "title: Title\ncontext: knowledge/infra\n\nFirst.\nSecond.\n"
    )
    assert question.location(1) == "at title"
    assert question.location(2) == "at context"
    assert question.location(4) == "at body line 1"
    assert question.location(5) == "at body line 2"
    assert question.refusal_lines([("Secret Keyword", 1), ("Private Key", 4)]) == [
        "gap: refused: possible secret (Secret Keyword) at title",
        "gap: refused: possible secret (Private Key) at body line 1",
        "gap: remove or redact it, then run kb gap again",
    ]


def test_the_blank_separator_is_not_a_supplied_field() -> None:
    with pytest.raises(ValueError, match="holds no agent text"):
        question.location(3)

"""Pure rendering for resolved questions."""

from datetime import date
from typing import Literal

import pytest

from kb import question
from kb.model import FrontMatterEditError

TODAY = date(2026, 10, 26)


@pytest.mark.parametrize(
    ("original", "resolution", "answer", "destination", "expected"),
    [
        (
            '---\ntitle: "Quoted \\"question\\""\ncreated: 2026-10-01\n---\n\nQuestion.\n',
            "answered",
            "Answer.",
            "knowledge/infra/nas.md#1",
            '---\ntitle: "Quoted \\"question\\""\ncreated: 2026-10-01\n'
            "resolved: 2026-10-26\nresolution: answered\n"
            'destination: "knowledge/infra/nas.md#1"\n---\n\nQuestion.\n'
            "\n## Resolution (2026-10-26)\n\nAnswer.\n",
        ),
        (
            "---\ntitle: Old\ncreated: 2026-10-01\n---\n\nQuestion.\n",
            "obsolete",
            "Retired.",
            None,
            "---\ntitle: Old\ncreated: 2026-10-01\n"
            "resolved: 2026-10-26\nresolution: obsolete\n---\n\nQuestion.\n"
            "\n## Resolution (2026-10-26)\n\nRetired.\n",
        ),
    ],
)
def test_render_resolution_preserves_original_and_appends_fields_and_answer(
    original: str,
    resolution: Literal["answered", "obsolete"],
    answer: str,
    destination: str | None,
    expected: str,
) -> None:
    assert question.render_resolution(original, resolution, answer, destination, TODAY) == expected


def test_render_resolution_uses_existing_line_endings_and_preserves_a_bom() -> None:
    original = "\ufeff---\r\ntitle: Old\r\n---\r\n\r\nQuestion.\r\n"

    result = question.render_resolution(original, "obsolete", "Retired.", None, TODAY)

    assert result == (
        "\ufeff---\r\ntitle: Old\r\nresolved: 2026-10-26\r\n"
        "resolution: obsolete\r\n---\r\n\r\nQuestion.\r\n"
        "\r\n## Resolution (2026-10-26)\r\n\r\nRetired.\r\n"
    )


def test_render_resolution_refuses_existing_resolution_fields() -> None:
    with pytest.raises(FrontMatterEditError, match="resolution fields already exist"):
        question.render_resolution(
            "---\ntitle: Old\nresolution: obsolete\n---\n",
            "obsolete",
            "Retired.",
            None,
            TODAY,
        )

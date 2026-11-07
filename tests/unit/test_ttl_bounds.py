"""Bound numeric TTLs before readers convert them to integers."""

from datetime import date
from pathlib import Path

import pytest

from kb import freshness, lint, model
from kb.commands import read, recall
from kb.context import Context


@pytest.mark.parametrize(
    ("value", "valid", "expected"),
    [
        pytest.param("0" * 5000 + "1", True, "stale, verified 2026-10-24 (ttl 1)", id="padded-one"),
        pytest.param("9" * 5000, False, "invalid", id="oversized"),
        pytest.param("0" * 5000, False, "stale, verified 2026-10-24 (ttl 0)", id="zero"),
    ],
)
def test_long_numeric_ttl_in_freshness_and_readers(
    tmp_path: Path, value: str, valid: bool, expected: str
) -> None:
    text = (
        f"---\nverified: 2026-10-24\nttl: {value}\n---\n"
        "# Telescope\n\n## Lens\n\nAmethyst telescope.\n"
    )
    document = model.parse("knowledge/test.md", text)
    assert lint.valid_ttl(value) is valid
    assert freshness.status(document, None, date(2026, 10, 26)) == expected
    path = tmp_path / document.path
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    context = Context(root=tmp_path, today=date(2026, 10, 26))
    assert f" | {expected} | " in read.render(context, f"{document.path}#1", False)
    assert f" | {expected} | " in recall.answer(context, ["amethyst", "telescope"], 3, None)

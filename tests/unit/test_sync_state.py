"""Format, validation, and atomic replacement of the sync outcome record."""

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kb import sync_state
from kb.errors import KbError

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)
TEXT = (
    '{"schema_version": 1, "kb_version": "0.1.0", "last_run": "2026-10-26T12:00:00Z", '
    '"last_outcome": "ok", "last_exchange": "2026-10-26T12:00:00Z", "message": null}\n'
)
VALID = {
    "schema_version": 1,
    "kb_version": "0.1.0",
    "last_run": "2026-10-26T12:00:00Z",
    "last_outcome": "ok",
    "last_exchange": "2026-10-26T12:00:00Z",
    "message": None,
}


def make_state(
    *,
    outcome: str = "ok",
    last_exchange: datetime | None = NOW,
    message: str | None = None,
) -> sync_state.SyncState:
    return sync_state.SyncState("0.1.0", NOW, outcome, last_exchange, message)


def test_render_writes_the_documented_layout_in_utc() -> None:
    assert sync_state.render(make_state()) == TEXT

    zoned = datetime(2026, 10, 26, 14, tzinfo=timezone(timedelta(hours=2)))
    assert json.loads(sync_state.render(make_state(last_exchange=zoned)))["last_exchange"] == (
        "2026-10-26T12:00:00Z"
    )


@pytest.mark.parametrize(
    ("outcome", "exchange", "message"),
    [("ok", NOW, None), ("dirty", None, None), ("error", NOW, "sync: fetch origin failed")],
)
def test_render_and_parse_round_trip_each_outcome(
    outcome: str, exchange: datetime | None, message: str | None
) -> None:
    original = make_state(outcome=outcome, last_exchange=exchange, message=message)

    assert sync_state.parse(sync_state.render(original)) == original


def test_read_returns_none_when_no_record_exists(tmp_path: Path) -> None:
    assert sync_state.read(tmp_path) is None


def test_write_replaces_the_record_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    sync_state.write(tmp_path, make_state(outcome="dirty", last_exchange=None))

    sync_state.write(tmp_path, make_state())

    assert sync_state.read(tmp_path) == make_state()
    assert sync_state.path(tmp_path).read_text(encoding="utf-8") == TEXT
    assert list((tmp_path / "kb-tmp").iterdir()) == []


def test_a_failed_replacement_keeps_the_previous_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_state.write(tmp_path, make_state())

    def refuse(*args: object, **kwargs: object) -> Path:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(OSError, match="No space left"):
        sync_state.write(tmp_path, make_state(outcome="error", message="sync: x"))

    monkeypatch.undo()
    assert sync_state.read(tmp_path) == make_state()
    assert list((tmp_path / "kb-tmp").iterdir()) == []


def test_read_reports_a_record_that_cannot_be_read(tmp_path: Path) -> None:
    sync_state.path(tmp_path).mkdir(parents=True)

    with pytest.raises(KbError, match="cannot read"):
        sync_state.read(tmp_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("kb_version", ""),
        ("kb_version", 1),
        ("last_outcome", "maybe"),
        ("message", 3),
        ("last_run", "2026-10-26 12:00:00"),
        ("last_run", None),
        ("last_exchange", "yesterday"),
    ],
)
def test_parse_rejects_each_invalid_field(field: str, value: object) -> None:
    text = json.dumps({**VALID, field: value})

    with pytest.raises(KbError, match="sync state"):
        sync_state.parse(text)


@pytest.mark.parametrize(
    "text",
    ["not json", "[]"],
)
def test_parse_rejects_text_that_is_not_a_record(text: str) -> None:
    with pytest.raises(KbError, match="sync state"):
        sync_state.parse(text)

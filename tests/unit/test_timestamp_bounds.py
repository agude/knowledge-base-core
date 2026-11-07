"""Reject timestamps whose UTC normalization exceeds datetime bounds."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb import addressing, config, curation, dates, model, transcripts
from kb.commands import sync
from kb.errors import KbError

BOUNDS = ["0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00"]


@pytest.mark.parametrize("value", BOUNDS, ids=["lower", "upper"])
def test_transcript_timestamp_bounds(value: str) -> None:
    assert transcripts.parse_timestamp(value) is None


@pytest.mark.parametrize("value", BOUNDS, ids=["lower", "upper"])
def test_addressable_timestamp_bounds(value: str) -> None:
    text = (
        "---\nsource: session-transcript\nsession: demo\npart: 1\n"
        f"first_message: a\nlast_message: a\nstarted: {value}\nended: {value}\n---\n"
        f"## 1. user, {value}\n\nText.\n"
    )
    assert addressing.message_sections(model.parse("observations/pending/demo.md", text)) is None


@pytest.mark.parametrize("value", BOUNDS, ids=["lower", "upper"])
def test_fixed_clock_bounds(value: str) -> None:
    with pytest.raises(KbError, match=r"KB_NOW.*UTC"):
        dates.now({"KB_NOW": value})


@pytest.mark.parametrize("value", BOUNDS, ids=["lower", "upper"])
def test_config_cutoff_bounds(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    with pytest.raises(KbError, match=r"invalid config file.*harvest_since.*UTC"):
        config.parse_harvest_since(f"harvest_since = {value}\n", path)
    with pytest.raises(KbError, match=r"invalid config file.*harvest_since.*UTC"):
        config.set_harvest_since(
            f"harvest_since = {value}\n", datetime(2026, 10, 26, tzinfo=UTC), path
        )
    with pytest.raises(KbError, match=r"harvest_since.*UTC"):
        config.set_harvest_since("", datetime.fromisoformat(value), path)


@pytest.mark.parametrize("value", BOUNDS, ids=["lower", "upper"])
def test_batch_timestamp_bounds(value: str) -> None:
    moment = datetime.fromisoformat(value)
    with pytest.raises(curation.StateError, match=r"batch timestamp.*UTC"):
        curation.make_run_id(moment, "0123abcd")
    with pytest.raises(curation.StateError, match=r"batch created timestamp.*UTC"):
        curation.make_batch("20261028T120000-0123abcd", moment, 0, [])


def test_bad_timestamp_sessions_do_not_abort_scan(tmp_path: Path) -> None:
    project = tmp_path / "claude" / "projects" / "demo"
    project.mkdir(parents=True)
    for index, value in enumerate([*BOUNDS, "2026-10-26T12:00:00Z"]):
        record = {
            "type": "user",
            "uuid": str(index),
            "timestamp": value,
            "message": {"role": "user", "content": "Healthy request."},
        }
        (project / f"session-{index}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    result = sync._scan_transcripts(
        {
            "CLAUDE_CONFIG_DIR": str(tmp_path / "claude"),
            "CODEX_HOME": str(tmp_path / "codex"),
            "GOOSE_PATH_ROOT": str(tmp_path / "goose"),
        }
    )
    sessions = {candidate.session.id: candidate.session for candidate in result.candidates}
    assert not result.failures
    assert set(sessions) == {"session-0", "session-1", "session-2"}
    for name in ("session-0", "session-1"):
        assert sessions[name].messages == ()
        assert sessions[name].malformed_lines == 1
    assert [message.text for message in sessions["session-2"].messages] == ["Healthy request."]

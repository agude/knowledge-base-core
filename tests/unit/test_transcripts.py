"""Tests for the host-neutral transcript model and its stable helpers."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from kb.transcripts import (
    KbCall,
    Message,
    Scan,
    complete_lines,
    earlier,
    later,
    parse_timestamp,
    read_store,
    synthetic_id,
    text_of,
    timestamp_text,
    unique_messages,
)


def test_complete_lines_accepts_an_empty_snapshot() -> None:
    assert complete_lines("") == ((), True)


@pytest.mark.parametrize("text", ["one\n", "one\r\n"])
def test_complete_lines_keeps_only_terminated_records(text: str) -> None:
    assert complete_lines(text) == (("one",), True)


def test_complete_lines_excludes_an_incomplete_tail() -> None:
    assert complete_lines("one\ntwo") == (("one",), False)
    assert complete_lines("one") == ((), False)


@pytest.mark.parametrize("value", [None, 4, "not a timestamp", "2026-10-26T12:00:00"])
def test_parse_timestamp_rejects_non_iso_or_timezone_free_values(value: object) -> None:
    assert parse_timestamp(value) is None


def test_timestamp_text_preserves_fractional_seconds_and_uses_utc() -> None:
    local = datetime(2026, 10, 26, 5, 0, 5, 123000, tzinfo=timezone(timedelta(hours=-7)))
    assert timestamp_text(local) == "2026-10-26T12:00:05.123000Z"


def test_timestamp_text_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        timestamp_text(datetime(2026, 10, 26, 12))


def test_synthetic_id_uses_sha256_and_the_first_sixteen_hex_digits() -> None:
    import hashlib

    source = "\0".join(("claude-code", "2026-10-26T12:00:00Z", "user", "Fixture text."))
    assert (
        synthetic_id("claude-code", "2026-10-26T12:00:00Z", "user", "Fixture text.")
        == (hashlib.sha256(source.encode("utf-8")).hexdigest()[:16])
    )


def test_unique_messages_keeps_first_id_occurrence_and_counts_later_copies() -> None:
    first = Message("same", datetime(2026, 10, 26, tzinfo=UTC), "user", "First.")
    later = Message("same", datetime(2026, 10, 27, tzinfo=UTC), "assistant", "Later.")
    kept, duplicates = unique_messages((first, later))
    assert kept == (first,)
    assert duplicates == 1


def test_unique_messages_accepts_no_messages() -> None:
    assert unique_messages(()) == ((), 0)


def test_text_of_reads_a_string_or_a_list_of_text_blocks() -> None:
    assert text_of("plain") == "plain"
    assert text_of([{"type": "text", "text": "a"}, {"type": "input_text", "text": "b"}]) == "a\nb"


@pytest.mark.parametrize("value", [None, 3, [], ["bare"], [{"type": "image"}], [{"text": 1}]])
def test_text_of_has_no_text_for_other_shapes(value: object) -> None:
    assert text_of(value) is None


def test_earlier_and_later_keep_the_known_timestamp_when_one_is_missing() -> None:
    moment = datetime(2026, 10, 1, tzinfo=UTC)
    later_moment = moment + timedelta(hours=1)
    assert earlier(None, moment) == moment
    assert earlier(moment, None) == moment
    assert earlier(later_moment, moment) == moment
    assert later(None, moment) == moment
    assert later(moment, None) == moment
    assert later(moment, later_moment) == later_moment


def _call(output: str | None, excluded: str | None) -> KbCall:
    return KbCall(
        app="claude-code",
        session_id="s",
        timestamp=None,
        project="",
        command="kb recall a",
        subcommand="recall",
        arguments=("a",),
        output=output,
        excluded=excluded,
    )


def test_a_kb_call_has_output_or_an_exclusion_and_not_both() -> None:
    assert _call("text", None).output == "text"
    assert _call(None, "missing").excluded == "missing"
    with pytest.raises(ValueError, match="output or an exclusion"):
        _call("text", "missing")
    with pytest.raises(ValueError, match="output or an exclusion"):
        _call(None, None)
    with pytest.raises(ValueError, match="unknown exclusion"):
        _call(None, "lost")


def test_read_store_scans_each_path_and_counts_the_unreadable_ones(tmp_path: Path) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text("line\n", encoding="utf-8")
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe")
    seen: list[str] = []

    def scan(text: str, path: Path) -> Scan:
        seen.append(path.name)
        return Scan((), None, None)

    store = read_store([good, bad], scan)
    assert seen == ["good.jsonl"]
    assert (store.files, store.unreadable, store.calls) == (2, 1, ())


def test_command_identity_distinguishes_command_boundaries_and_order() -> None:
    from kb.transcripts import synthetic_command_id

    values = (("a", "b"), ("a\x00b",), ("b", "a"), ("a", "b", ""))
    identities = [
        synthetic_command_id("codex", "2026-10-25T08:00:00Z", "assistant", "", commands)
        for commands in values
    ]
    assert len(set(identities)) == len(values)

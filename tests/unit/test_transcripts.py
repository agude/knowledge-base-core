"""Tests for the host-neutral transcript model and its stable helpers."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kb.transcripts import (
    Message,
    complete_lines,
    parse_timestamp,
    synthetic_id,
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


def test_parse_timestamp_normalizes_utc_and_other_offsets() -> None:
    assert parse_timestamp("2026-10-26T12:00:00Z") == datetime(2026, 10, 26, 12, tzinfo=UTC)
    assert parse_timestamp("2026-10-26T05:00:00-07:00") == datetime(2026, 10, 26, 12, tzinfo=UTC)


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

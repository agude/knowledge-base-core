"""Tests for today's date and the KB_TODAY override."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from kb import dates
from kb.errors import KbError


def test_kb_today_fixes_the_date() -> None:
    assert dates.today({"KB_TODAY": "2026-10-26"}) == date(2026, 10, 26)


def test_without_kb_today_the_local_date_is_used() -> None:
    assert dates.today({}) == date.today()


def test_an_empty_kb_today_is_unset() -> None:
    assert dates.today({"KB_TODAY": ""}) == date.today()


def test_a_malformed_kb_today_is_reported() -> None:
    with pytest.raises(KbError, match=r"^knowledge base: KB_TODAY must be YYYY-MM-DD, not nope$"):
        dates.today({"KB_TODAY": "nope"})


@pytest.mark.parametrize("text", ["2026-02-28", "1999-12-31"])
def test_parse_date_accepts_iso_dates(text: str) -> None:
    assert dates.parse_date(text) == date.fromisoformat(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "2026-2-8",
        "20261026",
        "2026-13-01",
        "2026-02-30",
        "2026-10-26T00:00:00Z",
        " 2026-10-26",
        "\uff12\uff10\uff12\uff16-10-26",
    ],
)
def test_parse_date_rejects_other_forms(text: str) -> None:
    assert dates.parse_date(text) is None


def test_kb_now_fixes_time_and_normalizes_to_utc() -> None:
    assert dates.now({"KB_NOW": "2026-10-26T05:00:00-07:00"}) == datetime(
        2026, 10, 26, 12, tzinfo=UTC
    )


def test_without_kb_now_uses_the_current_utc_time() -> None:
    current = dates.now({})
    assert current.tzinfo is UTC


@pytest.mark.parametrize("value", ["nope", "2026-10-26T12:00:00"])
def test_malformed_kb_now_is_reported(value: str) -> None:
    with pytest.raises(
        KbError, match=r"^knowledge base: KB_NOW must be a time-zone-aware ISO timestamp"
    ):
        dates.now({"KB_NOW": value})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11-07T10:00:00Z", datetime(2026, 11, 7, 10, tzinfo=UTC)),
        (
            "2026-11-07T10:00:00+05:30",
            datetime(2026, 11, 7, 10, tzinfo=timezone(timedelta(hours=5, minutes=30))),
        ),
        ("2026-11-07T10:00:00.250Z", datetime(2026, 11, 7, 10, 0, 0, 250000, tzinfo=UTC)),
    ],
)
def test_parse_aware_keeps_the_written_offset(text: str, expected: datetime) -> None:
    parsed = dates.parse_aware(text)

    assert parsed == expected
    assert parsed is not None and parsed.utcoffset() == expected.utcoffset()


@pytest.mark.parametrize("text", ["2026-11-07T10:00:00", "not a time", ""])
def test_parse_aware_refuses_naive_and_malformed_text(text: str) -> None:
    assert dates.parse_aware(text) is None


def test_to_utc_converts_an_offset_value() -> None:
    value = datetime(2026, 11, 7, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    converted = dates.to_utc(value)

    assert converted == datetime(2026, 11, 7, 10, tzinfo=UTC)
    assert converted is not None and converted.tzinfo is UTC


@pytest.mark.parametrize(
    "value",
    [
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(timedelta(hours=-1))),
    ],
)
def test_to_utc_refuses_an_instant_outside_the_representable_years(value: datetime) -> None:
    assert dates.to_utc(value) is None


def test_parse_utc_normalizes_to_the_utc_instant() -> None:
    parsed = dates.parse_utc("2026-11-07T15:30:00+05:30")

    assert parsed == datetime(2026, 11, 7, 10, tzinfo=UTC)
    assert parsed is not None and parsed.tzinfo is UTC

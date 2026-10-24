"""Dates in front matter, and the clock that freshness is measured against."""

from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime

DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def today_epoch() -> int:
    """FRESHNESS_TODAY_EPOCH when set (tests pin the clock), else now."""
    configured = os.environ.get("FRESHNESS_TODAY_EPOCH")
    return int(configured) if configured else int(time.time())


def date_epoch(value: str) -> int | None:
    """Midnight UTC of a YYYY-MM-DD date, or None if it is not a real date."""
    if not DATE.fullmatch(value):
        return None
    try:
        return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    except ValueError:
        return None


def timestamp_epoch(value: str) -> int | None:
    """A date or an ISO 8601 timestamp (Z, an offset, or none for UTC) as epoch seconds."""
    if DATE.fullmatch(value):
        return date_epoch(value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())

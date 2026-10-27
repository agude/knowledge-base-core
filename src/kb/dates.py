"""Today's date. KB_TODAY fixes it, so tests and reproducible runs get the same answers."""

import re
from collections.abc import Mapping
from datetime import UTC, date, datetime

from kb.errors import KbError

ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_date(text: str) -> date | None:
    """The date written as YYYY-MM-DD, or None for any other text."""
    if not ISO_DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def today(environ: Mapping[str, str]) -> date:
    """KB_TODAY when it is set, else the local date.

    Raises KbError when KB_TODAY is set but is not a YYYY-MM-DD date.
    """
    fixed = environ.get("KB_TODAY", "")
    if not fixed:
        return date.today()
    parsed = parse_date(fixed)
    if parsed is None:
        raise KbError(f"knowledge base: KB_TODAY must be YYYY-MM-DD, not {fixed}")
    return parsed


def now(environ: Mapping[str, str]) -> datetime:
    """KB_NOW as a timezone-aware ISO timestamp, else the current UTC time."""
    fixed = environ.get("KB_NOW", "")
    if not fixed:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(fixed.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise KbError(
            f"knowledge base: KB_NOW must be a time-zone-aware ISO timestamp, not {fixed}"
        )
    return parsed.astimezone(UTC)

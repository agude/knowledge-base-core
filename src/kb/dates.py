"""Today's date. KB_TODAY fixes it, so tests and reproducible runs get the same answers."""

import re
from collections.abc import Mapping
from datetime import date

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

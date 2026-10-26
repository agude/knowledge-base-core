"""Freshness: whether an article or a section is current, from its date and its ttl.

Knowledge articles and their sections are judged by `verified`. Files under
sources/ are copies of outside documents, so they report `synced`, and they
never go stale.
"""

from datetime import date

from kb.dates import parse_date
from kb.model import Document, Section

DEFAULT_TTL_DAYS = 60
NAMED_TTL_DAYS = {"people": 14, "status": 14, "process": 60, "domain": 180}
MAX_TTL_DAYS = 1_000_000


def status(document: Document, section: Section | None, today: date) -> str:
    """The status shown in headers, such as "stale, verified 2026-08-01 (ttl 60)".

    An unresolved conflict in the article adds ", conflict".
    """
    text = (
        _sources_status(document, section)
        if document.path.startswith("sources/")
        else (_knowledge_status(document, section, today))
    )
    if document.scalar("conflict") == "unresolved":
        text += ", conflict"
    return text


def _sources_status(document: Document, section: Section | None) -> str:
    raw = document.scalar("synced", section)
    if raw is None:
        return "unknown"
    if parse_date(raw) is None:
        return "invalid"
    return f"source, synced {raw}"


def _knowledge_status(document: Document, section: Section | None, today: date) -> str:
    raw_ttl = document.scalar("ttl", section) or ""
    if raw_ttl.isascii() and raw_ttl.isdigit() and int(raw_ttl) > MAX_TTL_DAYS:
        return "invalid"
    raw = document.scalar("verified", section)
    if raw is None:
        return "unknown"
    verified = parse_date(raw)
    if verified is None:
        return "invalid"
    days = _ttl_days(raw_ttl)
    if (today - verified).days > days:
        return f"stale, verified {raw} (ttl {days})"
    return f"fresh, verified {raw}"


def _ttl_days(raw: str) -> int:
    """The threshold in days: a named ttl, a day count, or the default for anything else."""
    if raw in NAMED_TTL_DAYS:
        return NAMED_TTL_DAYS[raw]
    if raw.isascii() and raw.isdigit():
        return int(raw)
    return DEFAULT_TTL_DAYS

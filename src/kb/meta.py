"""Typed views of article and transcript observation metadata, with the line each came from."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar, cast, get_args

from kb import dates, model
from kb.model import Document, Section
from kb.transcripts import App

T = TypeVar("T")
NAMED_TTL_DAYS = {"people": 14, "status": 14, "process": 60, "domain": 180}
MAX_TTL_DAYS = 1_000_000


@dataclass(frozen=True)
class Located(Generic[T]):
    """A value and the one-based line it was read from."""

    value: T
    line: int


def resolve(document: Document, section: Section | None, name: str) -> Located[str] | None:
    """The section's own value, then its H2 parent's, then the article's front matter."""
    resolved = model.resolve_field(document, section, name)
    if resolved is None:
        return None
    value, line = resolved
    return Located(value, line if line is not None else 1)


@dataclass(frozen=True)
class Invalid:
    """A field that is present but cannot be converted."""

    text: str
    line: int


@dataclass(frozen=True)
class ArticleMeta:
    """An article's front matter fields, converted, as one section sees them.

    verified, ttl, synced, and sources are the section's own, its H2's, or the article's;
    title, updated, conflict, and aliases are always the article's. A front matter list
    is not a scalar, so a scalar field holding one reads as None. A ttl of zero converts,
    because only writers refuse it.
    """

    title: str | None
    updated: date | Invalid | None
    verified: Located[date] | Invalid | None
    ttl: Located[int] | Invalid | None
    conflict: str | None
    synced: date | Invalid | None
    sources: tuple[str, ...]
    aliases: tuple[str, ...]

    @classmethod
    def read(cls, document: Document, section: Section | None = None) -> "ArticleMeta":
        """Convert the fields of a parsed article for one section, or for the whole file."""
        return cls(
            title=document.title,
            updated=_unlocated(_date(resolve(document, None, "updated"))),
            verified=_date(resolve(document, section, "verified")),
            ttl=_ttl(resolve(document, section, "ttl")),
            conflict=document.scalar("conflict"),
            synced=_unlocated(_date(resolve(document, section, "synced"))),
            sources=document.items("sources", section),
            aliases=document.items("aliases"),
        )


def ttl_days(raw: str) -> int | None:
    """Parse a named or bounded nonnegative TTL; writers separately reject zero."""
    if raw in NAMED_TTL_DAYS:
        return NAMED_TTL_DAYS[raw]
    if raw.isascii() and raw.isdigit():
        significant = raw.lstrip("0") or "0"
        maximum = str(MAX_TTL_DAYS)
        if len(significant) < len(maximum) or (
            len(significant) == len(maximum) and significant <= maximum
        ):
            return int(significant)
    return None


def _date(located: Located[str] | None) -> Located[date] | Invalid | None:
    """A YYYY-MM-DD field as a date, Invalid when it is not one, or None when absent."""
    if located is None:
        return None
    parsed = dates.parse_date(located.value)
    return Invalid(located.value, located.line) if parsed is None else Located(parsed, located.line)


def _ttl(located: Located[str] | None) -> Located[int] | Invalid | None:
    """A TTL field in days, Invalid when it is not one, or None when absent."""
    if located is None:
        return None
    days = ttl_days(located.value)
    return Invalid(located.value, located.line) if days is None else Located(days, located.line)


def _unlocated(value: Located[date] | Invalid | None) -> date | Invalid | None:
    """The date without its line; an Invalid value keeps its line for reports."""
    return value.value if isinstance(value, Located) else value


@dataclass(frozen=True)
class TranscriptMeta:
    """A transcript observation's front matter fields, converted to their types.

    A value with an unsupported shape reads as None: an unknown app, a part that is not
    ASCII digits, a timestamp without a time zone, or message_ids that is not a list.
    """

    source: str | None
    host: str | None
    app: App | None
    session: str | None
    part: int | None
    first_message: str | None
    last_message: str | None
    started: datetime | None
    ended: datetime | None
    created: datetime | None
    forked_from: str | None = None
    message_ids: tuple[str, ...] | None = None

    @classmethod
    def read(cls, document: Document) -> "TranscriptMeta":
        """Convert the front matter of a parsed observation."""
        part_text = document.scalar("part")
        message_ids = document.front.get("message_ids")
        return cls(
            source=document.scalar("source"),
            host=document.scalar("host"),
            app=_app(document.scalar("app")),
            session=document.scalar("session"),
            part=int(part_text)
            if part_text and part_text.isascii() and part_text.isdigit()
            else None,
            first_message=document.scalar("first_message"),
            last_message=document.scalar("last_message"),
            started=_timestamp(document.scalar("started")),
            ended=_timestamp(document.scalar("ended")),
            created=_timestamp(document.scalar("created")),
            forked_from=document.scalar("forked_from"),
            message_ids=message_ids if isinstance(message_ids, tuple) else None,
        )


def _app(value: str | None) -> App | None:
    """The app named by an observation, or None for any other value."""
    return cast(App, value) if value in get_args(App) else None


def _timestamp(value: str | None) -> datetime | None:
    """A time-zone-aware ISO timestamp normalized to UTC, or None."""
    return None if value is None else dates.parse_utc(value)

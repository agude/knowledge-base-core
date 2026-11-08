"""Typed views of article, question, and observation metadata, with the line each came from."""

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from kb import dates, model
from kb.model import Document, Section
from kb.transcripts import App

T = TypeVar("T")


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
    forked_from: str | None
    message_ids: tuple[str, ...] | None

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
    if value == "claude-code":
        return "claude-code"
    if value == "codex":
        return "codex"
    if value == "goose":
        return "goose"
    return None


def _timestamp(value: str | None) -> datetime | None:
    """A time-zone-aware ISO timestamp normalized to UTC, or None."""
    return None if value is None else dates.parse_utc(value)

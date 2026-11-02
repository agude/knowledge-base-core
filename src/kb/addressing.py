"""The addressable transcript contract: the message sections and timestamps of a valid file.

chunks and evidence both read this contract, so it lives apart from either of them.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from kb.model import Document, Section

_MESSAGE_HEADING = re.compile(r"([0-9]+)\. (user|assistant), (.+)")


@dataclass(frozen=True)
class MessageSection:
    """One validated message section: its number, its role, its H2 section, and its timestamp."""

    number: int
    role: str
    section: Section
    timestamp: datetime


def message_sections(document: Document) -> tuple[MessageSection, ...] | None:
    """The validated message sections of a transcript, or None when its contract is not valid.

    H2 keys are numbered in order, so a section's key is the string of its number.
    """
    if document.scalar("source") != "session-transcript":
        return None
    if not all(
        _nonempty(document.scalar(field)) for field in ("session", "first_message", "last_message")
    ):
        return None

    part = document.scalar("part") or ""
    if not part.isascii() or not part.isdigit() or int(part) < 1:
        return None

    started = _timestamp(document.scalar("started"))
    ended = _timestamp(document.scalar("ended"))
    if started is None or ended is None or started > ended:
        return None

    sections = [section for section in document.sections if section.level == 2]
    if not sections:
        return None

    found: list[MessageSection] = []
    for number, section in enumerate(sections, start=1):
        match = _MESSAGE_HEADING.fullmatch(section.heading)
        if match is None or int(match.group(1)) != number:
            return None
        timestamp = _timestamp(match.group(3))
        if timestamp is None or not started <= timestamp <= ended:
            return None
        found.append(
            MessageSection(number=number, role=match.group(2), section=section, timestamp=timestamp)
        )
    return tuple(found)


def _timestamp(value: str | None) -> datetime | None:
    """A timezone-aware ISO timestamp normalized to UTC."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _nonempty(value: str | None) -> bool:
    """Whether a metadata field contains non-whitespace text."""
    return value is not None and bool(value.strip())

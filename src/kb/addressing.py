"""The addressable transcript contract: the message sections and timestamps of a valid file.

chunks and evidence both read this contract, so it lives apart from either of them.
"""

import re
from dataclasses import dataclass
from datetime import datetime

from kb import dates
from kb.meta import TranscriptMeta
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
    metadata = TranscriptMeta.read(document)
    if metadata.source != "session-transcript":
        return None
    if not all(
        _nonempty(value)
        for value in (metadata.session, metadata.first_message, metadata.last_message)
    ):
        return None
    if metadata.part is None or metadata.part < 1:
        return None

    started = metadata.started
    ended = metadata.ended
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
    return dates.parse_utc(value) if value else None


def _nonempty(value: str | None) -> bool:
    """Whether a metadata field contains non-whitespace text."""
    return value is not None and bool(value.strip())

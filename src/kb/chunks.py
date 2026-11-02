"""Chunks: the units of a harvested transcript that session search scores.

A chunk is a run of consecutive messages, or one piece of a long message. Scoring chunks
keeps one relevant turn in a long transcript from being diluted by the rest of the file.
The chunker is a pure function of a parsed Markdown file. It never reads host JSON.

Rules:

- A message is an addressable "## N. role, time" section of a valid transcript, or a
  legacy "### user" or "### assistant" section. A file with neither is one chunk, which
  holds its whole body.
- Injected text is removed first: spans inside <INSTRUCTIONS> and <system-reminder>, and
  user messages that start with "# AGENTS.md instructions for". Stored files never change.
- A chunk starts at a message and takes the following messages until it reaches
  MERGE_THRESHOLD characters. A chunk never crosses a file, and a long message is never
  merged.
- A message longer than SPLIT_THRESHOLD is cut into pieces of about SPLIT_TARGET
  characters, at blank lines outside code fences. Each piece is its own chunk.

- With a date bound, only the messages inside the bound are chunked. A message outside the
  bound is a barrier: no chunk spans it. The bound is a predicate over each part's timestamp,
  so the cached tokens in kb.entries and the excerpts chunk the same way.

Chunk.number and Chunk.last are the numbers of the first and last messages, or NO_MESSAGE for a
legacy or headingless file. Chunk.piece numbers the pieces of a split message. The thresholds
are module constants. Changing one changes ranking.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from kb import addressing
from kb.model import Document, fence_closes, fence_opening

MERGE_THRESHOLD = 1024
SPLIT_THRESHOLD = 4000
SPLIT_TARGET = 2000
NO_MESSAGE = 0
LEGACY_ROLES = ("user", "assistant")

_INJECTED = re.compile(
    r"<INSTRUCTIONS>.*?</INSTRUCTIONS>|<system-reminder>.*?</system-reminder>", re.DOTALL
)
_AGENTS_PREFIX = "# AGENTS.md instructions for"
_TEXT_STORAGE_OPEN = re.compile(r"(~{4,})text")


class Sized(Protocol):
    """A part as group sees it: its piece index and its length in characters."""

    @property
    def piece(self) -> int: ...

    @property
    def size(self) -> int: ...


@dataclass(frozen=True)
class Chunk:
    """A chunk and its cleaned lines.

    number and last are the numbers of its first and last messages, or NO_MESSAGE for a
    legacy or headingless file. started and ended are the timestamps of those messages, or
    None without them. piece is 0 for a chunk of whole messages, and 1, 2, ... for the
    pieces of one split message, in order.
    """

    number: int
    last: int
    started: datetime | None
    ended: datetime | None
    piece: int
    lines: tuple[str, ...]


Eligible = Callable[[datetime | None], bool]


@dataclass(frozen=True)
class Part:
    """One message, or one piece of a split message, before chunks are formed.

    piece is 0 for a whole message, and 1, 2, ... for the pieces of a split message. size is
    the length of the lines.
    """

    number: int
    timestamp: datetime | None
    piece: int
    size: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _Message:
    """A message's number, role, timestamp, first content line, and text, with authored headings.

    start and end are the raw line range of the content, end excluded.
    """

    number: int
    role: str
    timestamp: datetime | None
    head: str
    lines: tuple[str, ...]
    start: int
    end: int


def chunks(document: Document, eligible: Eligible | None = None) -> tuple[Chunk, ...]:
    """The chunks of one file, in order, with injected text removed.

    With eligible, only the messages whose timestamp it accepts are chunked, and no chunk
    spans a message that it rejects.
    """
    found = parts(document)
    return tuple(_assemble(found, eligibility(found, eligible)))


def eligibility(found: Sequence[Part], eligible: Eligible | None = None) -> list[bool]:
    """Whether each part may be chunked: eligible's verdict on its timestamp, or True for all.

    With no bound, every part is eligible.
    """
    if eligible is None:
        return [True] * len(found)
    return [eligible(part.timestamp) for part in found]


def parts(document: Document) -> list[Part]:
    """The parts of one file, in order: one per message, and one per piece of a split message.

    Each AGENTS.md instruction message is dropped. A file with no message headings is one part
    with its whole body.
    """
    messages = _messages(document)
    if messages is None:
        lines = _clean(document.prose(document.body_start, len(document.lines)))
        return [Part(NO_MESSAGE, None, 0, _length(lines), lines)]
    out: list[Part] = []
    for message in messages:
        cleaned = _clean_message(message)
        if cleaned is None:
            continue
        if _length(cleaned.lines) > SPLIT_THRESHOLD:
            out.extend(
                Part(cleaned.number, cleaned.timestamp, index, _length(piece), piece)
                for index, piece in enumerate(_split(cleaned.lines), 1)
            )
        else:
            out.append(
                Part(
                    cleaned.number,
                    cleaned.timestamp,
                    0,
                    _length(cleaned.lines),
                    cleaned.lines,
                )
            )
    return out


def group(found: Sequence[Sized], eligible: Sequence[bool]) -> list[tuple[int, int]]:
    """The [start, end) index ranges of the chunks that parts form, in order.

    eligible[index] is False for a part outside a date bound. A split piece is a chunk alone. A
    chunk of whole messages takes the following ones until it reaches MERGE_THRESHOLD characters.
    Each joining blank line counts as two characters. An ineligible part is skipped, and it ends
    the chunk before it.
    """
    if len(eligible) != len(found):
        raise ValueError("eligible must name one value per part")
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(found):
        if not eligible[index]:
            index += 1
            continue
        start = index
        index += 1
        if found[start].piece:
            ranges.append((start, index))
            continue
        size = found[start].size
        while (
            index < len(found)
            and eligible[index]
            and not found[index].piece
            and size < MERGE_THRESHOLD
        ):
            size += 2 + found[index].size
            index += 1
        ranges.append((start, index))
    return ranges


def _messages(document: Document) -> list[_Message] | None:
    """The messages of a transcript, or None when it has neither kind of message heading."""
    sections = addressing.message_sections(document)
    if sections is not None:
        messages: list[_Message] = []
        for item in sections:
            start, end = item.section.start + 1, item.section.end
            content = _unwrap_text_storage(_message_lines(document, start, end))
            messages.append(
                _Message(
                    item.number, item.role, item.timestamp, _head(content), content, start, end
                )
            )
        return messages
    return _legacy_messages(document)


def _legacy_messages(document: Document) -> list[_Message] | None:
    """The "### user" and "### assistant" messages of a legacy transcript, in order.

    The model keeps no section for an H3 without an H2 above it, so the heading lines
    are read here. Other headings remain part of the current message.
    """
    lines = document.lines
    headings = sorted(document.heading_lines)
    found: list[_Message] = []
    message_headings = [
        index
        for index in headings
        if lines[index].strip().startswith("### ") and lines[index].strip()[4:] in LEGACY_ROLES
    ]
    for position, index in enumerate(message_headings):
        heading = lines[index].strip()
        end = message_headings[position + 1] if position + 1 < len(message_headings) else len(lines)
        head = _head(lines[index + 1 : end])
        found.append(
            _Message(
                NO_MESSAGE,
                heading[4:],
                None,
                head,
                _message_lines(document, index + 1, end),
                index + 1,
                end,
            )
        )
    return found or None


def _clean_message(message: _Message) -> _Message | None:
    """The message without injected text, or None for an AGENTS.md instruction message."""
    if message.role == "user" and message.head.startswith(_AGENTS_PREFIX):
        return None
    return replace(message, lines=_clean(message.lines))


def _head(raw: Sequence[str]) -> str:
    """The first non-blank raw line, stripped, or an empty string."""
    return next((line.strip() for line in raw if line.strip()), "")


def _message_lines(document: Document, start: int, end: int) -> tuple[str, ...]:
    """Keep message headings and prose, excluding parser metadata comments."""
    return tuple(
        line
        for index, line in enumerate(document.lines[start:end], start)
        if index not in document.comment_lines
    )


def _unwrap_text_storage(lines: Sequence[str]) -> tuple[str, ...]:
    """Unwrap text storage blocks and retain command and authored code fences."""
    unwrapped: list[str] = []
    index = 0
    while index < len(lines):
        opening = fence_opening(lines[index])
        if opening is None:
            unwrapped.append(lines[index])
            index += 1
            continue

        marker, length = opening
        end = index + 1
        while end < len(lines) and not fence_closes(lines[end], marker, length):
            end += 1
        if end == len(lines):
            unwrapped.extend(lines[index:])
            break

        if marker == "~" and _TEXT_STORAGE_OPEN.fullmatch(lines[index]):
            unwrapped.extend(lines[index + 1 : end])
        else:
            unwrapped.extend(lines[index : end + 1])
        index = end + 1
    return tuple(unwrapped)


def _clean(lines: Sequence[str]) -> tuple[str, ...]:
    """The lines with injected spans removed and blank lines trimmed from both ends."""
    text = _INJECTED.sub("", "\n".join(lines))
    return _trim(text.split("\n"))


def _trim(lines: Sequence[str]) -> tuple[str, ...]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return tuple(lines[start:end])


def _length(lines: Sequence[str]) -> int:
    return len("\n".join(lines))


def _assemble(found: Sequence[Part], eligible: Sequence[bool]) -> list[Chunk]:
    """The chunks that the groups of parts form, with the blank line between messages."""
    out: list[Chunk] = []
    for start, end in group(found, eligible):
        members = found[start:end]
        lines: list[str] = []
        for position, member in enumerate(members):
            if position:
                lines.append("")
            lines.extend(member.lines)
        first, last = members[0], members[-1]
        out.append(
            Chunk(
                first.number,
                last.number,
                first.timestamp,
                last.timestamp,
                first.piece,
                tuple(lines),
            )
        )
    return out


def _split(lines: Sequence[str]) -> list[tuple[str, ...]]:
    """Cut a long message at blank lines outside code fences, about SPLIT_TARGET apart."""
    pieces: list[tuple[str, ...]] = []
    current: list[str] = []
    size = 0
    marker: str | None = None
    marker_length = 0
    for line in lines:
        if marker is not None:
            closes = fence_closes(line, marker, marker_length)
            if closes:
                marker = None
        else:
            opening = fence_opening(line)
            if opening is not None:
                marker, marker_length = opening
        if marker is None and not line.strip() and size >= SPLIT_TARGET:
            pieces.append(_trim(current))
            current = []
            size = 0
            continue
        current.append(line)
        size += len(line) + 1
    pieces.append(_trim(current))
    return [piece for piece in pieces if piece]

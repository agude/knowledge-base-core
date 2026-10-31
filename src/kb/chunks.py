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

Chunk.number is the number of the first message, or NO_MESSAGE for a legacy or headingless
file. The thresholds are module constants. Changing one changes ranking.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from kb import evidence
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


@dataclass(frozen=True)
class Chunk:
    """A chunk: the number of its first message, or NO_MESSAGE, and its cleaned lines."""

    number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _Message:
    """A message's number, role, first content line, and text, including authored headings."""

    number: int
    role: str
    head: str
    lines: tuple[str, ...]


def chunks(document: Document) -> tuple[Chunk, ...]:
    """The chunks of one file, in order, with injected text removed."""
    messages = _messages(document)
    if messages is None:
        body = document.prose(document.body_start, len(document.lines))
        return (Chunk(NO_MESSAGE, _clean(body)),)
    cleaned = [item for item in map(_clean_message, messages) if item is not None]
    return tuple(_assemble(cleaned))


def _messages(document: Document) -> list[_Message] | None:
    """The messages of a transcript, or None when it has neither kind of message heading."""
    sections = evidence.message_sections(document)
    if sections is not None:
        messages: list[_Message] = []
        for item in sections:
            content = _unwrap_text_storage(
                _message_lines(document, item.section.start + 1, item.section.end)
            )
            messages.append(_Message(item.number, item.role, _head(content), content))
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
            _Message(NO_MESSAGE, heading[4:], head, _message_lines(document, index + 1, end))
        )
    return found or None


def _clean_message(message: _Message) -> _Message | None:
    """The message without injected text, or None for an AGENTS.md instruction message."""
    if message.role == "user" and message.head.startswith(_AGENTS_PREFIX):
        return None
    return _Message(message.number, message.role, message.head, _clean(message.lines))


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


def _assemble(messages: Sequence[_Message]) -> list[Chunk]:
    """Merge short messages forward, and split each long message into its own chunks."""
    out: list[Chunk] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        index += 1
        if _length(message.lines) > SPLIT_THRESHOLD:
            out.extend(Chunk(message.number, piece) for piece in _split(message.lines))
            continue
        lines = list(message.lines)
        while (
            _length(lines) < MERGE_THRESHOLD
            and index < len(messages)
            and _length(messages[index].lines) <= SPLIT_THRESHOLD
        ):
            lines.append("")
            lines.extend(messages[index].lines)
            index += 1
        out.append(Chunk(message.number, tuple(lines)))
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

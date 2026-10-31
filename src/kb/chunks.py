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
from kb.model import Document

MERGE_THRESHOLD = 1024
SPLIT_THRESHOLD = 4000
SPLIT_TARGET = 2000
NO_MESSAGE = 0
LEGACY_ROLES = ("user", "assistant")

_INJECTED = re.compile(
    r"<INSTRUCTIONS>.*?</INSTRUCTIONS>|<system-reminder>.*?</system-reminder>", re.DOTALL
)
_AGENTS_PREFIX = "# AGENTS.md instructions for"
_FENCE = re.compile(r"\s*(?:`{3,}|~{3,})")


@dataclass(frozen=True)
class Chunk:
    """A chunk: the number of its first message, or NO_MESSAGE, and its cleaned lines."""

    number: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class _Message:
    """A message: its number, its role, its first raw line, and its prose lines.

    head is read from the raw file. A line such as "# AGENTS.md instructions" is a heading
    to the model, so it is not in the prose.
    """

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
        return [
            _Message(
                item.number,
                item.role,
                _head(document.lines[item.section.start + 1 : item.section.end]),
                document.prose(item.section.start, item.section.end),
            )
            for item in sections
        ]
    return _legacy_messages(document)


def _legacy_messages(document: Document) -> list[_Message] | None:
    """The "### user" and "### assistant" messages of a legacy transcript, in order.

    A legacy message runs from its heading to the next heading of any level. The model
    keeps no section for an H3 without an H2 above it, so the heading lines are read here.
    """
    lines = document.lines
    headings = sorted(document.heading_lines)
    found: list[_Message] = []
    for position, index in enumerate(headings):
        heading = lines[index].strip()
        if not heading.startswith("### ") or heading[4:] not in LEGACY_ROLES:
            continue
        end = headings[position + 1] if position + 1 < len(headings) else len(lines)
        head = _head(lines[index + 1 : end])
        found.append(_Message(NO_MESSAGE, heading[4:], head, document.prose(index + 1, end)))
    return found or None


def _clean_message(message: _Message) -> _Message | None:
    """The message without injected text, or None for an AGENTS.md instruction message."""
    if message.role == "user" and message.head.startswith(_AGENTS_PREFIX):
        return None
    return _Message(message.number, message.role, message.head, _clean(message.lines))


def _head(raw: Sequence[str]) -> str:
    """The first non-blank raw line, stripped, or an empty string."""
    return next((line.strip() for line in raw if line.strip()), "")


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
    fenced = False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
        if not fenced and not line.strip() and size >= SPLIT_TARGET:
            pieces.append(_trim(current))
            current = []
            size = 0
            continue
        current.append(line)
        size += len(line) + 1
    pieces.append(_trim(current))
    return [piece for piece in pieces if piece]

"""The cached records of evidence files, and the derivations that read them.

The token cache stores one Entry per evidence file. This module holds those record types and
the functions that turn an entry into search units, chunk tokens, and message tokens. It imports
chunks and search only, so token_cache and evidence can both import it without a cycle.

A transcript stores its tokens once, as parts. A part is one message, or one piece of a split
message. Its chunks are formed from the parts when a query needs them, by chunks.group, which is
also the rule that chunks.chunks uses. Other evidence stores its body and no parts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from typing import NamedTuple

from kb import chunks, search


class PartTokens(NamedTuple):
    """One part of a transcript: a message, or one piece of a split message.

    number is the message number, or chunks.NO_MESSAGE for a legacy or headingless file. The
    timestamp is in UTC, and it is None without a message heading. piece is 0 for a whole
    message. size is the length of the cleaned lines. body holds their index tokens.
    """

    number: int
    timestamp: datetime | None
    piece: int
    size: int
    body: tuple[str, ...]


class ChunkTokens(NamedTuple):
    """One chunk: the numbers and timestamps of its first and last parts, and its body tokens."""

    number: int
    last: int
    started: datetime | None
    ended: datetime | None
    piece: int
    body: tuple[str, ...]


@dataclass(frozen=True)
class Entry:
    """The cached tokens of one evidence file.

    path is content-relative. mtime_ns and size are the file's stat fields, and digest is the
    SHA-256 of its bytes. scalars holds the front matter that the ranking path reads. title holds
    the index tokens of the title. body holds the body's tokens, and it is empty for a transcript.
    parts holds a transcript's parts, and it is empty for other evidence. addressable is True
    when the transcript has message headings that addressing accepts.
    """

    path: str
    mtime_ns: int
    size: int
    digest: str
    scalars: dict[str, str]
    title: tuple[str, ...]
    body: tuple[str, ...]
    parts: tuple[PartTokens, ...]
    addressable: bool


def chunk_tokens(entry: Entry, eligible: chunks.Eligible | None = None) -> tuple[ChunkTokens, ...]:
    """The chunks of a transcript, with their tokens. Equal to chunks.chunks on the same file.

    With eligible, only the parts whose timestamp it accepts are chunked, and no chunk spans a
    part that it rejects. Without it, every part is chunked.
    """
    parts = entry.parts
    flags = (
        [True] * len(parts) if eligible is None else [eligible(part.timestamp) for part in parts]
    )
    out: list[ChunkTokens] = []
    for start, end in chunks.group(parts, flags):
        members = parts[start:end]
        first, last = members[0], members[-1]
        body = (
            members[0].body
            if len(members) == 1
            else tuple(chain.from_iterable(member.body for member in members))
        )
        out.append(
            ChunkTokens(
                first.number, last.number, first.timestamp, last.timestamp, first.piece, body
            )
        )
    return tuple(out)


def message_bodies(entry: Entry) -> dict[int, frozenset[str]]:
    """The token set of each addressable message, with its split pieces joined, by message number."""
    joined: dict[int, set[str]] = {}
    for part in entry.parts:
        if part.number:
            joined.setdefault(part.number, set()).update(part.body)
    return {number: frozenset(tokens) for number, tokens in joined.items()}


def message_moment(entry: Entry, number: int) -> datetime | None:
    """The timestamp of a message, which its first part carries."""
    for part in entry.parts:
        if part.number == number:
            return part.timestamp
    return None


def file_unit(entry: Entry) -> search.Unit:
    """The search unit of an evidence file: its title and its body."""
    return search.Unit(
        title=entry.title,
        aliases=(),
        headings=(),
        body=entry.body,
        phrases=_phrases(entry.title),
    )


def chunk_unit(entry: Entry, chunk: ChunkTokens) -> search.Unit:
    """The search unit of one chunk: its body, with the file's title and phrase."""
    return search.Unit(
        title=entry.title,
        aliases=(),
        headings=(),
        body=chunk.body,
        phrases=_phrases(entry.title),
    )


def _phrases(title: Sequence[str]) -> frozenset[str]:
    """The whole title as one phrase, so a query equal to the title scores it."""
    return frozenset({" ".join(title)}) if title else frozenset()

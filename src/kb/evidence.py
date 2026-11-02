"""Select and format matching observations, transcripts, and questions."""

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING

from kb import chunks, dates, locators, search
from kb.model import Document

if TYPE_CHECKING:
    from kb.token_cache import ChunkTokens, Entry, MessageTokens

KINDS = ("observation", "transcript", "open-question", "resolved-question")
TITLE_WIDTH = 72
READ_WITH = "Read with: kb read <locator>"
# Units are ranked as files: a transcript counts once for a term in document frequency, and
# chunks and whole files have their own average lengths.
CHUNK_CLASS = "chunk"
FILE_CLASS = "file"


@dataclass(frozen=True)
class Candidate:
    """One evidence file that a query may match, with the chunks that score it.

    scored holds a transcript's chunks, in order, as this query sees them: with date bounds,
    only the eligible messages. It is empty for other kinds, which score as whole files.
    addressable is True when the transcript has addressable messages.
    """

    path: str
    entry: "Entry"
    kind: str
    created: date | None
    addressable: bool
    scored: "tuple[ChunkTokens, ...]"


@dataclass(frozen=True)
class Item:
    """One output row, with its file-level score kept private for sorting.

    chunk is the position of the winning chunk in the transcript's chunk list, or None for
    evidence that is not a transcript. message_number is the matched message, or None.
    """

    path: str
    date: date | None
    kind: str
    text: str
    score: float
    message_number: int | None
    chunk: int | None = None


def select(
    entries: Sequence["Entry"],
    terms: Sequence[str],
    kind_filter: str | None,
    since: date | None,
    until: date | None,
    limit: int,
    read: Callable[[str], Document],
) -> list[Item]:
    """Rank the eligible files, and show each transcript's best chunk and matched message.

    A transcript scores as its best chunk, and a chunk scores with the file's title. Other
    evidence scores as a whole file. With date bounds, a transcript is chunked from its eligible
    messages only. Ranking uses the cached tokens alone. A document is read only for each row
    that is printed, to build its excerpt.
    """
    has_date_bound = since is not None or until is not None
    eligible = _eligible(since, until) if has_date_bound else None
    candidates: list[Candidate] = []
    units: list[search.Unit] = []
    owners: list[tuple[int, int]] = []
    unit_classes: list[str] = []

    for entry in entries:
        kind = evidence_kind(entry.path, entry.scalars.get("source"))
        if kind_filter is not None and kind != kind_filter:
            continue

        created = created_date_of(entry.scalars.get("created"))
        addressable = kind == "transcript" and bool(entry.messages)
        if addressable and eligible is not None:
            scored = _bounded_chunks(entry, eligible)
        elif not addressable and has_date_bound and not _within(created, since, until):
            continue
        else:
            scored = entry.chunks
        if kind == "transcript" and not scored:
            continue

        index = len(candidates)
        candidates.append(Candidate(entry.path, entry, kind, created, addressable, tuple(scored)))
        if kind == "transcript":
            for position, found in enumerate(scored):
                units.append(_chunk_unit(entry, found))
                owners.append((index, position))
                unit_classes.append(CHUNK_CLASS)
        else:
            units.append(file_unit(entry))
            owners.append((index, -1))
            unit_classes.append(FILE_CLASS)

    best: dict[int, tuple[float, int]] = {}
    ranked = search.rank(
        units,
        terms,
        groups=[owner for owner, _position in owners],
        classes=unit_classes,
    )
    for hit in ranked:
        index, position = owners[hit.index]
        best.setdefault(index, (hit.score, position))
    rows = [
        (_row(candidates[index], score, position, terms), candidates[index])
        for index, (score, position) in best.items()
    ]
    rows.sort(key=lambda pair: _sort_key(pair[0]))
    return [
        replace(item, text=_excerpt_for(candidate, item, terms, read, eligible))
        for item, candidate in rows[:limit]
    ]


def evidence_kind(path: str, source: str | None) -> str:
    """The evidence kind from its storage area and its transcript source marker."""
    if path.startswith("questions/open/"):
        return "open-question"
    if path.startswith("questions/resolved/"):
        return "resolved-question"
    if source == "session-transcript":
        return "transcript"
    return "observation"


def file_unit(entry: "Entry") -> search.Unit:
    """The search unit of an evidence file, built from its cached tokens."""
    title, aliases, headings, body, phrases = entry.file_unit
    return search.Unit(
        title=title,
        aliases=aliases,
        headings=headings,
        body=body,
        phrases=frozenset(phrases),
    )


def _chunk_unit(entry: "Entry", found: "ChunkTokens") -> search.Unit:
    """The search unit of one chunk: its body, with the file's title and phrases."""
    title, _aliases, _headings, _body, phrases = entry.file_unit
    return search.Unit(
        title=title,
        aliases=(),
        headings=(),
        body=found[5],
        phrases=frozenset(phrases),
    )


def _bounded_chunks(entry: "Entry", eligible: chunks.Eligible) -> "tuple[ChunkTokens, ...]":
    """The chunks of an addressable transcript from its eligible messages only.

    Split pieces are kept as cached. Whole messages are merged again from their cached tokens
    and lengths, by the same rule as chunks.chunks, so a chunk never spans a message that
    eligible rejects. Without rejected messages, the result equals entry.chunks.
    """
    pieces: dict[int, list[tuple[str, ...]]] = {}
    for chunk in entry.chunks:
        if chunk[4]:
            pieces.setdefault(chunk[0], []).append(chunk[5])
    found: list[chunks.Part] = []
    bodies: list[tuple[str, ...]] = []
    for number, moment, body, size in entry.messages:
        started = datetime.fromisoformat(moment)
        if number in pieces:
            for index, piece in enumerate(pieces[number], 1):
                found.append(chunks.Part(number, started, index, 0, (), eligible(started)))
                bodies.append(piece)
        else:
            found.append(chunks.Part(number, started, 0, size, (), eligible(started)))
            bodies.append(body)
    out: list[ChunkTokens] = []
    for start, end in chunks.group(found):
        first, last = found[start], found[end - 1]
        tokens = tuple(token for index in range(start, end) for token in bodies[index])
        out.append(
            (
                first.number,
                last.number,
                _iso(first.timestamp),
                _iso(last.timestamp),
                first.piece,
                tokens,
            )
        )
    return tuple(out)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def _eligible(since: date | None, until: date | None) -> chunks.Eligible:
    """The chunk filter for date bounds. A message is eligible by its UTC date."""

    def eligible(moment: datetime | None) -> bool:
        return moment is None or _within(moment.date(), since, until)

    return eligible


def created_date(document: Document) -> date | None:
    """The valid date portion of an evidence file's created value."""
    return created_date_of(document.scalar("created"))


def created_date_of(created: str | None) -> date | None:
    """The valid date portion of a created value."""
    return dates.parse_date((created or "")[:10])


def format_results(query: str, items: Sequence[Item]) -> str:
    """Render selected rows or the exact no-match line."""
    if not items:
        return f'No evidence matches "{query}".\n'
    return "\n".join(["Evidence:", *format_rows(items), READ_WITH]) + "\n"


def format_rows(items: Sequence[Item]) -> list[str]:
    """Evidence rows with the locator and kind columns padded to their widest entries."""
    if not items:
        return []
    path_width = max(len(item.path) for item in items)
    kind_width = max(len(item.kind.replace("-", " ")) for item in items)
    return [
        f"  {item.path.ljust(path_width)} | {item.date.isoformat() if item.date else ''} | "
        f"{item.kind.replace('-', ' ').ljust(kind_width)} | {item.text}"
        for item in items
    ]


def _row(
    candidate: Candidate,
    score: float,
    position: int,
    terms: Sequence[str],
) -> Item:
    """One row without its excerpt. A row names its matched message when one holds half the terms."""
    if candidate.kind != "transcript":
        return Item(candidate.path, candidate.created, candidate.kind, "", score, None)
    message = None
    if candidate.addressable:
        message = _matched_message(candidate, candidate.scored[position], terms)
    if message is None:
        return Item(candidate.path, candidate.created, candidate.kind, "", score, None, position)
    return Item(
        path=f"{candidate.path}#{message[0]}",
        date=_message_date(message),
        kind=candidate.kind,
        text="",
        score=score,
        message_number=message[0],
        chunk=position,
    )


def _matched_message(
    candidate: Candidate, found: "ChunkTokens", terms: Sequence[str]
) -> "MessageTokens | None":
    """The message of the chunk with the most distinct query terms, or None when it holds fewer
    than half of them. A match spread over several messages keeps the file locator.

    Ties go to the earlier message.
    """
    wanted = frozenset(terms)
    members = [
        message for message in candidate.entry.messages if found[0] <= message[0] <= found[1]
    ]
    if not members:
        raise ValueError(f"{candidate.path} has no message {found[0]}")
    best = max(members, key=lambda message: (len(wanted.intersection(message[2])), -message[0]))
    if len(wanted.intersection(best[2])) < math.ceil(len(wanted) / 2):
        return None
    return best


def _excerpt_for(
    candidate: Candidate,
    item: Item,
    terms: Sequence[str],
    read: Callable[[str], Document],
    eligible: chunks.Eligible | None,
) -> str:
    """The excerpt of a printed row, read from its document.

    A transcript row shows the text of its winning chunk, which may hold messages after the
    matched one. Other evidence shows its title.
    """
    document = read(candidate.path)
    if candidate.kind != "transcript":
        return search.clip(locators.display_title(document), TITLE_WIDTH)
    listed = chunks.chunks(document, eligible)
    if item.chunk is None or item.chunk >= len(listed):
        raise ValueError(f"{candidate.path} has no chunk {item.chunk}")
    return search.excerpt(_excerpt_lines(listed[item.chunk].lines), terms)


def _message_date(message: "MessageTokens") -> date:
    """The UTC date of a cached message timestamp."""
    return datetime.fromisoformat(message[1]).date()


def _excerpt_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """Drop Markdown fence markers while retaining fenced text and shell commands."""
    return tuple(line for line in lines if re.match(r"\s*(?:`{3,}|~{3,})", line) is None)


def _within(value: date | None, since: date | None, until: date | None) -> bool:
    """Whether a known date is inside the inclusive bounds."""
    return (
        value is not None
        and (since is None or since <= value)
        and (until is None or value <= until)
    )


def _sort_key(item: Item) -> tuple[float, bool, int, str, int]:
    """Descending score and date, then path and numeric message number."""
    return (
        -item.score,
        item.date is None,
        -(item.date.toordinal() if item.date is not None else 0),
        item.path.partition("#")[0],
        item.message_number or 0,
    )

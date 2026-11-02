"""Select and format matching observations, transcripts, and questions."""

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

from kb import chunks, dates, locators, search
from kb.entries import (
    ChunkTokens,
    Entry,
    chunk_tokens,
    chunk_unit,
    file_unit,
    message_bodies,
    message_moment,
)
from kb.model import Document

KINDS = ("observation", "transcript", "open-question", "resolved-question")
TITLE_WIDTH = 72
READ_WITH = "Read with: kb read <locator>"
# Units are ranked as files: a transcript counts once for a term in document frequency, and
# chunks and whole files have their own average lengths. DELTA is the BM25+ lower bound.
CHUNK_CLASS = "chunk"
FILE_CLASS = "file"
DELTA = 1.0


@dataclass(frozen=True)
class Candidate:
    """One evidence file that a query may match, with the chunks that score it.

    scored holds a transcript's chunks, in order, as this query sees them: with date bounds,
    only the eligible messages. It is empty for other kinds, which score as whole files.
    addressable is True when the transcript has addressable messages.
    """

    path: str
    entry: Entry
    kind: str
    created: date | None
    addressable: bool
    scored: tuple[ChunkTokens, ...]


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
    entries: Sequence[Entry],
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
        if kind == "transcript":
            # Legacy transcripts have no message dates, so they keep the created-date filter.
            if has_date_bound and not entry.addressable and not _within(created, since, until):
                continue
            scored = chunk_tokens(entry, eligible if entry.addressable else None)
            if not scored:
                continue
        else:
            if has_date_bound and not _within(created, since, until):
                continue
            scored = ()

        index = len(candidates)
        candidates.append(Candidate(entry.path, entry, kind, created, entry.addressable, scored))
        if kind == "transcript":
            for position, found in enumerate(scored):
                units.append(chunk_unit(entry, found))
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
        delta=DELTA,
    )
    for hit in ranked:
        index, position = owners[hit.index]
        best.setdefault(index, (hit.score, position))

    # A row's date comes from its matched message, so a row is built only when the limit needs
    # it. Rows that tie the last row kept are built as well, because their date breaks the tie.
    ordered = sorted(best.items(), key=lambda pair: -pair[1][0])
    built = [
        (_row(candidates[index], score, position, terms), candidates[index])
        for index, (score, position) in ordered[: _built_count(ordered, limit)]
    ]
    built.sort(key=lambda pair: _sort_key(pair[0]))
    return [
        replace(item, text=_excerpt_for(candidate, item, terms, read, eligible))
        for item, candidate in built[:limit]
    ]


def _built_count(ordered: Sequence[tuple[int, tuple[float, int]]], limit: int) -> int:
    """How many leading rows to build: limit rows, and any that tie the last one of them."""
    if limit <= 0:
        return 0
    if len(ordered) <= limit:
        return len(ordered)
    boundary = ordered[limit - 1][1][0]
    count = limit
    while count < len(ordered) and ordered[count][1][0] == boundary:
        count += 1
    return count


def evidence_kind(path: str, source: str | None) -> str:
    """The evidence kind from its storage area and its transcript source marker."""
    if path.startswith("questions/open/"):
        return "open-question"
    if path.startswith("questions/resolved/"):
        return "resolved-question"
    if source == "session-transcript":
        return "transcript"
    return "observation"


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
    number = None
    if candidate.addressable:
        number = _matched_message(candidate, candidate.scored[position], terms)
    if number is None:
        return Item(candidate.path, candidate.created, candidate.kind, "", score, None, position)
    moment = message_moment(candidate.entry, number)
    if moment is None:
        raise ValueError(f"{candidate.path} message {number} has no timestamp")
    return Item(
        path=f"{candidate.path}#{number}",
        date=moment.date(),
        kind=candidate.kind,
        text="",
        score=score,
        message_number=number,
        chunk=position,
    )


def _matched_message(candidate: Candidate, found: ChunkTokens, terms: Sequence[str]) -> int | None:
    """The number of the message in the chunk with the most distinct query terms, or None when it
    holds fewer than half of them. A match spread over several messages keeps the file locator.

    Ties go to the earlier message.
    """
    wanted = frozenset(terms)
    members = [
        (number, body)
        for number, body in message_bodies(candidate.entry).items()
        if found.number <= number <= found.last
    ]
    if not members:
        raise ValueError(f"{candidate.path} has no message {found.number}")
    number, body = max(
        members, key=lambda member: (len(wanted.intersection(member[1])), -member[0])
    )
    if len(wanted.intersection(body)) < math.ceil(len(wanted) / 2):
        return None
    return number


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

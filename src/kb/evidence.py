"""Select and format matching observations, transcripts, and questions."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING

from kb import addressing, chunks, dates, locators, search
from kb.model import Document, Section

if TYPE_CHECKING:
    from kb.token_cache import Entry, MessageTokens

KINDS = ("observation", "transcript", "open-question", "resolved-question")
TITLE_WIDTH = 72
READ_WITH = "Read with: kb read <locator>"


@dataclass(frozen=True)
class Message:
    """One validated harvested message and its body-only search unit."""

    number: int
    section: Section
    timestamp: datetime
    body: tuple[str, ...]
    unit: search.Unit


@dataclass(frozen=True)
class Candidate:
    """One searchable evidence file, its cache entry, and its addressable messages.

    messages is None unless the file is an addressable transcript with at least one message.
    """

    path: str
    entry: "Entry"
    kind: str
    created: date | None
    messages: "tuple[MessageTokens, ...] | None"


@dataclass(frozen=True)
class Item:
    """One output row, with its file-level score kept private for sorting."""

    path: str
    date: date | None
    kind: str
    text: str
    score: float
    message_number: int | None


def select(
    entries: Sequence["Entry"],
    terms: Sequence[str],
    kind_filter: str | None,
    since: date | None,
    until: date | None,
    limit: int,
    read: Callable[[str], Document],
) -> list[Item]:
    """Rank eligible files, then select a qualifying message when one is addressable.

    Ranking uses the cached tokens alone. A document is read only for each row that is
    printed, to build its excerpt.
    """
    candidates: list[Candidate] = []
    matching_messages: dict[str, tuple[tuple[MessageTokens, float], ...]] = {}
    has_date_bound = since is not None or until is not None

    for entry in entries:
        kind = evidence_kind(entry.path, entry.scalars.get("source"))
        if kind_filter is not None and kind != kind_filter:
            continue

        created = created_date_of(entry.scalars.get("created"))
        messages = entry.messages if kind == "transcript" and entry.messages else None
        if messages is None:
            if has_date_bound and not _within(created, since, until):
                continue
        else:
            eligible = tuple(
                message
                for message in messages
                if not has_date_bound or _within(_message_date(message), since, until)
            )
            message_hits = search.rank([message_unit(message) for message in eligible], terms)
            if has_date_bound and not message_hits:
                continue
            matching_messages[entry.path] = tuple(
                (eligible[hit.index], hit.score) for hit in message_hits
            )

        candidates.append(Candidate(entry.path, entry, kind, created, messages))

    file_hits = search.rank([file_unit(candidate.entry) for candidate in candidates], terms)
    items = [
        _row(
            candidates[hit.index],
            hit.score,
            matching_messages.get(candidates[hit.index].path, ()),
        )
        for hit in file_hits
    ]
    items.sort(key=_sort_key)
    by_path = {candidate.path: candidate for candidate in candidates}
    return [
        replace(item, text=_excerpt_for(by_path[item.path.partition("#")[0]], item, terms, read))
        for item in items[:limit]
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


def message_unit(message: "MessageTokens") -> search.Unit:
    """The search unit of a cached message: its body only, as addressable_messages builds it."""
    return search.Unit(title=(), aliases=(), headings=(), body=message[2], phrases=frozenset())


def addressable_messages(document: Document) -> tuple[Message, ...] | None:
    """The transcript's messages when its complete addressability contract is valid."""
    sections = addressing.message_sections(document)
    if sections is None:
        return None
    messages: list[Message] = []
    for item in sections:
        body = document.prose(item.section.start, item.section.end)
        messages.append(
            Message(
                number=item.number,
                section=item.section,
                timestamp=item.timestamp,
                body=body,
                unit=search.make_unit("", (), (), body),
            )
        )
    return tuple(messages)


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
    matched_messages: Sequence[tuple["MessageTokens", float]],
) -> Item:
    """One row without its excerpt: the best message when one matched, else the file."""
    if candidate.messages is not None and matched_messages:
        message, _message_score = min(
            matched_messages,
            key=lambda match: (-match[1], match[0][0]),
        )
        return Item(
            path=f"{candidate.path}#{message[0]}",
            date=_message_date(message),
            kind=candidate.kind,
            text="",
            score=score,
            message_number=message[0],
        )
    return Item(candidate.path, candidate.created, candidate.kind, "", score, None)


def _excerpt_for(
    candidate: Candidate, item: Item, terms: Sequence[str], read: Callable[[str], Document]
) -> str:
    """The excerpt of a printed row, read from its document.

    A row for a message shows that message. A file-level transcript shows its best chunk,
    or its whole body when no chunk holds a query term.
    """
    document = read(candidate.path)
    if item.message_number is not None:
        section = document.section(str(item.message_number))
        if section is None:
            raise ValueError(f"{candidate.path} has no message {item.message_number}")
        return search.excerpt(document.prose(section.start, section.end), terms)
    if candidate.kind == "transcript":
        found = chunks.best(document, terms)
        if found is not None:
            return search.excerpt(_excerpt_lines(found.lines), terms)
        body = _excerpt_lines(document.prose(document.body_start, len(document.lines)))
        return search.excerpt(body, terms)
    return search.clip(locators.display_title(document), TITLE_WIDTH)


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

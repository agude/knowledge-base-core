"""Select and format matching observations, transcripts, and questions."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from kb import dates, locators, search
from kb.model import Document, Section

KINDS = ("observation", "transcript", "open-question", "resolved-question")
TITLE_WIDTH = 72
READ_WITH = "Read with: kb read <locator>"
_MESSAGE_HEADING = re.compile(r"([0-9]+)\. (user|assistant), (.+)")


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
    """One searchable evidence file and any addressable harvested messages."""

    path: str
    document: Document
    kind: str
    created: date | None
    messages: tuple[Message, ...] | None


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
    documents: Sequence[tuple[str, Document]],
    terms: Sequence[str],
    kind_filter: str | None,
    since: date | None,
    until: date | None,
    limit: int,
) -> list[Item]:
    """Rank eligible files, then select a qualifying message when one is addressable."""
    candidates: list[Candidate] = []
    matching_messages: dict[str, tuple[tuple[Message, float], ...]] = {}
    has_date_bound = since is not None or until is not None

    for path, document in documents:
        kind = evidence_kind(path, document)
        if kind_filter is not None and kind != kind_filter:
            continue

        created = created_date(document)
        messages = addressable_messages(document) if kind == "transcript" else None
        if messages is None:
            if has_date_bound and not _within(created, since, until):
                continue
        else:
            eligible_messages = tuple(
                message
                for message in messages
                if not has_date_bound or _within(message.timestamp.date(), since, until)
            )
            message_hits = search.rank([message.unit for message in eligible_messages], terms)
            if has_date_bound and not message_hits:
                continue
            matching_messages[path] = tuple(
                (eligible_messages[hit.index], hit.score) for hit in message_hits
            )

        candidates.append(Candidate(path, document, kind, created, messages))

    file_hits = search.rank([search.evidence_unit(item.document) for item in candidates], terms)
    items = [
        _item(
            candidates[hit.index],
            hit.score,
            matching_messages.get(candidates[hit.index].path, ()),
            terms,
        )
        for hit in file_hits
    ]
    items.sort(key=_sort_key)
    return items[:limit]


def evidence_kind(path: str, document: Document) -> str:
    """The evidence kind from its storage area and transcript source marker."""
    if path.startswith("questions/open/"):
        return "open-question"
    if path.startswith("questions/resolved/"):
        return "resolved-question"
    if document.scalar("source") == "session-transcript":
        return "transcript"
    return "observation"


def addressable_messages(document: Document) -> tuple[Message, ...] | None:
    """The transcript's messages when its complete addressability contract is valid."""
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

    messages: list[Message] = []
    for number, section in enumerate(sections, start=1):
        match = _MESSAGE_HEADING.fullmatch(section.heading)
        if match is None or int(match.group(1)) != number:
            return None
        timestamp = _timestamp(match.group(3))
        if timestamp is None or not started <= timestamp <= ended:
            return None
        body = document.prose(section.start, section.end)
        messages.append(
            Message(
                number=number,
                section=section,
                timestamp=timestamp,
                body=body,
                unit=search.make_unit("", (), (), body),
            )
        )
    return tuple(messages)


def created_date(document: Document) -> date | None:
    """The valid date portion of an evidence file's created value."""
    created = document.scalar("created") or ""
    return dates.parse_date(created[:10])


def format_results(query: str, items: Sequence[Item]) -> str:
    """Render selected rows or the exact no-match line."""
    if not items:
        return f'No evidence matches "{query}".\n'
    path_width = max(len(item.path) for item in items)
    kind_width = max(len(item.kind.replace("-", " ")) for item in items)
    lines = ["Evidence:"]
    lines.extend(
        f"  {item.path.ljust(path_width)} | {item.date.isoformat() if item.date else ''} | "
        f"{item.kind.replace('-', ' ').ljust(kind_width)} | {item.text}"
        for item in items
    )
    lines.append(READ_WITH)
    return "\n".join(lines) + "\n"


def _item(
    candidate: Candidate,
    score: float,
    matched_messages: Sequence[tuple[Message, float]],
    terms: Sequence[str],
) -> Item:
    """Choose a message locator or keep the evidence file locator."""
    if candidate.messages is not None and matched_messages:
        message, _message_score = min(
            matched_messages,
            key=lambda match: (-match[1], match[0].number),
        )
        return Item(
            path=f"{candidate.path}#{message.section.key}",
            date=message.timestamp.date(),
            kind=candidate.kind,
            text=search.excerpt(message.body, terms),
            score=score,
            message_number=message.number,
        )

    if candidate.kind == "transcript":
        body = _excerpt_lines(
            candidate.document.prose(candidate.document.body_start, len(candidate.document.lines))
        )
        text = search.excerpt(body, terms)
    else:
        text = search.clip(locators.display_title(candidate.document), TITLE_WIDTH)
    return Item(candidate.path, candidate.created, candidate.kind, text, score, None)


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


def _excerpt_lines(lines: Sequence[str]) -> tuple[str, ...]:
    """Drop Markdown fence markers while retaining fenced text and shell commands."""
    return tuple(line for line in lines if re.match(r"\s*(?:`{3,}|~{3,})", line) is None)


def _nonempty(value: str | None) -> bool:
    """Whether a metadata field contains non-whitespace text."""
    return value is not None and bool(value.strip())


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

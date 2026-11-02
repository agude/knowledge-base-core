"""The cached selection must print the same rows as the document-based selection it replaced.

reference_select is that earlier selection, kept here as the old path. It reads every
document and builds every unit from its text. The new path ranks cache entries and
reads a document only for printed rows. Both run over every fixture corpus, a fixed
query list, and several kind and date filters.
"""

import math
from datetime import date, datetime
from pathlib import Path

import pytest

from kb import chunks, corpus, evidence, locators, search, token_cache
from kb.model import Document, parse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPORA = (
    FIXTURES / "content",
    FIXTURES / "evidence-content",
)
QUERIES = (
    "nas restart",
    "traefik",
    "backup disk",
    "telemetry worker",
    "subagent inventory",
    "curator cadence",
    "session",
    "outage",
    "codex",
    "observation",
    "decision",
    "the",
    "zzz missing",
)
FILTERS = (
    (None, None, None),
    ("transcript", None, None),
    ("observation", None, None),
    (None, date(2026, 10, 1), None),
    ("transcript", date(2026, 10, 20), date(2026, 10, 22)),
    ("transcript", date(2026, 10, 21), None),
)


def _within(value: date | None, since: date | None, until: date | None) -> bool:
    return (
        value is not None
        and (since is None or since <= value)
        and (until is None or value <= until)
    )


def _eligible(since: date | None, until: date | None) -> chunks.Eligible:
    def eligible(moment: datetime | None) -> bool:
        return moment is None or _within(moment.date(), since, until)

    return eligible


def _sort_key(item: evidence.Item) -> tuple[float, bool, int, str, int]:
    return (
        -item.score,
        item.date is None,
        -(item.date.toordinal() if item.date is not None else 0),
        item.path.partition("#")[0],
        item.message_number or 0,
    )


def reference_select(
    documents: list[tuple[str, Document]],
    terms: list[str],
    kind_filter: str | None,
    since: date | None,
    until: date | None,
    limit: int,
) -> list[evidence.Item]:
    """The selection rules, written from documents: chunks come from chunks.chunks, not the cache."""
    has_date_bound = since is not None or until is not None
    eligible = _eligible(since, until) if has_date_bound else None
    candidates: list[tuple[str, Document, str, date | None, bool, tuple[chunks.Chunk, ...]]] = []
    units: list[search.Unit] = []
    owners: list[tuple[int, int]] = []
    unit_classes: list[str] = []
    for path, document in documents:
        kind = evidence.evidence_kind(path, document.scalar("source"))
        if kind_filter is not None and kind != kind_filter:
            continue
        created = evidence.created_date(document)
        addressable = kind == "transcript" and any(part.number for part in chunks.parts(document))
        if addressable:
            listed = chunks.chunks(document, eligible)
            if not listed:
                continue
        else:
            if has_date_bound and not _within(created, since, until):
                continue
            listed = chunks.chunks(document) if kind == "transcript" else ()
        index = len(candidates)
        candidates.append((path, document, kind, created, addressable, listed))
        if kind == "transcript":
            title = search.index_tokens(document.title or "")
            phrases = frozenset({" ".join(title)}) if title else frozenset()
            for position, chunk in enumerate(listed):
                body = tuple(token for line in chunk.lines for token in search.index_tokens(line))
                units.append(search.Unit(title, (), (), body, phrases))
                owners.append((index, position))
                unit_classes.append(evidence.CHUNK_CLASS)
        else:
            units.append(search.evidence_unit(document))
            owners.append((index, -1))
            unit_classes.append(evidence.FILE_CLASS)

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
    items = []
    for index, (score, position) in best.items():
        path, document, kind, created, addressable, listed = candidates[index]
        if kind != "transcript":
            text = search.clip(locators.display_title(document), evidence.TITLE_WIDTH)
            items.append(evidence.Item(path, created, kind, text, score, None))
            continue
        chunk = listed[position]
        text = search.excerpt(evidence._excerpt_lines(chunk.lines), terms)
        if not addressable:
            items.append(evidence.Item(path, created, kind, text, score, None, position))
            continue
        members: dict[int, list[str]] = {}
        moments: dict[int, datetime] = {}
        for part in chunks.parts(document, eligible):
            if part.number and chunk.number <= part.number <= chunk.last:
                members.setdefault(part.number, []).extend(
                    token for line in part.lines for token in search.index_tokens(line)
                )
                assert part.timestamp is not None
                moments.setdefault(part.number, part.timestamp)
        wanted = set(terms)
        number = max(members, key=lambda n: (len(wanted & set(members[n])), -n))
        if len(wanted & set(members[number])) < math.ceil(len(wanted) / 2):
            items.append(evidence.Item(path, created, kind, text, score, None, position))
            continue
        items.append(
            evidence.Item(
                path=f"{path}#{number}",
                date=moments[number].date(),
                kind=kind,
                text=text,
                score=score,
                message_number=number,
                chunk=position,
            )
        )
    items.sort(key=_sort_key)
    return items[:limit]


@pytest.mark.parametrize("root", CORPORA, ids=[str(path.relative_to(FIXTURES)) for path in CORPORA])
def test_the_cached_selection_prints_what_the_document_selection_printed(root: Path) -> None:
    paths = token_cache.evidence_paths(root)
    assert paths
    loaded = token_cache.load(root, paths)
    entries = [loaded[path] for path in paths]
    documents = [(path, corpus.read_document(root, path)) for path in paths]
    read = corpus.Documents(root).read

    non_empty = 0
    for query in QUERIES:
        terms = list(search.query_terms(query.split()))
        for kind_filter, since, until in FILTERS:
            expected = reference_select(documents, terms, kind_filter, since, until, 5)
            actual = evidence.select(entries, terms, kind_filter, since, until, 5, read)
            assert actual == expected, (query, kind_filter, since, until)
            non_empty += bool(actual)
    assert non_empty > 0


def test_a_printed_row_whose_chunk_is_missing_from_the_document_is_an_error(tmp_path: Path) -> None:
    long_text = "filler words " * 100
    transcript = (
        "---\nsource: session-transcript\nsession: s\npart: 1\nfirst_message: a\n"
        "last_message: b\nstarted: 2026-10-01T09:00:00Z\nended: 2026-10-01T09:05:00Z\n---\n\n"
        f"## 1. user, 2026-10-01T09:00:00Z\n\n{long_text}\n\n"
        f"## 2. assistant, 2026-10-01T09:01:00Z\n\n{long_text}restart the NAS.\n"
    )
    target = tmp_path / "content" / "observations" / "archived" / "t.md"
    target.parent.mkdir(parents=True)
    target.write_text(transcript, encoding="utf-8")
    entries = list(token_cache.load(tmp_path / "content", ["observations/archived/t.md"]).values())

    def without_sections(relpath: str) -> Document:
        return parse(relpath, "---\nsource: session-transcript\n---\nNo headings here.\n")

    with pytest.raises(ValueError, match="has no chunk 1"):
        evidence.select(entries, ["restart"], None, None, None, 5, without_sections)

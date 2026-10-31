"""The cached selection must print the same rows as the document-based selection it replaced.

reference_select is that earlier selection, kept here as the old path. It reads every
document and builds every unit from its text. The new path ranks cache entries and
reads a document only for printed rows. Both run over every fixture corpus, a fixed
query list, and several kind and date filters.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from kb import corpus, evidence, locators, search, token_cache
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
)


@dataclass(frozen=True)
class _Candidate:
    path: str
    document: Document
    kind: str
    created: date | None
    messages: tuple[evidence.Message, ...] | None


def _within(value: date | None, since: date | None, until: date | None) -> bool:
    return (
        value is not None
        and (since is None or since <= value)
        and (until is None or value <= until)
    )


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
    candidates: list[_Candidate] = []
    matching: dict[str, tuple[tuple[evidence.Message, float], ...]] = {}
    has_date_bound = since is not None or until is not None
    for path, document in documents:
        kind = evidence.evidence_kind(path, document.scalar("source"))
        if kind_filter is not None and kind != kind_filter:
            continue
        created = evidence.created_date(document)
        messages = evidence.addressable_messages(document) if kind == "transcript" else None
        if messages is None:
            if has_date_bound and not _within(created, since, until):
                continue
        else:
            eligible = tuple(
                message
                for message in messages
                if not has_date_bound or _within(message.timestamp.date(), since, until)
            )
            hits = search.rank([message.unit for message in eligible], terms)
            if has_date_bound and not hits:
                continue
            matching[path] = tuple((eligible[hit.index], hit.score) for hit in hits)
        candidates.append(_Candidate(path, document, kind, created, messages))

    file_hits = search.rank([search.evidence_unit(c.document) for c in candidates], terms)
    items = [
        _reference_item(
            candidates[hit.index], hit.score, matching.get(candidates[hit.index].path, ()), terms
        )
        for hit in file_hits
    ]
    items.sort(key=_sort_key)
    return items[:limit]


def _reference_item(
    candidate: _Candidate,
    score: float,
    matched: tuple[tuple[evidence.Message, float], ...],
    terms: list[str],
) -> evidence.Item:
    if candidate.messages is not None and matched:
        message, _ = min(matched, key=lambda match: (-match[1], match[0].number))
        return evidence.Item(
            path=f"{candidate.path}#{message.section.key}",
            date=message.timestamp.date(),
            kind=candidate.kind,
            text=search.excerpt(message.body, terms),
            score=score,
            message_number=message.number,
        )
    if candidate.kind == "transcript":
        body = evidence._excerpt_lines(
            candidate.document.prose(candidate.document.body_start, len(candidate.document.lines))
        )
        text = search.excerpt(body, terms)
    else:
        text = search.clip(locators.display_title(candidate.document), evidence.TITLE_WIDTH)
    return evidence.Item(candidate.path, candidate.created, candidate.kind, text, score, None)


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


def test_a_printed_message_whose_section_is_missing_is_an_error(tmp_path: Path) -> None:
    transcript = (
        "---\nsource: session-transcript\nsession: s\npart: 1\nfirst_message: a\n"
        "last_message: b\nstarted: 2026-10-01T09:00:00Z\nended: 2026-10-01T09:05:00Z\n---\n\n"
        "## 1. user, 2026-10-01T09:00:00Z\n\nRestart the NAS.\n"
    )
    target = tmp_path / "content" / "observations" / "archived" / "t.md"
    target.parent.mkdir(parents=True)
    target.write_text(transcript, encoding="utf-8")
    entries = list(token_cache.load(tmp_path / "content", ["observations/archived/t.md"]).values())

    def without_sections(relpath: str) -> Document:
        return parse(relpath, "---\nsource: session-transcript\n---\nNo headings here.\n")

    with pytest.raises(ValueError, match="has no message 1"):
        evidence.select(entries, ["restart"], None, None, None, 5, without_sections)

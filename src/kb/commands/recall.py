"""kb recall: the curated sections that answer a query, and the evidence when none do.

Curated knowledge (knowledge/ and sources/) is searched first. Pending
observations are searched on every call and listed as uncurated. When no
curated section qualifies, the archived observations and the questions are
searched too, and the best of them are listed as evidence.
"""

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kb import args, corpus, freshness, locators, search
from kb.args import Spec
from kb.context import Context, load
from kb.dates import parse_date
from kb.errors import KbError
from kb.model import Document

WHO = "kb recall"
DEFAULT_LIMIT = 3
FOLLOW_UP = 5
TITLE_WIDTH = 72
READ_WITH = "Read with: kb read <locator>"
PENDING = "observations/pending"
ARCHIVED = "observations/archived"
QUESTIONS = ("questions/open", "questions/resolved")
SPEC = Spec(
    usage="recall QUERY... [--limit N] [--in PATH]",
    summary=(
        "Find the curated sections that answer QUERY, each with its header line. When none\n"
        "match, list the observations and questions that do. --limit N sets how many sections\n"
        "print in full (default 3). --in PATH limits the search to a file or directory."
    ),
    valued=frozenset({"--limit", "--in"}),
)


@dataclass(frozen=True)
class Item:
    """One evidence line: its file, date, kind, and the title or excerpt to show."""

    path: str
    date: str
    kind: str
    text: str


def run(words: Sequence[str]) -> int:
    """Run kb recall and print its answer."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if not parsed.words:
        raise SPEC.usage_error()
    limit = args.positive_int(parsed.values.get("--limit", str(DEFAULT_LIMIT)), "--limit")
    context = load(os.environ, sys.platform, Path.home())
    scope = _scope(context, parsed.values.get("--in"))
    sys.stdout.write(answer(context, parsed.words, limit, scope))
    return 0


def answer(context: Context, words: Sequence[str], limit: int, scope: str | None) -> str:
    """The full text of an answer to a query, with its trailing lines."""
    terms = search.query_terms(words)
    documents = _curated(context, scope)
    pairs = [
        (document, candidate)
        for document in documents
        for candidate in search.article_candidates(document)
    ]
    hits = search.rank([candidate.unit for _, candidate in pairs], terms)
    if hits:
        return _with_results(context, [pairs[hit.index] for hit in hits], limit, terms, scope)
    query = " ".join(words)
    items = _ranked(_evidence(context, scope, (PENDING, ARCHIVED, *QUESTIONS)), terms)
    head = f'No curated knowledge matches "{query}".'
    if not items:
        return head + "\n"
    listing = ["Evidence:", *_evidence_lines(items[:FOLLOW_UP])]
    return "\n".join([head, *listing, READ_WITH]) + "\n"


def _with_results(
    context: Context,
    results: Sequence[tuple[Document, search.Candidate]],
    limit: int,
    terms: Sequence[str],
    scope: str | None,
) -> str:
    blocks = [
        _result_block(context, document, candidate) for document, candidate in results[:limit]
    ]
    tail: list[str] = []
    follow = results[limit : limit + FOLLOW_UP]
    if follow:
        tail.append("Also relevant:")
        tail.extend(
            f"  {document.path}#{candidate.fragment} | {candidate.heading}"
            for document, candidate in follow
        )
    uncurated = _ranked(_evidence(context, scope, (PENDING,)), terms)[:FOLLOW_UP]
    if uncurated:
        tail.append("Uncurated (pending, not yet verified):")
        tail.extend(f"  {item.path} | {item.date} | {item.text}" for item in uncurated)
    tail.append(READ_WITH)
    return "\n".join(blocks) + "\n" + "\n".join(tail) + "\n"


def _result_block(context: Context, document: Document, candidate: search.Candidate) -> str:
    section = None if candidate.fragment == "top" else document.section(candidate.fragment)
    lines = document.top_lines() if section is None else document.section_lines(section)
    head = locators.header(
        f"{document.path}#{candidate.fragment}",
        candidate.heading,
        freshness.status(document, section, context.today),
        len(document.items("sources", section)),
    )
    return locators.block(head, lines)


def _scope(context: Context, value: str | None) -> str | None:
    if value is None:
        return None
    relpath = corpus.resolve_path(context.root, value, WHO)
    if relpath is None:
        raise KbError(f"{WHO}: no such path: {value}")
    return relpath


def _in_scope(relpath: str, scope: str | None) -> bool:
    return scope is None or relpath == scope or relpath.startswith(scope + "/")


def _curated(context: Context, scope: str | None) -> list[Document]:
    paths = [
        path
        for directory in ("knowledge", "sources")
        for path in corpus.markdown_files(context.root, directory)
    ]
    return [
        corpus.read_document(context.root, path) for path in sorted(paths) if _in_scope(path, scope)
    ]


def _evidence(
    context: Context, scope: str | None, directories: Sequence[str]
) -> list[tuple[str, Document]]:
    paths = [
        path for directory in directories for path in corpus.markdown_files(context.root, directory)
    ]
    return [
        (path, corpus.read_document(context.root, path)) for path in paths if _in_scope(path, scope)
    ]


def _ranked(evidence: Sequence[tuple[str, Document]], terms: Sequence[str]) -> list[Item]:
    """Evidence items that qualify: best score first, then newest, then by path."""
    units = [search.evidence_unit(document) for _, document in evidence]
    hits = search.rank(units, terms)
    hits = sorted(hits, key=lambda hit: evidence[hit.index][0])
    hits = sorted(hits, key=lambda hit: _date(evidence[hit.index][1]), reverse=True)
    hits = sorted(hits, key=lambda hit: hit.score, reverse=True)
    items = []
    for hit in hits[: 2 * FOLLOW_UP]:
        path, document = evidence[hit.index]
        kind = _kind(path, document)
        items.append(Item(path, _date(document), kind, _text(kind, document, terms)))
    return items[:FOLLOW_UP] if items else []


def _evidence_lines(items: Sequence[Item]) -> list[str]:
    """Evidence lines with their columns aligned to the widest entry in the block."""
    path_width = max(len(item.path) for item in items)
    kind_width = max(len(item.kind) for item in items)
    return [
        f"  {item.path.ljust(path_width)} | {item.date} | {item.kind.ljust(kind_width)} | {item.text}"
        for item in items
    ]


def _kind(path: str, document: Document) -> str:
    if path.startswith("questions/open/"):
        return "open question"
    if path.startswith("questions/resolved/"):
        return "resolved question"
    if document.scalar("source") == "session-transcript":
        return "transcript"
    return "observation"


def _date(document: Document) -> str:
    created = (document.scalar("created") or "")[:10]
    return created if parse_date(created) else ""


def _text(kind: str, document: Document, terms: Sequence[str]) -> str:
    if kind == "transcript":
        return search.excerpt(document.prose(document.body_start, len(document.lines)), terms)
    return search.clip(locators.display_title(document), TITLE_WIDTH)

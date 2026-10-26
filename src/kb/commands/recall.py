"""kb recall: the curated sections that answer a query, and the evidence behind them.

Curated knowledge is knowledge/ and sources/. Pending observations are
searched on every call and listed as uncurated beside any curated results.
When no curated section matches, the archived observations and the questions
are searched too, and the best of them are listed as evidence.
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
        "Find the curated sections that answer QUERY, each with its header line. The first N\n"
        "sections print in full (default 3); the next few are listed. Pending observations\n"
        "that match are listed as uncurated. When no section matches, the observations and\n"
        "questions that do match are listed as evidence. --in PATH limits the search to a\n"
        "file or directory."
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
    """The text of the answer to a query."""
    terms = search.query_terms(words)
    results = _ranked(context.root, words, scope)
    if not results:
        items = _rank_evidence(
            _evidence(context.root, scope, (PENDING, ARCHIVED, *QUESTIONS)), terms, FOLLOW_UP
        )
        head = f'No curated knowledge matches "{" ".join(words)}".'
        if not items:
            return head + "\n"
        return "\n".join([head, "Evidence:", *_evidence_lines(items), READ_WITH]) + "\n"
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
    uncurated = _rank_evidence(_evidence(context.root, scope, (PENDING,)), terms, FOLLOW_UP)
    if uncurated:
        tail.append("Uncurated (pending, not yet verified):")
        tail.extend(f"  {item.path} | {item.date} | {item.text}" for item in uncurated)
    tail.append(READ_WITH)
    return "\n".join(blocks) + "\n" + "\n".join(tail) + "\n"


def ranked_locators(root: Path, words: Sequence[str], scope: str | None = None) -> list[str]:
    """The curated locators that qualify for a query, best first. The evaluation uses this."""
    return [
        f"{document.path}#{candidate.fragment}"
        for document, candidate in _ranked(root, words, scope)
    ]


def _ranked(
    root: Path, words: Sequence[str], scope: str | None
) -> list[tuple[Document, search.Candidate]]:
    """The curated units that qualify for a query, best first."""
    pairs = [
        (document, candidate)
        for document in _curated(root, scope)
        for candidate in search.article_candidates(document)
    ]
    hits = search.rank([candidate.unit for _, candidate in pairs], search.query_terms(words))
    return [pairs[hit.index] for hit in hits]


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


def _curated(root: Path, scope: str | None) -> list[Document]:
    paths = [
        path
        for directory in ("knowledge", "sources")
        for path in corpus.markdown_files(root, directory)
    ]
    return [corpus.read_document(root, path) for path in sorted(paths) if _in_scope(path, scope)]


def _evidence(
    root: Path, scope: str | None, directories: Sequence[str]
) -> list[tuple[str, Document]]:
    paths = [path for directory in directories for path in corpus.markdown_files(root, directory)]
    return [(path, corpus.read_document(root, path)) for path in paths if _in_scope(path, scope)]


def _rank_evidence(
    evidence: Sequence[tuple[str, Document]], terms: Sequence[str], limit: int
) -> list[Item]:
    """Up to limit evidence items that qualify: best score, then newest, then by path."""
    units = [search.evidence_unit(document) for _, document in evidence]
    hits = search.rank(units, terms)
    hits = sorted(hits, key=lambda hit: evidence[hit.index][0])
    hits = sorted(hits, key=lambda hit: _date(evidence[hit.index][1]), reverse=True)
    hits = sorted(hits, key=lambda hit: hit.score, reverse=True)
    items = []
    for hit in hits[:limit]:
        path, document = evidence[hit.index]
        kind = _kind(path, document)
        items.append(Item(path, _date(document), kind, _text(kind, document, terms)))
    return items


def _evidence_lines(items: Sequence[Item]) -> list[str]:
    """Evidence lines with each column padded to its widest entry."""
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
    """Transcripts show their best matching line, since their titles are generic."""
    if kind == "transcript":
        return search.excerpt(document.prose(document.body_start, len(document.lines)), terms)
    return search.clip(locators.display_title(document), TITLE_WIDTH)

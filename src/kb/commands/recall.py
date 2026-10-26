"""kb recall: the curated sections that answer a query, each with its header line.

Curated knowledge is knowledge/ and sources/. A query that matches no curated
section prints one line saying so.
"""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from kb import args, corpus, freshness, locators, search
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError
from kb.model import Document

WHO = "kb recall"
DEFAULT_LIMIT = 3
FOLLOW_UP = 5
READ_WITH = "Read with: kb read <locator>"
SPEC = Spec(
    usage="recall QUERY... [--limit N] [--in PATH]",
    summary=(
        "Find the curated sections that answer QUERY, each with its header line. The first N\n"
        "sections print in full (default 3); the next few are listed. --in PATH limits the\n"
        "search to a file or directory."
    ),
    valued=frozenset({"--limit", "--in"}),
)


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
    pairs = [
        (document, candidate)
        for document in _curated(context, scope)
        for candidate in search.article_candidates(document)
    ]
    hits = search.rank([candidate.unit for _, candidate in pairs], terms)
    if not hits:
        return f'No curated knowledge matches "{" ".join(words)}".\n'
    results = [pairs[hit.index] for hit in hits]
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


def _curated(context: Context, scope: str | None) -> list[Document]:
    paths = [
        path
        for directory in ("knowledge", "sources")
        for path in corpus.markdown_files(context.root, directory)
    ]
    return [
        corpus.read_document(context.root, path)
        for path in sorted(paths)
        if scope is None or path == scope or path.startswith(scope + "/")
    ]

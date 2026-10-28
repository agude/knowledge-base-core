"""kb recall: curated answers, matching open questions, and the evidence behind them.

Curated knowledge is knowledge/ and sources/. Pending observations and open
questions are searched beside curated results. When no curated section
matches, archived observations and resolved questions are searched too.
Addressable harvested messages use message locators; other matches use files.
"""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from kb import areas, args, corpus, evidence, freshness, locators, search
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError
from kb.model import Document

WHO = "kb recall"
DEFAULT_LIMIT = 3
FOLLOW_UP = 5
READ_WITH = "Read with: kb read <locator>"
PENDING = "observations/pending"
ARCHIVED = "observations/archived"
OPEN_QUESTIONS = "questions/open"
ALL_QUESTIONS = (OPEN_QUESTIONS, "questions/resolved")
SPEC = Spec(
    usage="recall QUERY... [--limit N] [--in PATH]",
    summary=(
        "Find the curated sections that answer QUERY, each with its header line. The first N\n"
        "sections print in full (default 3); the next few are listed. Pending observations\n"
        "and matching open questions are listed as uncurated. Without a curated match, pending\n"
        "and archived observations plus open and resolved questions are listed as evidence.\n"
        "Addressable harvested messages use message locators. --in PATH scopes curated files\n"
        "and observation storage paths; questions under knowledge/ or sources/ match by context."
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
    results = _ranked(context.root, words, scope)
    if not results:
        items = _matching_evidence(
            context,
            words,
            scope,
            (PENDING, ARCHIVED, *ALL_QUESTIONS),
            FOLLOW_UP,
        )
        questions = matching_open_questions(context, words, scope, candidates=items)
        question_paths = {item.path for item in questions}
        items = [
            item for item in items if item.kind != "open-question" or item.path in question_paths
        ]
        head = f'No curated knowledge matches "{" ".join(words)}".'
        if not items:
            return head + "\n"
        return head + "\n" + evidence.format_results(" ".join(words), items)
    blocks = [
        section_block(context, document, candidate) for document, candidate in results[:limit]
    ]
    tail: list[str] = []
    follow = results[limit : limit + FOLLOW_UP]
    if follow:
        tail.append("Also relevant:")
        tail.extend(
            f"  {document.path}#{candidate.fragment} | {candidate.heading}"
            for document, candidate in follow
        )
    uncurated = _matching_evidence(
        context,
        words,
        scope,
        (PENDING, OPEN_QUESTIONS),
        FOLLOW_UP,
    )
    questions = matching_open_questions(context, words, scope, candidates=uncurated)
    question_paths = {item.path for item in questions}
    uncurated = [
        item for item in uncurated if item.kind != "open-question" or item.path in question_paths
    ]
    if uncurated:
        tail.append("Uncurated (pending, not yet verified):")
        tail.extend(evidence.format_rows(uncurated))
    tail.append(READ_WITH)
    return "\n".join(blocks) + "\n" + "\n".join(tail) + "\n"


def ranked_locators(root: Path, words: Sequence[str], scope: str | None = None) -> list[str]:
    """The curated locators that qualify for a query, best first. The evaluation uses this."""
    return [
        f"{document.path}#{candidate.fragment}"
        for document, candidate in _ranked(root, words, scope)
    ]


def matching_sections(
    context: Context,
    words: Sequence[str],
    limit: int = DEFAULT_LIMIT,
    scope: str | None = None,
) -> list[str]:
    """The formatted, ranked curated sections that recall would show for a query."""
    return [
        section_block(context, document, candidate)
        for document, candidate in _ranked(context.root, words, scope)[:limit]
    ]


def matching_open_questions(
    context: Context,
    words: Sequence[str],
    scope: str | None = None,
    limit: int = FOLLOW_UP,
    *,
    candidates: Sequence[evidence.Item] | None = None,
    has_curated_matches: bool | None = None,
) -> list[evidence.Item]:
    """The open-question rows that occur in recall's bounded evidence matches."""
    if candidates is None:
        if has_curated_matches is None:
            has_curated_matches = bool(_ranked(context.root, words, scope))
        directories = (
            (PENDING, OPEN_QUESTIONS)
            if has_curated_matches
            else (PENDING, ARCHIVED, *ALL_QUESTIONS)
        )
        candidates = _matching_evidence(context, words, scope, directories, limit)
    return [item for item in candidates if item.kind == "open-question"][:limit]


def matching_open_question_rows(
    context: Context,
    words: Sequence[str],
    scope: str | None = None,
    *,
    has_curated_matches: bool | None = None,
) -> list[str]:
    """The question rows recall would show, retaining its shared column widths."""
    if has_curated_matches is None:
        has_curated_matches = bool(_ranked(context.root, words, scope))
    directories = (
        (PENDING, OPEN_QUESTIONS) if has_curated_matches else (PENDING, ARCHIVED, *ALL_QUESTIONS)
    )
    candidates = _matching_evidence(context, words, scope, directories, FOLLOW_UP)
    questions = matching_open_questions(context, words, scope, candidates=candidates)
    rows_by_path = {
        item.path: row
        for item, row in zip(candidates, evidence.format_rows(candidates), strict=True)
    }
    return [rows_by_path[item.path] for item in questions]


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


def section_block(context: Context, document: Document, candidate: search.Candidate) -> str:
    section = None if candidate.fragment == "top" else document.section(candidate.fragment)
    lines = document.top_lines() if section is None else document.section_lines(section)
    head = locators.header(
        f"{document.path}#{candidate.fragment}",
        candidate.heading,
        freshness.status(document, section, context.today),
        len(document.items("sources", section)),
    )
    return locators.block(head, lines)


def _matching_evidence(
    context: Context,
    words: Sequence[str],
    scope: str | None,
    directories: Sequence[str],
    limit: int,
) -> list[evidence.Item]:
    """Select the evidence rows recall uses for a query and its scope."""
    terms = search.query_terms(words)
    if not terms:
        return []
    return evidence.select(
        _evidence(context.root, scope, directories), terms, None, None, None, limit
    )


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
    match_context = scope is not None and areas.is_area_path(scope)
    paths = sorted(
        {
            path
            for directory in directories
            for path in corpus.markdown_files(root, directory)
            if _in_scope(path, scope) or (match_context and path.startswith("questions/"))
        }
    )
    documents = [(path, corpus.read_document(root, path)) for path in paths]
    if not match_context:
        return documents

    scope_area = areas.canonical_area(root, scope)
    selected: list[tuple[str, Document]] = []
    for path, document in documents:
        if not path.startswith("questions/"):
            selected.append((path, document))
            continue
        context_area = areas.canonical_area(root, document.scalar("context"))
        if (
            scope_area is not None
            and context_area is not None
            and areas.overlaps(context_area, scope_area)
        ):
            selected.append((path, document))
    return selected

"""kb recall: curated answers, matching open questions, and the evidence behind them.

Curated knowledge is knowledge/ and sources/. Pending observations and open
questions are searched beside curated results. When no curated section
matches, archived observations and resolved questions are searched too.
Addressable harvested messages use message locators; other matches use files.
"""

import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from kb import areas, args, corpus, evidence, freshness, locators, search, token_cache
from kb.args import Spec
from kb.context import Context, load
from kb.entries import Entry
from kb.errors import KbError
from kb.meta import ArticleMeta
from kb.model import Document

WHO = "kb recall"
DEFAULT_LIMIT = 3
FOLLOW_UP = 5
SESSION_ROWS = 3
SESSIONS_HEADING = "From sessions (raw, unverified, may be superseded):"
UNCURATED_HEADING = "Uncurated (pending, not yet verified):"
ALSO_HEADING = "Also relevant:"
NO_SESSIONS = "--no-sessions"
READ_WITH = "Read with: kb read <locator>"
PENDING = "observations/pending"
ARCHIVED = "observations/archived"
OPEN_QUESTIONS = "questions/open"
ALL_QUESTIONS = (OPEN_QUESTIONS, "questions/resolved")
SESSION_DIRECTORIES = (PENDING, ARCHIVED)
SPEC = Spec(
    usage="recall QUERY... [--limit N] [--in PATH] [--no-sessions]",
    summary=(
        "Find the curated sections that answer QUERY, each with its header line. The first N\n"
        "sections print in full (default 3); the next few are listed. Pending observations\n"
        "and matching open questions are listed as uncurated. Without a curated match, pending\n"
        "and archived observations plus open and resolved questions are listed as evidence.\n"
        "With a curated match, up to 3 matching session transcript rows follow under\n"
        '"From sessions", unless --no-sessions is given. Rows already listed as uncurated\n'
        "are left out.\n"
        "Addressable harvested messages use message locators. --in PATH scopes curated files\n"
        "and observation storage paths; questions under knowledge/ or sources/ match by context."
    ),
    valued=frozenset({"--limit", "--in"}),
    switches=frozenset({NO_SESSIONS}),
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
    sessions = NO_SESSIONS not in parsed.switches
    sys.stdout.write(answer(context, parsed.words, limit, scope, sessions=sessions))
    return 0


@dataclass(frozen=True)
class Selection:
    """The rows that recall shows for one query, before they are formatted.

    results are the curated sections that qualify, best first, and follow are the sections under
    "Also relevant". uncurated holds the rows under "Uncurated". sessions holds the rows under
    "From sessions", and it is empty when sessions is False. evidence holds the rows of the
    no-curated fallback. A selection with results has no evidence, and one without results has
    no uncurated, follow, or session rows.
    """

    results: list[tuple[Document, search.Candidate]]
    follow: list[tuple[Document, search.Candidate]]
    uncurated: list[evidence.Item]
    sessions: list[evidence.Item]
    evidence: list[evidence.Item]


def select(
    context: Context,
    words: Sequence[str],
    scope: str | None,
    limit: int,
    *,
    sessions: bool = True,
) -> Selection:
    """Choose the rows that recall shows for a query. The cache is loaded once for the selection.

    Without a curated match, the evidence rows are the fallback, and nothing else is selected.
    """
    documents = corpus.Documents(context.root)
    results = _ranked(context.root, words, scope)
    if not results:
        empty_directories: tuple[str, ...] = (PENDING, ARCHIVED, *ALL_QUESTIONS)
        loaded = _loaded(context.root, documents, words, empty_directories)
        items = _matching_evidence(
            context, words, scope, empty_directories, FOLLOW_UP, documents, loaded
        )
        return Selection([], [], [], [], items)
    # A curated answer lists only the directories its blocks read, so a block that is not shown
    # does not list the archive.
    directories = (PENDING, OPEN_QUESTIONS, ARCHIVED) if sessions else (PENDING, OPEN_QUESTIONS)
    loaded = _loaded(context.root, documents, words, directories)
    follow = results[limit : limit + FOLLOW_UP]
    uncurated = _uncurated(context, words, scope, documents, loaded)
    rows: list[evidence.Item] = []
    if sessions:
        # A session row that Uncurated already shows is left out, so ask for enough extra rows.
        shown = {item.path for item in uncurated}
        found = session_rows(context, words, scope, documents, SESSION_ROWS + len(shown), loaded)
        rows = [row for row in found if row.path not in shown][:SESSION_ROWS]
    return Selection(results, follow, uncurated, rows, [])


def answer(
    context: Context,
    words: Sequence[str],
    limit: int,
    scope: str | None,
    *,
    sessions: bool = True,
) -> str:
    """The text of the answer to a query. Each file is parsed at most once for the answer.

    sessions adds the From sessions block after the curated results. It is not printed
    when no curated section matches, because the evidence list already holds the sessions.
    """
    chosen = select(context, words, scope, limit, sessions=sessions)
    if not chosen.results:
        head = f'No curated knowledge matches "{" ".join(words)}".'
        if not chosen.evidence:
            return head + "\n"
        return head + "\n" + evidence.format_results(" ".join(words), chosen.evidence)
    blocks = [
        section_block(context, document, candidate)
        for document, candidate in chosen.results[:limit]
    ]
    tail: list[str] = []
    if chosen.follow:
        tail.append(ALSO_HEADING)
        tail.extend(
            f"  {document.path}#{candidate.fragment} | {candidate.heading}"
            for document, candidate in chosen.follow
        )
    if chosen.uncurated:
        tail.append(UNCURATED_HEADING)
        tail.extend(evidence.format_rows(chosen.uncurated))
    if chosen.sessions:
        tail.extend(_session_lines(chosen.sessions))
    tail.append(READ_WITH)
    return "\n".join(blocks) + "\n" + "\n".join(tail) + "\n"


def ranked_locators(root: Path, words: Sequence[str], scope: str | None = None) -> list[str]:
    """The curated locators that qualify for a query, best first. The evaluation uses this."""
    return ranked_locators_for_queries(root, [words], scope)[0]


def ranked_locators_for_queries(
    root: Path,
    queries: Sequence[Sequence[str]],
    scope: str | None = None,
    limit: int | None = None,
) -> list[list[str]]:
    """Rank several queries against one parsed curated snapshot, in recall order."""
    if not queries:
        return []
    pairs = _candidate_pairs(root, scope)
    units = [candidate.unit for _, candidate in pairs]
    results: list[list[str]] = []
    for words in queries:
        hits = search.rank(units, search.query_terms(words))
        if limit is not None:
            hits = hits[:limit]
        results.append(
            [f"{pairs[hit.index][0].path}#{pairs[hit.index][1].fragment}" for hit in hits]
        )
    return results


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
    documents: corpus.Documents | None = None,
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
        shared = corpus.Documents(context.root) if documents is None else documents
        candidates = _matching_evidence(
            context,
            words,
            scope,
            directories,
            limit,
            shared,
            _loaded(context.root, shared, words, directories),
        )
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
    documents = corpus.Documents(context.root)
    candidates = _matching_evidence(
        context,
        words,
        scope,
        directories,
        FOLLOW_UP,
        documents,
        _loaded(context.root, documents, words, directories),
    )
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
    pairs = _candidate_pairs(root, scope)
    hits = search.rank([candidate.unit for _, candidate in pairs], search.query_terms(words))
    return [pairs[hit.index] for hit in hits]


def _candidate_pairs(root: Path, scope: str | None) -> list[tuple[Document, search.Candidate]]:
    """Build the ordered article candidate snapshot shared by ranking helpers."""
    return [
        (document, candidate)
        for document in _curated(root, scope)
        for candidate in search.article_candidates(document)
    ]


def section_block(context: Context, document: Document, candidate: search.Candidate) -> str:
    section = None if candidate.fragment == "top" else document.section(candidate.fragment)
    lines = document.top_lines() if section is None else document.section_lines(section)
    head = locators.header(
        f"{document.path}#{candidate.fragment}",
        candidate.heading,
        freshness.status(document, section, context.today),
        len(ArticleMeta.read(document, section).sources),
    )
    return locators.block(head, lines)


def _loaded(
    root: Path,
    documents: corpus.Documents,
    words: Sequence[str],
    directories: Sequence[str],
) -> dict[str, Entry]:
    """The cache entries of the evidence files in directories, loaded in one pass.

    Empty when the query has no terms, because nothing can match it.
    """
    if not search.query_terms(words):
        return {}
    paths = sorted(
        {path for directory in directories for path in corpus.markdown_files(root, directory)}
    )
    return token_cache.load(root, paths, documents)


def _matching_evidence(
    context: Context,
    words: Sequence[str],
    scope: str | None,
    directories: Sequence[str],
    limit: int,
    documents: corpus.Documents,
    loaded: Mapping[str, Entry],
) -> list[evidence.Item]:
    """Select the evidence rows recall uses for a query and its scope."""
    terms = search.query_terms(words)
    if not terms:
        return []
    return evidence.select(
        _evidence(context.root, scope, directories, loaded),
        terms,
        None,
        None,
        None,
        limit,
        documents.read,
    )


def _uncurated(
    context: Context,
    words: Sequence[str],
    scope: str | None,
    documents: corpus.Documents,
    loaded: Mapping[str, Entry],
) -> list[evidence.Item]:
    """The rows under Uncurated for a query: pending evidence and open questions.

    Every open question that the matching step returns is shown, so no question filter applies.
    """
    return _matching_evidence(
        context,
        words,
        scope,
        (PENDING, OPEN_QUESTIONS),
        FOLLOW_UP,
        documents,
        loaded,
    )


def session_rows(
    context: Context,
    words: Sequence[str],
    scope: str | None,
    documents: corpus.Documents,
    limit: int,
    loaded: Mapping[str, Entry] | None = None,
) -> list[evidence.Item]:
    """The best transcript rows for a query, from pending and archived harvests.

    This ranks every transcript row. The From sessions block takes its rows from here, after it
    leaves out the rows that Uncurated shows. loaded is the cache for the query, or None to load it.
    """
    terms = search.query_terms(words)
    if not terms:
        return []
    entries = (
        _loaded(context.root, documents, words, SESSION_DIRECTORIES) if loaded is None else loaded
    )
    return evidence.select(
        _evidence(context.root, scope, SESSION_DIRECTORIES, entries),
        terms,
        "transcript",
        None,
        None,
        limit,
        documents.read,
    )


def _session_lines(rows: Sequence[evidence.Item]) -> list[str]:
    """The From sessions heading and rows. Each row is locator | date | excerpt.

    An excerpt is at most search.EXCERPT_WIDTH characters.
    """
    width = max(len(row.path) for row in rows)
    lines = [SESSIONS_HEADING]
    for row in rows:
        date_text = row.date.isoformat() if row.date else ""
        lines.append(f"  {row.path.ljust(width)} | {date_text} | {row.text}")
    return lines


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
    root: Path,
    scope: str | None,
    directories: Sequence[str],
    loaded: Mapping[str, Entry],
) -> list[Entry]:
    """The cache entries of the evidence files in scope, in path order.

    loaded holds the entries of every file that recall may search, so no file is loaded here.
    """
    match_context = scope is not None and areas.is_area_path(scope)
    paths = sorted(
        {
            path
            for directory in directories
            for path in corpus.markdown_files(root, directory)
            if _in_scope(path, scope) or (match_context and path.startswith("questions/"))
        }
    )
    entries = [loaded[path] for path in paths if path in loaded]
    if not match_context:
        return entries

    scope_area = areas.canonical_area(root, scope)
    selected: list[Entry] = []
    for entry in entries:
        if not entry.path.startswith("questions/"):
            selected.append(entry)
            continue
        context_area = areas.canonical_area(root, entry.scalars.get("context"))
        if (
            scope_area is not None
            and context_area is not None
            and areas.overlaps(context_area, scope_area)
        ):
            selected.append(entry)
    return selected

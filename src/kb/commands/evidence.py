"""kb evidence: deliberately search observations, transcripts, and questions."""

import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from kb import args, corpus, dates, evidence, search, token_cache
from kb.args import Spec
from kb.context import Context, load
from kb.entries import Entry
from kb.errors import KbError

WHO = "evidence"
ALL_DIRECTORIES = (
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
)
DIRECTORIES_BY_KIND = {
    "observation": ALL_DIRECTORIES[:2],
    "transcript": ALL_DIRECTORIES[:2],
    "open-question": ("questions/open",),
    "resolved-question": ("questions/resolved",),
}
DEFAULT_LIMIT = 5
SPEC = Spec(
    usage="evidence QUERY... [--kind KIND] [--since DATE] [--until DATE] [--limit N]",
    summary=(
        "Search pending and archived observations, harvested transcripts, and open or resolved\n"
        "questions. Date bounds are inclusive. A matching harvested message uses its message\n"
        "date and locator when the transcript has addressable messages."
    ),
    valued=frozenset({"--kind", "--since", "--until", "--limit"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb evidence and print its selected evidence rows."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if not parsed.words:
        raise SPEC.usage_error()

    kind_filter = parsed.values.get("--kind")
    if kind_filter is not None and kind_filter not in evidence.KINDS:
        allowed = ", ".join(evidence.KINDS)
        raise KbError(f"{WHO}: --kind must be one of {allowed}")
    since = _date(parsed.values.get("--since"), "--since")
    until = _date(parsed.values.get("--until"), "--until")
    if since is not None and until is not None and since > until:
        raise KbError(f"{WHO}: --since must not be after --until")
    limit = args.positive_int(parsed.values.get("--limit", str(DEFAULT_LIMIT)), "--limit")

    try:
        context = load(os.environ, sys.platform, Path.home())
        documents = corpus.Documents(context.root)
        entries = _entries(context, kind_filter, documents)
    except KbError as error:
        raise KbError(f"{WHO}: {error}") from error

    terms = search.query_terms(parsed.words)
    items = evidence.select(
        entries,
        terms,
        kind_filter,
        since,
        until,
        limit,
        documents.read,
    )
    sys.stdout.write(evidence.format_results(" ".join(parsed.words), items))
    return 0


def _date(value: str | None, option: str) -> date | None:
    """A strict YYYY-MM-DD value from an optional date filter."""
    if value is None:
        return None
    parsed = dates.parse_date(value)
    if parsed is None:
        raise KbError(f"{WHO}: {option} must be YYYY-MM-DD")
    return parsed


def _entries(context: Context, kind_filter: str | None, documents: corpus.Documents) -> list[Entry]:
    """The cache entries of the selected evidence files, in content-relative path order."""
    directories = ALL_DIRECTORIES if kind_filter is None else DIRECTORIES_BY_KIND[kind_filter]
    paths = sorted(
        {
            path
            for directory in directories
            for path in corpus.markdown_files(context.root, directory)
        }
    )
    loaded = token_cache.load(context.root, paths, documents)
    return [loaded[path] for path in paths if path in loaded]

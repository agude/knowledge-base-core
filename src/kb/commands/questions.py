"""kb questions: list open questions, or include resolved questions."""

import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kb import areas, args, corpus, evidence, locators, search
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError

WHO = "questions"
OPEN = "questions/open"
RESOLVED = "questions/resolved"
DEFAULT_LIMIT = 20
READ_WITH = "Read with: kb read <locator>"
SPEC = Spec(
    usage="questions [--context PATH] [--all] [--limit N]",
    summary=(
        "List open questions, with context and a locator for each. --context includes questions "
        "about that area and its descendants; --all also includes resolved questions."
    ),
    valued=frozenset({"--context", "--limit"}),
    switches=frozenset({"--all"}),
)


@dataclass(frozen=True)
class Row:
    """The fields printed for one open or resolved question."""

    path: str
    created: date | None
    status: str
    context: str
    title: str


def run(words: Sequence[str]) -> int:
    """Run kb questions and print the selected question rows."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    limit = args.positive_int(parsed.values.get("--limit", str(DEFAULT_LIMIT)), "--limit")
    try:
        context = load(os.environ, sys.platform, Path.home())
        supplied_scope = parsed.values.get("--context")
        scope = _scope(context.root, supplied_scope)
        if supplied_scope is not None and scope is None:
            sys.stdout.write("No questions match.\n")
            return 0
        sys.stdout.write(answer(context, "--all" in parsed.switches, limit, scope))
    except KbError as error:
        message = str(error)
        if message.startswith(f"{WHO}:"):
            raise
        raise KbError(f"{WHO}: {message}") from error
    except (OSError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    return 0


def answer(context: Context, include_resolved: bool, limit: int, scope: str | None) -> str:
    """The formatted listing for all matching questions before the output limit."""
    rows = _rows(context.root, include_resolved, scope)
    if not rows:
        return "No questions match.\n"
    shown = rows[:limit]
    lines = [f"Questions: {len(rows)}; shown: {len(shown)}"]
    lines.extend(
        f"{row.path} | {row.created.isoformat() if row.created else ''} | {row.status} | "
        f"{row.context} | {row.title}"
        for row in shown
    )
    lines.append(READ_WITH)
    return "\n".join(lines) + "\n"


def _scope(root: Path, value: str | None) -> str | None:
    """Validate a supplied context and resolve it, retaining safe missing areas."""
    if value is None:
        return None
    areas.for_storage(root, value, WHO)
    return areas.canonical_area(root, value)


def _rows(root: Path, include_resolved: bool, scope: str | None) -> list[Row]:
    """Read selected question documents once, filter, and sort by date then path."""
    directories = (OPEN, RESOLVED) if include_resolved else (OPEN,)
    paths = sorted(
        {path for directory in directories for path in corpus.markdown_files(root, directory)}
    )
    rows = []
    for path in paths:
        document = corpus.read_document(root, path)
        context_area = areas.canonical_area(root, document.scalar("context"))
        if scope is not None and not _within(context_area, scope):
            continue
        raw_context = document.scalar("context")
        rows.append(
            Row(
                path=path,
                created=evidence.created_date(document),
                status="resolved" if path.startswith(f"{RESOLVED}/") else "open",
                context=raw_context
                if context_area is not None and raw_context is not None
                else "-",
                title=search.clip(locators.display_title(document), evidence.TITLE_WIDTH),
            )
        )
    return sorted(rows, key=_sort_key)


def _within(context_area: str | None, scope: str) -> bool:
    """Whether a normalized question context equals or descends from scope."""
    return context_area is not None and (
        context_area == scope or context_area.startswith(scope + "/")
    )


def _sort_key(row: Row) -> tuple[bool, int, str]:
    """Newest valid date first, invalid dates last, then content-relative path."""
    return (row.created is None, -row.created.toordinal() if row.created else 0, row.path)

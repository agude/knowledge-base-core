"""Read-only usage report for kb calls in the raw Claude Code and Codex session stores.

python -m kb.usage [--list] [--claude-root PATH] [--codex-root PATH]

Each kb recall output is parsed by its block structure into the locators it shows, tagged
curated or session. A recall made before the From sessions block shipped has no block, and it
is tagged pre-block. Every metric is counted per ISO week of the event's own timestamp.
Nothing is written. Query text is printed only by --list, which is for hand checking.
"""

import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from kb.hosts import claude, codex
from kb.transcripts import KbCall, Store

# The From sessions block shipped in commit a739708 (committer 2026-11-01T20:32:06-08:00).
# A recall before this instant that shows no block is tagged pre-block.
SESSION_BLOCK_SINCE = datetime(2026, 11, 2, 4, 32, 6, tzinfo=UTC)
SESSIONS_HEADING = "From sessions (raw, unverified, may be superseded):"
UNCURATED_HEADING = "Uncurated (pending, not yet verified):"
EVIDENCE_HEADING = "Evidence:"
ALSO_HEADING = "Also relevant:"
READ_WITH = "Read with:"
NO_MATCH = "No curated knowledge matches"
CURATED_ROW = "  "
UNKNOWN_WEEK = "unknown"
COLUMNS = (
    "week",
    "recalls",
    "no_output",
    "with_session_row",
    "session_row_reads",
    "reads_after_no_curated",
    "evidence_after_recall",
    "gap_after_recall",
    "mean_chars",
)


@dataclass(frozen=True)
class Shown:
    """One locator a recall printed, tagged by the block it appeared in."""

    locator: str
    tag: str  # curated, session, uncurated, or evidence


@dataclass(frozen=True)
class RecallView:
    """The locators one recall output shows, and whether it has a From sessions block."""

    shown: tuple[Shown, ...]
    no_match: bool
    block: bool

    @property
    def curated(self) -> tuple[str, ...]:
        return tuple(item.locator for item in self.shown if item.tag == "curated")

    @property
    def sessions(self) -> tuple[str, ...]:
        return tuple(item.locator for item in self.shown if item.tag == "session")


def parse_recall(output: str) -> RecallView:
    """The locators in a kb recall output, tagged by block.

    Curated section headers and Also relevant rows are curated. Rows under the From sessions
    heading are session. Uncurated and Evidence rows are tagged by their heading.
    """
    shown: list[Shown] = []
    tag = "section"
    block = False
    no_match = False
    for line in output.splitlines():
        if line == SESSIONS_HEADING:
            tag, block = "session", True
        elif line.startswith(UNCURATED_HEADING):
            tag = "uncurated"
        elif line == EVIDENCE_HEADING:
            tag = "evidence"
        elif line == ALSO_HEADING:
            tag = "also"
        elif line.startswith(READ_WITH):
            break
        elif line.startswith(NO_MATCH):
            no_match = True
        elif tag == "section":
            head = line.split(" | ", 1)[0]
            if " | " in line and "#" in head and " " not in head:
                shown.append(Shown(head, "curated"))
        elif tag == "also":
            if line.startswith(CURATED_ROW):
                shown.append(Shown(line[len(CURATED_ROW) :].split(" | ", 1)[0].strip(), "curated"))
        elif tag in ("session", "uncurated", "evidence") and line.startswith(CURATED_ROW):
            shown.append(Shown(line[len(CURATED_ROW) :].split(" | ", 1)[0].strip(), tag))
    return RecallView(tuple(shown), no_match, block)


def week_of(moment: datetime | None) -> str:
    """The ISO week of a timestamp, as YYYY-Www in UTC, or UNKNOWN_WEEK."""
    if moment is None:
        return UNKNOWN_WEEK
    year, week, _weekday = moment.astimezone(UTC).isocalendar()
    return f"{year}-W{week:02d}"


def recall_status(call: KbCall, view: RecallView | None) -> str:
    """How one recall is tagged: no output, no match, block with rows, or the no-row cases."""
    if view is None:
        return "no-output"
    if view.no_match:
        return "no-curated-match"
    if view.block and view.sessions:
        return "session-rows"
    if call.timestamp is not None and call.timestamp < SESSION_BLOCK_SINCE:
        return "pre-block"
    return "no-session-rows"


@dataclass
class _Entry:
    """One recall for --list: its header line, and the calls later in its session."""

    head: str
    later: list[str] = field(default_factory=list)


@dataclass
class _Session:
    """Per-session state, in the order the calls ran."""

    entry: _Entry | None = None
    session_rows: dict[str, bool] = field(default_factory=dict)


@dataclass
class Week:
    """The counts of one ISO week."""

    recalls: int = 0
    no_output: int = 0
    with_session_row: int = 0
    session_row_reads: int = 0
    reads_after_no_curated: int = 0
    evidence_after_recall: int = 0
    gap_after_recall: int = 0
    recall_chars: int = 0
    recall_outputs: int = 0

    def mean_chars(self) -> str:
        if self.recall_outputs == 0:
            return "n/a"
        return str(round(self.recall_chars / self.recall_outputs))


@dataclass
class Report:
    """The weekly counts, the recall tags, and each recall with its later calls, for --list."""

    weeks: dict[str, Week] = field(default_factory=dict)
    tags: Counter[str] = field(default_factory=Counter)
    entries: list[_Entry] = field(default_factory=list)


def analyze(calls: Sequence[KbCall]) -> Report:
    """Count the metrics over calls in the order they ran. A later call in the same session
    may refer to an earlier recall, so the state is kept per session_id."""
    report = Report()
    sessions: dict[str | None, _Session] = {}
    for call in calls:
        state = sessions.setdefault(call.session_id, _Session())
        week = report.weeks.setdefault(week_of(call.timestamp), Week())
        if call.subcommand == "recall":
            view = parse_recall(call.output) if call.output is not None else None
            status = recall_status(call, view)
            report.tags[status] += 1
            week.recalls += 1
            if view is None:
                week.no_output += 1
            else:
                week.recall_outputs += 1
                week.recall_chars += len(call.output or "")
                if view.sessions:
                    week.with_session_row += 1
            if view is not None:
                state.session_rows = {locator: bool(view.curated) for locator in view.sessions}
            state.entry = _Entry(_recall_head(call, view, status))
            report.entries.append(state.entry)
        elif call.subcommand == "read":
            matched = [arg for arg in call.arguments if arg in state.session_rows]
            if matched:
                week.session_row_reads += 1
                if any(not state.session_rows[arg] for arg in matched):
                    week.reads_after_no_curated += 1
            _later(state, call)
        elif call.subcommand == "evidence":
            if state.entry is not None:
                week.evidence_after_recall += 1
            _later(state, call)
        elif call.subcommand == "gap":
            if state.entry is not None:
                week.gap_after_recall += 1
            _later(state, call)
    return report


def _later(state: _Session, call: KbCall) -> None:
    """Add a call to the recall it follows in its session, for --list."""
    if state.entry is None:
        return
    when = call.timestamp.isoformat() if call.timestamp else UNKNOWN_WEEK
    state.entry.later.append(f"{call.subcommand} {' '.join(call.arguments)}  ({when})")


def _recall_head(call: KbCall, view: RecallView | None, status: str) -> str:
    """One recall for --list: its time, session, query, tag, and the locators it showed."""
    when = call.timestamp.isoformat() if call.timestamp else UNKNOWN_WEEK
    shown = (
        ", ".join(f"{item.locator} [{item.tag}]" for item in view.shown) if view else "(no output)"
    )
    return (
        f"recall {when} session={call.session_id} status={status}\n"
        f"    query: {' '.join(call.arguments)}\n"
        f"    shown: {shown}"
    )


def weekly_rows(report: Report) -> list[list[str]]:
    """The weekly table, one row per week, oldest first, with the unknown week last."""
    keys = sorted(key for key in report.weeks if key != UNKNOWN_WEEK)
    if UNKNOWN_WEEK in report.weeks:
        keys.append(UNKNOWN_WEEK)
    rows: list[list[str]] = []
    for key in keys:
        week = report.weeks[key]
        rows.append(
            [
                key,
                str(week.recalls),
                str(week.no_output),
                str(week.with_session_row),
                str(week.session_row_reads),
                str(week.reads_after_no_curated),
                str(week.evidence_after_recall),
                str(week.gap_after_recall),
                week.mean_chars(),
            ]
        )
    return rows


def _format_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    widths = [max(len(str(row[index])) for row in [header, *rows]) for index in range(len(header))]
    lines = ["  ".join(str(cell).ljust(width) for cell, width in zip(header, widths, strict=True))]
    for row in rows:
        lines.append(
            "  ".join(str(cell).ljust(width) for cell, width in zip(row, widths, strict=True))
        )
    return "\n".join(lines)


def store_summary(name: str, store: Store) -> str:
    """One host's store: files, unreadable count, and the span of its records."""
    first = store.first.date().isoformat() if store.first else "none"
    last = store.last.date().isoformat() if store.last else "none"
    return (
        f"{name}: {store.files} files, {store.unreadable} unreadable, "
        f"{len(store.calls)} kb calls, records {first} to {last}"
    )


def render(stores: Mapping[str, Store], report: Report) -> str:
    """The default output: store ranges, recall tags, and the weekly table."""
    lines = [store_summary(name, store) for name, store in stores.items()]
    lines.append("")
    lines.append(
        "recall tags: " + ", ".join(f"{key}={count}" for key, count in sorted(report.tags.items()))
    )
    lines.append("")
    lines.append(_format_table(COLUMNS, weekly_rows(report)))
    return "\n".join(lines) + "\n"


def render_list(report: Report) -> str:
    """The --list output: every recall, then the calls later in its session until the next recall."""
    lines: list[str] = []
    for entry in report.entries:
        lines.append(entry.head)
        lines.append("    later: " + ("; ".join(entry.later) if entry.later else "none"))
    return "\n".join(lines) + "\n"


def _calls(stores: Mapping[str, Store]) -> list[KbCall]:
    calls: list[KbCall] = []
    for store in stores.values():
        calls.extend(store.calls)
    return sorted(calls, key=lambda call: (call.timestamp is None, call.timestamp or UNKNOWN_EPOCH))


UNKNOWN_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _store_root(environ: Mapping[str, str], name: str, default: str) -> Path:
    value = environ.get(name, "")
    return Path(value).expanduser() if value else Path.home() / default


def main(argv: Iterable[str] | None = None) -> int:
    """Read the stores and print the report. Returns 0."""
    words = list(sys.argv[1:] if argv is None else argv)
    listing = "--list" in words
    roots = _roots(words, os.environ)
    stores = {
        "claude-code": claude.read_store(roots["claude-code"]),
        "codex": codex.read_store(roots["codex"]),
    }
    report = analyze(_calls(stores))
    sys.stdout.write(render_list(report) if listing else render(stores, report))
    return 0


def _roots(words: Sequence[str], environ: Mapping[str, str]) -> dict[str, Path]:
    """The Claude projects and Codex sessions roots, from flags or the host environment."""
    roots = {
        "claude-code": _store_root(environ, "CLAUDE_CONFIG_DIR", ".claude") / "projects",
        "codex": _store_root(environ, "CODEX_HOME", ".codex") / "sessions",
    }
    for flag, key in (("--claude-root", "claude-code"), ("--codex-root", "codex")):
        if flag in words:
            index = words.index(flag)
            roots[key] = Path(words[index + 1])
    return roots


if __name__ == "__main__":
    raise SystemExit(main())

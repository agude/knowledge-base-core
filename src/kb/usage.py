"""Read-only usage report for kb calls in the raw Claude Code and Codex session stores.

python -m kb.usage [--list] [--claude-root PATH] [--codex-root PATH]

Each kb recall output is parsed by its block structure into the locators it shows, tagged
curated or session. A recall whose output is not usable is counted as excluded, with its reason,
and it is not parsed, so missing data cannot read as zero session rows. A recall made before
the From sessions block shipped has no block, and it is tagged pre-block. Every metric is counted
per ISO week of the event's own timestamp. Nothing is written. Query text is printed only by
--list, which is for hand checking.
"""

import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from kb import args
from kb.commands import recall
from kb.errors import KbError
from kb.evidence import EVIDENCE_HEADING
from kb.hosts import claude, codex
from kb.transcripts import KbCall, Store

# The From sessions block shipped in commit a739708 (committer 2026-11-01T20:32:06-08:00).
# A recall before this instant that shows no block is tagged pre-block.
SESSION_BLOCK_SINCE = datetime(2026, 11, 2, 4, 32, 6, tzinfo=UTC)
SESSIONS_HEADING = recall.SESSIONS_HEADING
UNCURATED_HEADING = recall.UNCURATED_HEADING
ALSO_HEADING = recall.ALSO_HEADING
READ_WITH = recall.READ_WITH
NO_MATCH = "No curated knowledge matches"
CURATED_ROW = "  "
UNKNOWN_WEEK = "unknown"
UNKNOWN_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# Week fields that feed the mean and are not columns of their own.
PRIVATE_FIELDS = frozenset({"recall_chars", "recall_outputs"})
USAGE = "Usage: python -m kb.usage [--list] [--claude-root PATH] [--codex-root PATH]"
SUMMARY = (
    "Report kb call usage from the raw Claude Code and Codex session stores. Read-only.\n"
    "--list prints each recall with its later calls, for hand checking. It shows query text.\n"
    "The roots default to CLAUDE_CONFIG_DIR/projects and CODEX_HOME/sessions."
)
SPEC = args.Spec(
    usage="",
    summary=SUMMARY,
    valued=frozenset({"--claude-root", "--codex-root"}),
    switches=frozenset({"--list"}),
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
        elif line == UNCURATED_HEADING:
            tag = "uncurated"
        elif line == EVIDENCE_HEADING:
            tag = "evidence"
        elif line == ALSO_HEADING:
            tag = "also"
        elif line == READ_WITH:
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
    """How one recall is tagged: excluded with its reason, no match, block with rows, or no rows."""
    if view is None:
        return f"excluded-{call.excluded}"
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
    session_rows: set[str] = field(default_factory=set)


@dataclass
class Week:
    """The counts of one ISO week. Every field but the two private ones is a column."""

    recalls: int = 0
    recalls_excluded: int = 0
    no_output: int = 0
    with_session_row: int = 0
    session_row_reads: int = 0
    evidence_after_recall: int = 0
    gap_after_recall: int = 0
    recall_chars: int = 0
    recall_outputs: int = 0

    def mean_chars(self) -> str:
        if self.recall_outputs == 0:
            return "n/a"
        return str(round(self.recall_chars / self.recall_outputs))


def _counted_fields() -> tuple[str, ...]:
    """The Week fields that print as columns, in declaration order."""
    return tuple(field.name for field in fields(Week) if field.name not in PRIVATE_FIELDS)


COLUMNS = ("week", *_counted_fields(), "mean_chars")


@dataclass
class Report:
    """The weekly counts, the recall tags, the excluded recalls by reason, and each recall with
    its later calls, for --list."""

    weeks: dict[str, Week] = field(default_factory=dict)
    tags: Counter[str] = field(default_factory=Counter)
    excluded: Counter[str] = field(default_factory=Counter)
    entries: list[_Entry] = field(default_factory=list)


def analyze(calls: Sequence[KbCall]) -> Report:
    """Count the metrics over calls in the order they ran. A later call in the same session
    may refer to an earlier recall, so the state is kept per session_id.

    A recall with no usable output resets its session's rows, so a later read cannot match the
    rows of an earlier recall.
    """
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
            if call.excluded is not None:
                week.recalls_excluded += 1
                report.excluded[call.excluded] += 1
            if call.excluded == "missing":
                week.no_output += 1
            if view is None:
                state.session_rows = set()
            else:
                week.recall_outputs += 1
                week.recall_chars += len(call.output or "")
                if view.sessions:
                    week.with_session_row += 1
                state.session_rows = set(view.sessions)
            state.entry = _Entry(_recall_head(call, view, status))
            report.entries.append(state.entry)
        elif call.subcommand == "read":
            if any(arg in state.session_rows for arg in call.arguments):
                week.session_row_reads += 1
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
    if view is None:
        shown = f"(excluded: {call.excluded})"
    else:
        shown = ", ".join(f"{item.locator} [{item.tag}]" for item in view.shown)
    return (
        f"recall {when} session={call.session_id} status={status}\n"
        f"    query: {' '.join(call.arguments)}\n"
        f"    shown: {shown}"
    )


def weekly_rows(report: Report) -> list[list[str]]:
    """The weekly table, one row per week, oldest first, with the unknown week last.

    The counted columns come from the Week fields, the same source as COLUMNS.
    """
    keys = sorted(key for key in report.weeks if key != UNKNOWN_WEEK)
    if UNKNOWN_WEEK in report.weeks:
        keys.append(UNKNOWN_WEEK)
    names = [item.name for item in fields(Week) if item.name not in PRIVATE_FIELDS]
    rows: list[list[str]] = []
    for key in keys:
        week = report.weeks[key]
        rows.append([key, *(str(getattr(week, name)) for name in names), week.mean_chars()])
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


def _by_reason(counts: Mapping[str, int]) -> str:
    """The counts as key=value pairs in key order, or none."""
    return ", ".join(f"{key}={count}" for key, count in sorted(counts.items())) or "none"


def render(stores: Mapping[str, Store], report: Report) -> str:
    """The default output: store ranges, recall tags, excluded recalls, and the weekly table."""
    lines = [store_summary(name, store) for name, store in stores.items()]
    lines.append("")
    lines.append("recall tags: " + _by_reason(report.tags))
    lines.append("recall excluded by reason: " + _by_reason(report.excluded))
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


def _store_root(environ: Mapping[str, str], name: str, default: str) -> Path:
    value = environ.get(name, "")
    return Path(value).expanduser() if value else Path.home() / default


def _roots(values: Mapping[str, str], environ: Mapping[str, str]) -> dict[str, Path]:
    """The Claude projects and Codex sessions roots, from the flags or the host environment."""
    roots = {
        "claude-code": _store_root(environ, "CLAUDE_CONFIG_DIR", ".claude") / "projects",
        "codex": _store_root(environ, "CODEX_HOME", ".codex") / "sessions",
    }
    if "--claude-root" in values:
        roots["claude-code"] = Path(values["--claude-root"])
    if "--codex-root" in values:
        roots["codex"] = Path(values["--codex-root"])
    return roots


def main(argv: Iterable[str] | None = None) -> int:
    """Read the stores and print the report. Returns 0, or 1 for a usage error."""
    words = list(sys.argv[1:] if argv is None else argv)
    try:
        parsed = args.parse(SPEC, words)
        if parsed.help:
            sys.stdout.write(f"{USAGE}\n\n{SUMMARY}\n")
            return 0
        if parsed.words:
            raise KbError(f"Unexpected argument: {parsed.words[0]}\n{USAGE}")
        roots = _roots(parsed.values, os.environ)
    except KbError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    stores = {
        "claude-code": claude.read_store(roots["claude-code"]),
        "codex": codex.read_store(roots["codex"]),
    }
    report = analyze(_calls(stores))
    sys.stdout.write(render_list(report) if "--list" in parsed.switches else render(stores, report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

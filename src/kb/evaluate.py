"""Score retrieval against question sets.

A question set is a JSON file in the kb-retrieval-questions format, version 1.
Each case names a query, the locators that answer it (none when unanswerable),
and, for a current-state case, the superseded locators it must rank below.

A mode chooses which rows are scored:

- curated: the curated results of recall, best first.
- sessions: the transcript rows recall prints from sessions, best first. A
  row's locator names its best message (PATH#N), so a session label names the
  answering message.
- combined: the curated results, then the session rows, as recall prints them.

A set names the modes it is scored in with "modes" (default ["curated"]).
`just eval` scores each fixture set in curated mode. A mode given with explicit
paths scores those paths whatever their "modes" say.

Only the first 3 rows of each block count. A case passes in curated mode when
an expected locator is among the top 3 and no unanswerable case returns a
curated result. A session or combined case passes by the same rule over the
rows that mode shows. A current-state case also needs its current locator
shown above every superseded locator shown.

The verdict line for a set reads `acceptance: met`, or `acceptance: not met (<ids>)`
with the ids of the cases that fail. The exit status is 1 when any set is not
met, and 0 otherwise.
"""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kb import corpus, evidence
from kb.commands import recall
from kb.context import Context
from kb.errors import KbError

FORMAT = "kb-retrieval-questions"
VERSION = 1
TOP = 3
POOL = 10
CURATED = "curated"
SESSIONS = "sessions"
COMBINED = "combined"
MODES = (CURATED, SESSIONS, COMBINED)
DEFAULT_MODES = (CURATED,)
USAGE = "Usage: python -m kb.evaluate [--mode curated|sessions|combined] [QUESTIONS [CONTENT]]"


@dataclass(frozen=True)
class Case:
    """One question: its id, query, locators that answer it (none when unanswerable), and superseded ones."""

    id: str
    query: str
    expected: tuple[str, ...]
    requires_all: bool
    superseded: tuple[str, ...] = ()

    @property
    def unanswerable(self) -> bool:
        return not self.expected


@dataclass(frozen=True)
class Outcome:
    """A case with the curated locators and the session rows that recall returns for it, best first.

    sessions holds up to POOL rows, so a rank beyond the top 3 can be reported. Only the
    first TOP rows of each block are shown, and session_chars counts those shown rows.
    """

    case: Case
    ranked: tuple[str, ...]
    sessions: tuple[str, ...] = ()
    session_chars: int = 0

    @property
    def rank(self) -> int | None:
        """The 1-based position of the best expected locator, or None when none was returned."""
        position = _first_index(self.ranked, self.case.expected)
        return None if position is None else position + 1

    @property
    def hit(self) -> bool:
        return self.rank is not None and self.rank <= TOP

    @property
    def every_expected_in_top(self) -> bool:
        top = self.ranked[:TOP]
        return all(locator in top for locator in self.case.expected)

    @property
    def meets(self) -> bool:
        """The curated criterion for one case."""
        return self.passes(CURATED)

    def shown(self, mode: str) -> tuple[str, ...]:
        """The locators that a mode prints, in print order, each block cut to TOP rows."""
        if mode == SESSIONS:
            return self.sessions[:TOP]
        if mode == COMBINED:
            return (*self.ranked[:TOP], *self.sessions[:TOP])
        return self.ranked[:TOP]

    def passes(self, mode: str) -> bool:
        """The criterion for one case in one mode. See the module docstring."""
        shown = self.shown(mode)
        if self.case.unanswerable:
            return not shown
        current = _first_index(shown, self.case.expected)
        if current is None:
            return False
        superseded = _first_index(shown, self.case.superseded)
        return superseded is None or current < superseded


def load_set(path: Path) -> tuple[list[Case], tuple[str, ...]]:
    """The cases of a question set and the modes it is scored in. Raises KbError when invalid."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise KbError(f"{path}: {error}") from error
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        raise KbError(f"{path}: not a {FORMAT} version {VERSION} question set")
    modes = data.get("modes", list(DEFAULT_MODES))
    if not isinstance(modes, list) or not modes or not all(mode in MODES for mode in modes):
        raise KbError(f"{path}: modes must be a non-empty list of {', '.join(MODES)}")
    cases = [_case(path, raw) for raw in data.get("cases", [])]
    return cases, tuple(modes)


def _case(path: Path, raw: object) -> Case:
    if not isinstance(raw, dict):
        raise KbError(f"{path}: every case must be an object")
    expected = raw.get("expected", [])
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        raise KbError(f"{path}: expected must be a list of locators in case {raw.get('id')}")
    superseded = raw.get("superseded", [])
    if not isinstance(superseded, list) or not all(isinstance(item, str) for item in superseded):
        raise KbError(f"{path}: superseded must be a list of locators in case {raw.get('id')}")
    unanswerable = bool(raw.get("unanswerable", False))
    if unanswerable == bool(expected):
        state = "unanswerable" if unanswerable else "answerable"
        raise KbError(f"{path}: case {raw.get('id')} is {state} but lists {len(expected)} locators")
    return Case(
        id=str(raw.get("id")),
        query=str(raw.get("query", "")),
        expected=tuple(expected),
        requires_all=bool(raw.get("requires_all", False)),
        superseded=tuple(superseded),
    )


def run_cases(root: Path, cases: Sequence[Case], mode: str = CURATED) -> list[Outcome]:
    """Run each case's query through the rankings that the mode prints.

    Sessions mode ranks every transcript row, up to POOL. Combined mode uses the selection that
    recall prints, so its session rows are the From sessions rows, or the transcript rows of the
    no-curated fallback. A case gets its own corpus.Documents, so one query's parsed files are not
    kept for the next.
    """
    context = Context(root=root, today=date.today())
    outcomes: list[Outcome] = []
    for case in cases:
        words = [case.query]
        if mode == CURATED:
            outcomes.append(Outcome(case, tuple(recall.ranked_locators(root, words))))
            continue
        if mode == SESSIONS:
            rows = recall.session_rows(context, words, None, corpus.Documents(root), POOL)
            outcomes.append(Outcome(case, (), tuple(row.path for row in rows), _chars(rows[:TOP])))
            continue
        chosen = recall.select(context, words, None, recall.DEFAULT_LIMIT)
        ranked = tuple(
            f"{document.path}#{candidate.fragment}" for document, candidate in chosen.results
        )
        if chosen.results:
            rows = chosen.sessions
        else:
            rows = [row for row in chosen.evidence if row.kind == "transcript"]
        outcomes.append(Outcome(case, ranked, tuple(row.path for row in rows), _chars(rows[:TOP])))
    return outcomes


def _chars(rows: Sequence[evidence.Item]) -> int:
    return len("\n".join(evidence.format_rows(rows)))


def report(name: str, outcomes: Sequence[Outcome]) -> str:
    """One line per case, then the three curated totals."""
    lines = [name]
    for outcome in outcomes:
        case = outcome.case
        verdict = "pass" if outcome.passes(CURATED) else "FAIL"
        if case.unanswerable:
            detail = f"returned {len(outcome.ranked)}"
        else:
            detail = f"rank {outcome.rank if outcome.rank is not None else '-'}"
        lines.append(f"  {case.id:<40} {verdict:<4}  {detail}")
    answerable = [outcome for outcome in outcomes if not outcome.case.unanswerable]
    unanswerable = [outcome for outcome in outcomes if outcome.case.unanswerable]
    required = [outcome for outcome in answerable if outcome.case.requires_all]
    hits = sum(outcome.hit for outcome in answerable)
    empty = sum(not outcome.ranked for outcome in unanswerable)
    full = sum(outcome.every_expected_in_top for outcome in required)
    lines.append(
        f"answerable with an expected locator in the top {TOP}: "
        f"{hits} of {len(answerable)} ({_percent(hits, len(answerable))})"
    )
    lines.append(
        f"unanswerable with no curated result: "
        f"{empty} of {len(unanswerable)} ({_percent(empty, len(unanswerable))})"
    )
    if required:
        lines.append(
            f"requires_all with every expected locator in the top {TOP}: "
            f"{full} of {len(required)} ({_percent(full, len(required))})"
        )
    return "\n".join(lines) + "\n"


def report_for(name: str, outcomes: Sequence[Outcome], mode: str) -> str:
    """The report for one set in one mode. Curated mode keeps the original report."""
    if mode == CURATED:
        return report(name, outcomes)
    lines = [name]
    for outcome in outcomes:
        verdict = "pass" if outcome.passes(mode) else "FAIL"
        lines.append(f"  {outcome.case.id:<40} {verdict:<4}  {_detail(outcome, mode)}")
    lines.extend(_totals(outcomes, mode))
    return "\n".join(lines) + "\n"


def _detail(outcome: Outcome, mode: str) -> str:
    shown = outcome.shown(mode)
    if outcome.case.unanswerable:
        return f"returned {len(shown)}"
    session = _first_index(outcome.sessions, outcome.case.expected)
    session_rank = "-" if session is None else str(session + 1)
    if mode == SESSIONS:
        return f"rank {session_rank}"
    rank = "-" if outcome.rank is None else str(outcome.rank)
    return f"curated {rank}, session {session_rank}"


def _totals(outcomes: Sequence[Outcome], mode: str) -> list[str]:
    answerable = [outcome for outcome in outcomes if not outcome.case.unanswerable]
    unanswerable = [outcome for outcome in outcomes if outcome.case.unanswerable]
    current = [outcome for outcome in answerable if outcome.case.superseded]
    session_hits = [_in(outcome.sessions[:TOP], outcome.case.expected) for outcome in answerable]
    false_positives = sum(bool(outcome.sessions[:TOP]) for outcome in unanswerable)
    session_label = f"session rows with an expected locator in the top {TOP}"
    lines: list[str] = []
    if mode == COMBINED:
        curated_hits = [_in(outcome.ranked[:TOP], outcome.case.expected) for outcome in answerable]
        added = sum(
            not curated and session
            for curated, session in zip(curated_hits, session_hits, strict=True)
        )
        lines.append(
            _share(
                f"curated rows with an expected locator in the top {TOP}",
                sum(curated_hits),
                len(answerable),
            )
        )
        lines.append(_share(session_label, sum(session_hits), len(answerable)))
        lines.append(
            _share("added by the session block (curated top 3 missed it)", added, len(answerable))
        )
    else:
        lines.append(_share(session_label, sum(session_hits), len(answerable)))
    lines.append(
        _share(
            "session false positives (unanswerable with a row)", false_positives, len(unanswerable)
        )
    )
    if current:
        passed = sum(outcome.passes(mode) for outcome in current)
        lines.append(
            _share(
                "current-state cases with the current answer above the superseded one",
                passed,
                len(current),
            )
        )
    claims = sum(_in(outcome.shown(mode), outcome.case.superseded) for outcome in outcomes)
    lines.append(f"superseded claims shown: {claims}")
    chars = sum(outcome.session_chars for outcome in outcomes)
    lines.append(f"session characters per query: {_mean(chars, len(outcomes))}")
    return lines


def unmet(outcomes: Sequence[Outcome], mode: str = CURATED) -> list[str]:
    """The ids of the cases that do not meet the criterion in the mode."""
    return [outcome.case.id for outcome in outcomes if not outcome.passes(mode)]


def verdict(outcomes: Sequence[Outcome], mode: str = CURATED) -> str:
    """The acceptance verdict for one question set in one mode."""
    failed = unmet(outcomes, mode)
    if not failed:
        return "acceptance: met"
    return f"acceptance: not met ({', '.join(failed)})"


def main(argv: Sequence[str] | None = None) -> int:
    """Score the question sets named on the command line, or every fixture set for the mode.

    Returns 1 when a set does not meet the criterion, and 0 otherwise.
    """
    words = list(sys.argv[1:] if argv is None else argv)
    status = 0
    try:
        mode, positional = _options(words)
        for questions, content in _sets(positional, mode):
            cases, _modes = load_set(questions)
            outcomes = run_cases(content.resolve(), cases, mode)
            sys.stdout.write(report_for(questions.as_posix(), outcomes, mode))
            sys.stdout.write(verdict(outcomes, mode) + "\n\n")
            if unmet(outcomes, mode):
                status = 1
    except KbError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return status


def _options(words: Sequence[str]) -> tuple[str, list[str]]:
    """The mode and the positional arguments. --mode takes one value."""
    mode = CURATED
    positional: list[str] = []
    values = iter(words)
    for word in values:
        if word != "--mode":
            positional.append(word)
            continue
        value = next(values, None)
        if value is None or value not in MODES:
            raise KbError(USAGE)
        mode = value
    return mode, positional


def _sets(words: Sequence[str], mode: str) -> list[tuple[Path, Path]]:
    """Pairs of (question set, content root). Without arguments, every fixture set for the mode."""
    if len(words) > 2:
        raise KbError(USAGE)
    if words:
        questions = Path(words[0])
        content = Path(words[1]) if len(words) == 2 else questions.parent / "content"
        return [(questions, content)]
    found = sorted(Path("tests/fixtures").glob("*/questions.json"))
    if not found:
        raise KbError("no question sets under tests/fixtures")
    selected = [path for path in found if mode in load_set(path)[1]]
    if not selected:
        raise KbError(f"no question sets for mode {mode} under tests/fixtures")
    return [(path, path.parent / "content") for path in selected]


def _first_index(locators: Sequence[str], wanted: Sequence[str]) -> int | None:
    """The 0-based position of the first wanted locator that is listed, or None."""
    found = [locators.index(locator) for locator in wanted if locator in locators]
    return min(found, default=None)


def _in(locators: Sequence[str], wanted: Sequence[str]) -> bool:
    return any(locator in locators for locator in wanted)


def _share(label: str, count: int, whole: int) -> str:
    return f"{label}: {count} of {whole} ({_percent(count, whole)})"


def _percent(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{round(100 * part / whole)}%"


def _mean(total: int, count: int) -> str:
    return "n/a" if count == 0 else f"{round(total / count)}"


if __name__ == "__main__":
    raise SystemExit(main())

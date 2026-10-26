"""Score retrieval against question sets.

A question set is a JSON file in the kb-retrieval-questions format, version 1.
For each case, the report gives the rank of the first expected locator among
the curated results. Three totals follow: the share of answerable cases with
an expected locator in the top 3, the share of unanswerable cases that
returned no curated result, and the share of requires_all cases whose every
expected locator is in the top 3.

`just eval` scores every tests/fixtures/*/questions.json against the content
beside it. `just eval QUESTIONS [CONTENT]` scores one set.
"""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kb.commands import recall
from kb.errors import KbError

FORMAT = "kb-retrieval-questions"
VERSION = 1
TOP = 3
USAGE = "Usage: python -m kb.evaluate [QUESTIONS [CONTENT]]"


@dataclass(frozen=True)
class Case:
    """One question: its id, query, and the locators that answer it (none when unanswerable)."""

    id: str
    query: str
    expected: tuple[str, ...]
    requires_all: bool

    @property
    def unanswerable(self) -> bool:
        return not self.expected


@dataclass(frozen=True)
class Outcome:
    """A case with the curated locators that the search returned for it, best first."""

    case: Case
    ranked: tuple[str, ...]

    @property
    def rank(self) -> int | None:
        """The 1-based position of the best expected locator, or None when none was returned."""
        found = [
            index + 1 for index, locator in enumerate(self.ranked) if locator in self.case.expected
        ]
        return min(found, default=None)

    @property
    def hit(self) -> bool:
        return self.rank is not None and self.rank <= TOP

    @property
    def every_expected_in_top(self) -> bool:
        top = self.ranked[:TOP]
        return all(locator in top for locator in self.case.expected)

    @property
    def meets(self) -> bool:
        """The step 7 test for this case: a hit when answerable, no curated result when not."""
        return not self.ranked if self.case.unanswerable else self.hit


def load_cases(path: Path) -> list[Case]:
    """The cases of a question set. Raises KbError when the file is not in the format."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise KbError(f"{path}: {error}") from error
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        raise KbError(f"{path}: not a {FORMAT} version {VERSION} question set")
    return [_case(path, raw) for raw in data.get("cases", [])]


def _case(path: Path, raw: object) -> Case:
    if not isinstance(raw, dict):
        raise KbError(f"{path}: every case must be an object")
    expected = raw.get("expected", [])
    if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
        raise KbError(f"{path}: expected must be a list of locators in case {raw.get('id')}")
    unanswerable = bool(raw.get("unanswerable", False))
    if unanswerable == bool(expected):
        state = "unanswerable" if unanswerable else "answerable"
        raise KbError(f"{path}: case {raw.get('id')} is {state} but lists {len(expected)} locators")
    return Case(
        id=str(raw.get("id")),
        query=str(raw.get("query", "")),
        expected=tuple(expected),
        requires_all=bool(raw.get("requires_all", False)),
    )


def run_cases(root: Path, cases: Sequence[Case]) -> list[Outcome]:
    """Run each case's query through the same ranking that recall uses."""
    return [Outcome(case, tuple(recall.ranked_locators(root, [case.query]))) for case in cases]


def report(name: str, outcomes: Sequence[Outcome]) -> str:
    """One line per case, then the three totals."""
    lines = [name]
    for outcome in outcomes:
        case = outcome.case
        if case.unanswerable:
            verdict = "pass" if not outcome.ranked else "FAIL"
            detail = f"returned {len(outcome.ranked)}"
        else:
            verdict = "pass" if outcome.hit else "FAIL"
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


def unmet(outcomes: Sequence[Outcome]) -> list[str]:
    """The ids of the cases that fail the plan.md step 7 criterion as written."""
    return [outcome.case.id for outcome in outcomes if not outcome.meets]


def verdict(outcomes: Sequence[Outcome]) -> str:
    """The plan.md step 7 acceptance verdict for one question set."""
    failed = unmet(outcomes)
    if not failed:
        return "plan.md step 7 acceptance: met"
    return f"plan.md step 7 acceptance: not met ({', '.join(failed)})"


def main(argv: Sequence[str] | None = None) -> int:
    """Score the question sets named on the command line, or every set under tests/fixtures.

    Returns 1 when a set fails the plan.md step 7 criterion, and 0 otherwise.
    """
    words = list(sys.argv[1:] if argv is None else argv)
    status = 0
    try:
        for questions, content in _sets(words):
            outcomes = run_cases(content.resolve(), load_cases(questions))
            sys.stdout.write(report(str(questions), outcomes))
            sys.stdout.write(verdict(outcomes) + "\n\n")
            if unmet(outcomes):
                status = 1
    except KbError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    return status


def _sets(words: Sequence[str]) -> list[tuple[Path, Path]]:
    """Pairs of (question set, content root). Without arguments, every fixture set."""
    if len(words) > 2:
        raise KbError(USAGE)
    if words:
        questions = Path(words[0])
        content = Path(words[1]) if len(words) == 2 else questions.parent / "content"
        return [(questions, content)]
    found = sorted(Path("tests/fixtures").glob("*/questions.json"))
    if not found:
        raise KbError("no question sets under tests/fixtures")
    return [(path, path.parent / "content") for path in found]


def _percent(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{round(100 * part / whole)}%"


if __name__ == "__main__":
    raise SystemExit(main())

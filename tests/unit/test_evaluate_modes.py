"""Tests for the evaluation modes: question-set modes, session and combined scoring, and the session fixture."""

import json
from pathlib import Path

import pytest

from kb import evaluate
from kb.errors import KbError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SESSION_SET = FIXTURES / "session-recovery-v1" / "questions.json"
SESSION_CONTENT = FIXTURES / "session-recovery-v1" / "content"


def answerable(expected: tuple[str, ...], superseded: tuple[str, ...] = ()) -> evaluate.Case:
    return evaluate.Case("c", "alpha", expected, False, superseded)


def unanswerable() -> evaluate.Case:
    return evaluate.Case("u", "zeta", (), False)


def write_set(path: Path, cases: list[dict[str, object]], **extra: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"format": evaluate.FORMAT, "version": 1, "cases": cases, **extra}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def raw_case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"id": "c", "query": "alpha", "expected": ["a.md#1"]}
    base.update(overrides)
    return base


def test_load_set_defaults_to_curated_and_reads_superseded(tmp_path: Path) -> None:
    path = write_set(
        tmp_path / "q.json",
        [raw_case(id="cur", expected=["a.md#1"], superseded=["b.md#2"])],
    )
    cases, modes = evaluate.load_set(path)
    assert modes == ("curated",)
    assert cases == [evaluate.Case("cur", "alpha", ("a.md#1",), False, ("b.md#2",))]


def test_load_set_reads_its_modes(tmp_path: Path) -> None:
    path = write_set(tmp_path / "q.json", [raw_case()], modes=["sessions", "combined"])
    assert evaluate.load_set(path)[1] == ("sessions", "combined")


@pytest.mark.parametrize("modes", [[], "sessions", ["fast"], [1]])
def test_load_set_rejects_bad_modes(tmp_path: Path, modes: object) -> None:
    path = write_set(tmp_path / "q.json", [raw_case()], modes=modes)
    with pytest.raises(KbError, match="modes must be"):
        evaluate.load_set(path)


@pytest.mark.parametrize("superseded", ["b.md#2", [1]])
def test_superseded_must_be_a_list_of_locators(tmp_path: Path, superseded: object) -> None:
    path = write_set(tmp_path / "q.json", [raw_case(superseded=superseded)])
    with pytest.raises(KbError, match="superseded must be"):
        evaluate.load_set(path)


def _row(text: str, case_id: str) -> list[str]:
    """The words of one case line in a report."""
    rows = [line.split() for line in text.splitlines() if line.split()[:1] == [case_id]]
    assert len(rows) == 1
    return rows[0]


def test_curated_block_is_not_session_evidence() -> None:
    outcome = evaluate.Outcome(answerable(("a.md#1",)), ("a.md#1",), ("t.md#2",))
    assert outcome.passes(evaluate.CURATED)
    assert not outcome.passes(evaluate.SESSIONS)


def test_sessions_block_is_not_curated_evidence() -> None:
    outcome = evaluate.Outcome(answerable(("t.md#2",)), ("a.md#1",), ("t.md#2",))
    assert not outcome.passes(evaluate.CURATED)
    assert outcome.passes(evaluate.SESSIONS)


def test_combined_accepts_a_hit_in_either_block() -> None:
    outcome = evaluate.Outcome(answerable(("t.md#2",)), ("a.md#1",), ("t.md#2",))
    assert outcome.passes(evaluate.COMBINED)


def test_a_block_row_below_the_top_three_is_not_shown() -> None:
    sessions = ("x.md#1", "x.md#2", "x.md#3", "t.md#4")
    outcome = evaluate.Outcome(answerable(("t.md#4",)), (), sessions)
    assert not outcome.passes(evaluate.SESSIONS)


def test_unanswerable_passes_when_the_mode_shows_nothing() -> None:
    outcome = evaluate.Outcome(unanswerable(), (), ("t.md#1",))
    assert outcome.passes(evaluate.CURATED)
    assert not outcome.passes(evaluate.SESSIONS)
    assert not outcome.passes(evaluate.COMBINED)


@pytest.mark.parametrize(
    ("sessions", "passes"),
    [
        (("old.md#1", "new.md#1"), False),
        (("new.md#1", "old.md#1"), True),
        (("new.md#1",), True),
        (("old.md#1",), False),
        ((), False),
    ],
)
def test_current_state_needs_the_current_answer_above_the_superseded_one(
    sessions: tuple[str, ...], passes: bool
) -> None:
    case = answerable(("new.md#1",), ("old.md#1",))
    assert evaluate.Outcome(case, (), sessions).passes(evaluate.SESSIONS) is passes


def test_report_for_curated_is_the_original_report() -> None:
    outcomes = [evaluate.Outcome(answerable(("a.md#1",)), ("a.md#1",))]
    assert evaluate.report_for("s", outcomes, evaluate.CURATED) == evaluate.report("s", outcomes)


def test_report_for_sessions_lists_the_session_totals() -> None:
    outcomes = [
        evaluate.Outcome(answerable(("t.md#4",)), (), ("x.md#1", "x.md#2", "x.md#3", "t.md#4"), 30),
        evaluate.Outcome(unanswerable(), (), ("y.md#1",), 10),
    ]
    text = evaluate.report_for("s", outcomes, evaluate.SESSIONS)
    assert _row(text, "c") == ["c", "FAIL", "rank", "4"]
    assert _row(text, "u") == ["u", "FAIL", "returned", "1"]
    assert "session rows with an expected locator in the top 3: 0 of 1 (0%)" in text
    assert "session false positives (unanswerable with a row): 1 of 1 (100%)" in text
    assert "superseded claims shown: 0" in text
    assert "session characters per query: 20" in text


def test_report_for_combined_lists_the_added_coverage() -> None:
    superseded = evaluate.Case("cur", "alpha", ("t.md#2",), False, ("o.md#1",))
    outcome = evaluate.Outcome(superseded, ("a.md#1",), ("o.md#1", "t.md#2"), 50)
    text = evaluate.report_for("s", [outcome], evaluate.COMBINED)
    assert _row(text, "cur") == ["cur", "FAIL", "curated", "-,", "session", "2"]
    assert "curated rows with an expected locator in the top 3: 0 of 1 (0%)" in text
    assert "session rows with an expected locator in the top 3: 1 of 1 (100%)" in text
    assert "added by the session block (curated top 3 missed it): 1 of 1 (100%)" in text
    assert "current-state cases with the current answer above the superseded one: 0 of 1" in text
    assert "superseded claims shown: 1" in text


def test_report_without_cases_says_n_a() -> None:
    text = evaluate.report_for("s", [], evaluate.SESSIONS)
    assert "session characters per query: n/a" in text
    assert "(n/a)" in text


def test_run_cases_scores_each_mode_from_its_own_rows() -> None:
    cases, _ = evaluate.load_set(SESSION_SET)
    sessions = evaluate.run_cases(SESSION_CONTENT, cases, evaluate.SESSIONS)
    assert all(outcome.ranked == () for outcome in sessions)
    assert all(outcome.sessions for outcome in sessions if not outcome.case.unanswerable)

    curated = evaluate.run_cases(SESSION_CONTENT, cases, evaluate.CURATED)
    assert all(outcome.sessions == () for outcome in curated)
    assert all(outcome.session_chars == 0 for outcome in curated)

    combined = evaluate.run_cases(SESSION_CONTENT, cases, evaluate.COMBINED)
    assert all(outcome.sessions for outcome in combined if not outcome.case.unanswerable)


def test_main_scores_the_session_fixture_in_sessions_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = evaluate.main(["--mode", "sessions", str(SESSION_SET)])
    out = capsys.readouterr().out
    assert status == 0
    assert "recovery-01" in out
    assert "session rows with an expected locator in the top 3: 4 of 4 (100%)" in out
    assert "session false positives (unanswerable with a row): 0 of 2 (0%)" in out
    assert "acceptance: met" in out


def test_main_scores_the_session_fixture_in_combined_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    evaluate.main(["--mode", "combined", str(SESSION_SET)])
    out = capsys.readouterr().out
    assert "added by the session block (curated top 3 missed it): 4 of 4 (100%)" in out


def test_main_rejects_an_unknown_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluate.main(["--mode", "fast"]) == 1
    assert "Usage:" in capsys.readouterr().err
    assert evaluate.main(["--mode"]) == 1


def test_main_without_paths_scores_only_the_sets_that_declare_the_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_set(tmp_path / "tests/fixtures/curated-set/questions.json", [raw_case()])
    write_set(
        tmp_path / "tests/fixtures/session-set/questions.json",
        [raw_case()],
        modes=["sessions"],
    )
    for name in ("curated-set", "session-set"):
        (tmp_path / "tests/fixtures" / name / "content/knowledge").mkdir(parents=True)

    evaluate.main(["--mode", "sessions"])
    out = capsys.readouterr().out
    assert "session-set" in out
    assert "curated-set" not in out

    evaluate.main([])
    out = capsys.readouterr().out
    assert "curated-set" in out
    assert "session-set" not in out


def test_main_without_a_set_for_the_mode_is_an_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    write_set(tmp_path / "tests/fixtures/curated-set/questions.json", [raw_case()])
    assert evaluate.main(["--mode", "combined"]) == 1
    assert "no question sets for mode combined under tests/fixtures" in capsys.readouterr().err


PENDING_TRANSCRIPT = (
    "---\n"
    "title: Session transcript: quokka\n"
    "source: session-transcript\n"
    "session: quokka-session\n"
    "part: 1\n"
    "first_message: quokka-1\n"
    "last_message: quokka-1\n"
    "started: 2026-10-20T10:00:00Z\n"
    "ended: 2026-10-20T10:05:00Z\n"
    "created: 2026-10-20T10:05:00Z\n"
    "---\n\n"
    "## 1. user, 2026-10-20T10:00:00Z\n\n"
    "Quokka habitat notes from the session.\n"
)


def test_combined_mode_scores_the_pending_transcript_that_recall_prints_as_evidence(
    tmp_path: Path,
) -> None:
    """With no curated match, recall prints the pending transcript under Evidence. Combined mode
    must score that row too, so it does not drop rows that Uncurated would have shown."""
    root = tmp_path / "content"
    relpath = "observations/pending/20261020T100000-quokka.md"
    (root / relpath).parent.mkdir(parents=True)
    (root / relpath).write_text(PENDING_TRANSCRIPT, encoding="utf-8")
    case = evaluate.Case("pending", "quokka habitat", (f"{relpath}#1",), False)

    [outcome] = evaluate.run_cases(root, [case], evaluate.COMBINED)

    assert outcome.ranked == ()
    assert outcome.sessions == (f"{relpath}#1",)
    assert outcome.passes(evaluate.COMBINED)

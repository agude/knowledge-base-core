"""Tests for the retrieval evaluation: loading question sets, scoring, reporting, and the command."""

import json
import runpy
import sys
from pathlib import Path

import pytest

from kb import evaluate
from kb.errors import KbError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def write_set(path: Path, cases: list[dict[str, object]], fmt: str = evaluate.FORMAT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": fmt, "version": 1, "cases": cases}), encoding="utf-8")
    return path


def case(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "c",
        "query": "alpha",
        "expected": ["a.md#1"],
        "unanswerable": False,
    }
    base.update(overrides)
    return base


def test_load_cases_reads_each_field(tmp_path: Path) -> None:
    path = write_set(
        tmp_path / "q.json",
        [
            case(id="one", expected=["a.md#1", "b.md#2"], requires_all=True),
            case(id="two", expected=[], unanswerable=True, query="none"),
        ],
    )
    cases = evaluate.load_cases(path)
    assert cases[0] == evaluate.Case("one", "alpha", ("a.md#1", "b.md#2"), True)
    assert cases[1].unanswerable
    assert cases[1].requires_all is False


@pytest.mark.parametrize(
    ("fmt", "bad"),
    [
        ("other", {}),
        ("kb-retrieval-questions", {"unanswerable": True}),
        ("kb-retrieval-questions", {"expected": []}),
        ("kb-retrieval-questions", {"expected": [1]}),
    ],
)
def test_load_cases_rejects_bad_sets(tmp_path: Path, fmt: str, bad: dict[str, object]) -> None:
    path = write_set(tmp_path / "q.json", [case(**bad)], fmt=fmt)
    with pytest.raises(KbError):
        evaluate.load_cases(path)


def test_load_cases_rejects_invalid_json_and_missing_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(KbError):
        evaluate.load_cases(broken)
    with pytest.raises(KbError):
        evaluate.load_cases(tmp_path / "missing.json")


def test_load_cases_rejects_a_case_that_is_not_an_object(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps({"format": evaluate.FORMAT, "version": 1, "cases": ["x"]}), encoding="utf-8"
    )
    with pytest.raises(KbError, match="every case must be an object"):
        evaluate.load_cases(path)


def test_load_cases_rejects_a_set_that_is_not_an_object(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(KbError, match="not a kb-retrieval-questions"):
        evaluate.load_cases(path)


def test_outcome_rank_is_the_best_expected_position() -> None:
    answer = evaluate.Case("c", "q", ("b.md#1", "c.md#1"), False)
    outcome = evaluate.Outcome(answer, ("a.md#1", "b.md#1", "c.md#1"))
    assert outcome.rank == 2
    assert outcome.hit
    assert outcome.every_expected_in_top


def test_outcome_without_an_expected_locator_has_no_rank() -> None:
    outcome = evaluate.Outcome(evaluate.Case("c", "q", ("z.md#1",), False), ("a.md#1",))
    assert outcome.rank is None
    assert not outcome.hit
    assert not outcome.every_expected_in_top


def test_a_locator_below_the_top_three_is_a_miss() -> None:
    outcome = evaluate.Outcome(
        evaluate.Case("c", "q", ("d.md#1",), False), ("a", "b", "c", "d.md#1")
    )
    assert outcome.rank == 4
    assert not outcome.hit


def test_report_lists_each_case_and_the_three_totals() -> None:
    answerable = evaluate.Case("hit", "q", ("a.md#1",), False)
    missed = evaluate.Case("miss", "q", ("z.md#1",), False)
    empty = evaluate.Case("abstain", "q", (), True)
    noisy = evaluate.Case("noise", "q", (), True)
    multi = evaluate.Case("multi", "q", ("a.md#1", "b.md#1"), True)
    text = evaluate.report(
        "set.json",
        [
            evaluate.Outcome(answerable, ("a.md#1",)),
            evaluate.Outcome(missed, ("a.md#1",)),
            evaluate.Outcome(empty, ()),
            evaluate.Outcome(noisy, ("a.md#1",)),
            evaluate.Outcome(multi, ("a.md#1", "b.md#1")),
        ],
    )
    lines = text.splitlines()
    assert lines[0] == "set.json"
    assert "hit" in lines[1] and "pass" in lines[1] and "rank 1" in lines[1]
    assert "miss" in lines[2] and "FAIL" in lines[2] and "rank -" in lines[2]
    assert "returned 0" in lines[3]
    assert "returned 1" in lines[4]
    assert lines[-3] == "answerable with an expected locator in the top 3: 2 of 3 (67%)"
    assert lines[-2] == "unanswerable with no curated result: 1 of 2 (50%)"
    assert lines[-1] == "requires_all with every expected locator in the top 3: 1 of 1 (100%)"


def test_report_without_answerable_or_required_cases_says_n_a() -> None:
    text = evaluate.report("s", [evaluate.Outcome(evaluate.Case("x", "q", (), True), ())])
    assert "(n/a)" in text
    assert "requires_all" not in text


def test_run_cases_uses_the_curated_ranking() -> None:
    content = FIXTURES / "content"
    cases = [evaluate.Case("restart", "nas restart order", ("knowledge/infra/nas.md#1",), False)]
    outcomes = evaluate.run_cases(content, cases)
    assert outcomes[0].ranked[0] == "knowledge/infra/nas.md#1"
    assert outcomes[0].hit


def test_main_scores_the_named_set_and_its_content(capsys: pytest.CaptureFixture[str]) -> None:
    questions = FIXTURES / "retrieval-question-v1" / "questions.json"
    assert evaluate.main([str(questions)]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{questions}\n")
    assert "answerable with an expected locator in the top 3: 8 of 8 (100%)" in out


def test_main_with_an_explicit_content_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    questions = write_set(
        tmp_path / "q.json",
        [case(query="nas restart order", expected=["knowledge/infra/nas.md#1"])],
    )
    assert evaluate.main([str(questions), str(FIXTURES / "content")]) == 0
    assert "1 of 1 (100%)" in capsys.readouterr().out


def test_main_without_arguments_scores_every_fixture_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = FIXTURES.parent.parent
    monkeypatch.chdir(repository)
    status = evaluate.main([])
    out = capsys.readouterr().out
    assert "tests/fixtures/retrieval-v1/questions.json" in out
    assert "tests/fixtures/retrieval-question-v1/questions.json" in out
    assert out.count("acceptance:") == 2
    assert status == (1 if "not met" in out else 0)


def test_main_without_question_sets_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert evaluate.main([]) == 1
    assert capsys.readouterr().err == "no question sets under tests/fixtures\n"


def test_main_rejects_too_many_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert evaluate.main(["a", "b", "c"]) == 1
    assert capsys.readouterr().err == evaluate.USAGE + "\n"


def test_main_reads_sys_argv_by_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    questions = FIXTURES / "retrieval-question-v1" / "questions.json"
    monkeypatch.setattr(sys, "argv", ["evaluate", str(questions)])
    assert evaluate.main() == 0
    assert capsys.readouterr().out.startswith(f"{questions}\n")


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")
def test_module_entry_point_runs_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate", "/nonexistent/questions.json"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("kb.evaluate", run_name="__main__")
    assert exit_info.value.code == 1


def test_verdict_is_met_when_every_case_meets_the_criterion() -> None:
    answer = evaluate.Case("hit", "q", ("a.md#1",), False)
    gap = evaluate.Case("gap", "q", (), True)
    outcomes = [evaluate.Outcome(answer, ("a.md#1",)), evaluate.Outcome(gap, ())]
    assert evaluate.verdict(outcomes) == "acceptance: met"


def test_verdict_names_every_case_that_fails_the_criterion() -> None:
    missed = evaluate.Case("missed", "q", ("z.md#1",), False)
    noisy = evaluate.Case("noisy", "q", (), True)
    outcomes = [evaluate.Outcome(missed, ("a.md#1",)), evaluate.Outcome(noisy, ("a.md#1",))]
    assert evaluate.verdict(outcomes) == "acceptance: not met (missed, noisy)"


def test_main_exits_one_when_a_case_fails_the_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    questions = write_set(
        tmp_path / "q.json",
        [case(id="gap", query="quantum zebra", expected=["a.md#1"])],
    )
    assert evaluate.main([str(questions), str(FIXTURES / "content")]) == 1
    assert "acceptance: not met (gap)" in capsys.readouterr().out


def test_main_exits_zero_when_every_case_meets_the_criterion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    questions = write_set(
        tmp_path / "q.json",
        [case(id="found", query="nas restart order", expected=["knowledge/infra/nas.md#1"])],
    )
    assert evaluate.main([str(questions), str(FIXTURES / "content")]) == 0
    assert "acceptance: met" in capsys.readouterr().out

"""evaluate-retrieval: fixture validation, reports, baselines, and regressions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from kbtest import normalize
from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.runner import KB, Result

FIXTURES = REPO / "tests" / "fixtures"
LITERAL = FIXTURES / "retrieval-v1"
QUESTION = FIXTURES / "retrieval-question-v1"


def _fixture(cases: list[dict[str, Any]], fixture_id: str, corpus_id: str) -> dict[str, Any]:
    return {
        "format": "knowledge-base-retrieval-evaluation",
        "version": 1,
        "fixture_id": fixture_id,
        "corpus_id": corpus_id,
        "cases": cases,
    }


def _single_case(
    case_id: str, query: str, path: str = "", section: str = "", unanswerable: bool = False
) -> dict[str, Any]:
    return _fixture(
        [
            {
                "id": case_id,
                "category": "focused-test",
                "query": query,
                "expected_sections": [] if unanswerable else [{"path": path, "section": section}],
                "requires_all_sections": False,
                "unanswerable": unanswerable,
            }
        ],
        "focused-retrieval-v1",
        "focused-corpus-v1",
    )


def _write(kb: KB, name: str, data: dict[str, Any]) -> Path:
    path = kb.layout.root / name
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def _copy_corpus(kb: KB, source: Path) -> Path:
    root = kb.layout.root / "corpus"
    shutil.copytree(source / "content", root)
    return root


def _evaluate(kb: KB, *args: str, env: dict[str, str | None] | None = None) -> Result:
    return kb.run("evaluate-retrieval", *args, "--json", env=env, timeout=600)


def _check(kb: KB, golden: Golden, result: Result) -> dict[str, Any] | None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stderr", kb.norm_err(result.err))
    if not result.out:
        golden.check("stdout", "")
        return None
    golden.check("report", kb.norm(normalize.report(result.out)))
    return json.loads(result.out)


@pytest.mark.bats(
    "evaluate_retrieval.bats", "evaluation does not count evidence outside the bounded response"
)
def test_bounded_response(kb: KB, golden: Golden) -> None:
    for index in range(1, 6):
        kb.create_article(
            f"alias-{index}.md",
            f'---\ntitle: "Alias {index}"\naliases:\n  - "target route {index}"\n---\n\n'
            f"# Alias {index}\n\nRouting record.",
        )
    kb.create_article("evidence.md", "# Evidence\n\n## Required\n\ntarget\n\n## Other\n\nroute")
    fixture = _write(
        kb,
        "alias-fixture.json",
        _fixture(
            [
                {
                    "id": "aliases-hide-evidence",
                    "category": "routing",
                    "query": "Where is the target route?",
                    "query_mode": "question",
                    "expected_sections": [{"path": "knowledge/evidence.md", "section": "Required"}],
                    "requires_all_sections": False,
                    "unanswerable": False,
                }
            ],
            "bounded-routing",
            "synthetic-corpus-v1",
        ),
    )
    result = _evaluate(kb, "--fixture", str(fixture), "--content-dir", str(kb.layout.content))
    _check(kb, golden, result)


@pytest.mark.data
@pytest.mark.bats(
    "evaluate_retrieval.bats", "public retrieval fixture has versioned coverage cases"
)
def test_public_fixture_coverage() -> None:
    fixture = json.loads((LITERAL / "retrieval-v1.json").read_text(encoding="utf-8"))
    assert fixture["format"] == "knowledge-base-retrieval-evaluation"
    assert fixture["version"] == 1
    assert 30 <= len(fixture["cases"]) <= 50
    categories = {case["category"] for case in fixture["cases"]}
    assert {
        "exact_command_or_name",
        "paraphrase",
        "cross_article",
        "changed_fact",
        "conflicting_evidence",
        "absent_answer",
    } <= categories
    baseline = json.loads((LITERAL / "retrieval-v1.baseline.json").read_text(encoding="utf-8"))
    assert baseline["format"] == "knowledge-base-retrieval-evaluation-baseline"
    assert baseline["version"] == 1
    assert len(baseline["cases"]) == 36


@pytest.mark.data
@pytest.mark.bats(
    "evaluate_retrieval.bats",
    "temporal answer judgments separate retrieval from current-claim selection",
)
def test_temporal_judgments() -> None:
    data = json.loads((QUESTION / "temporal-judgments.json").read_text(encoding="utf-8"))
    assert data["format"] == "knowledge-base-temporal-answer-judgments"
    assert data["version"] == 1
    assert data["fixture_id"] == "synthetic-question-v1"
    assert len(data["judgments"]) == 2
    for judgment in data["judgments"]:
        assert judgment["answer_judgment"] == "manual"
        for key in (
            "expected_current_claim",
            "historical_claims",
            "supporting_sections",
            "abstain_if",
        ):
            assert judgment[key], key


@pytest.mark.bats(
    "evaluate_retrieval.bats", "evaluation reports per-case metrics and aggregate evidence scores"
)
def test_literal_fixture_report(kb: KB, golden: Golden) -> None:
    shutil.copytree(
        LITERAL / "content" / "knowledge", kb.layout.content / "knowledge", dirs_exist_ok=True
    )
    result = _evaluate(
        kb,
        "--fixture",
        str(LITERAL / "retrieval-v1.json"),
        "--content-dir",
        str(kb.layout.content),
        "--baseline",
        str(LITERAL / "retrieval-v1.baseline.json"),
    )
    report = _check(kb, golden, result)
    assert report is not None
    assert report["baseline_comparison"]["regressions"] == []


@pytest.mark.bats("evaluate_retrieval.bats", "evaluation runs committed question-mode fixture")
def test_question_fixture_report(kb: KB, golden: Golden) -> None:
    root = _copy_corpus(kb, QUESTION)
    result = _evaluate(
        kb,
        "--fixture",
        str(QUESTION / "retrieval-question-v1.json"),
        "--content-dir",
        str(root),
        "--baseline",
        str(QUESTION / "retrieval-question-v1.baseline.json"),
    )
    report = _check(kb, golden, result)
    assert report is not None
    assert report["baseline_comparison"]["regressions"] == []


@pytest.mark.bats(
    "evaluate_retrieval.bats",
    "evaluation freezes a pre-change literal control on the question corpus",
)
def test_pre_change_control(kb: KB, golden: Golden) -> None:
    root = _copy_corpus(kb, QUESTION)
    result = _evaluate(
        kb,
        "--fixture",
        str(QUESTION / "retrieval-question-pre-change-v1.json"),
        "--content-dir",
        str(root),
        "--baseline",
        str(QUESTION / "retrieval-question-pre-change-v1.baseline.json"),
    )
    _check(kb, golden, result)


@pytest.mark.bats(
    "evaluate_retrieval.bats", "evaluation reports strict and relaxed comparison gains separately"
)
def test_comparison_fixture(kb: KB, golden: Golden) -> None:
    root = _copy_corpus(kb, QUESTION)
    result = _evaluate(
        kb,
        "--fixture",
        str(QUESTION / "retrieval-question-comparison-v1.json"),
        "--content-dir",
        str(root),
        "--baseline",
        str(QUESTION / "retrieval-question-comparison-v1.baseline.json"),
    )
    _check(kb, golden, result)


@pytest.mark.bats("evaluate_retrieval.bats", "evaluation reports an optional output byte budget")
def test_output_budget(kb: KB, golden: Golden) -> None:
    root = _copy_corpus(kb, QUESTION)
    result = _evaluate(
        kb,
        "--fixture",
        str(QUESTION / "retrieval-question-v1.json"),
        "--content-dir",
        str(root),
        "--max-bytes",
        "2000",
    )
    _check(kb, golden, result)


@pytest.mark.bats(
    "evaluate_retrieval.bats", "fail-on-regression catches new false-positive retrieval"
)
def test_false_positive_regression(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "false-positive.md", "# False Positive\n\n## Evidence\n\nobsolete setting is enabled"
    )
    fixture = _write(
        kb, "fixture.json", _single_case("focused-absent", "obsolete setting", unanswerable=True)
    )
    baseline = kb.layout.root / "baseline.json"
    written = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--write-baseline",
        str(baseline),
    )
    assert written.returncode == 0
    golden.check("baseline", kb.norm(normalize.report(baseline.read_text(encoding="utf-8"))))

    data = json.loads(baseline.read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case["id"] == "focused-absent":
            case["false_positive_retrieval"] = False
    mutated = _write(kb, "mutated.json", data)
    result = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--baseline",
        str(mutated),
        "--fail-on-regression",
    )
    _check(kb, golden, result)


@pytest.mark.bats(
    "evaluate_retrieval.bats", "evaluation can select content independently of KB_CONTENT_DIR"
)
def test_content_dir_without_env(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "content-root.md", "# Content Root\n\n## Evidence\n\nfocused content root evidence"
    )
    fixture = _write(
        kb,
        "fixture.json",
        _single_case(
            "content-root", "focused content root", "knowledge/content-root.md", "Evidence"
        ),
    )
    result = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        env={"KB_CONTENT_DIR": None},
    )
    _check(kb, golden, result)


@pytest.mark.bats("evaluate_retrieval.bats", "evaluation writes and compares a frozen baseline")
def test_write_and_compare_baseline(kb: KB, golden: Golden) -> None:
    kb.create_article("baseline.md", "# Baseline\n\n## Evidence\n\nfocused baseline evidence")
    fixture = _write(
        kb,
        "fixture.json",
        _single_case("baseline", "focused baseline", "knowledge/baseline.md", "Evidence"),
    )
    baseline = kb.layout.root / "retrieval.baseline.json"
    written = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--write-baseline",
        str(baseline),
    )
    assert written.returncode == 0
    golden.check("baseline", kb.norm(normalize.report(baseline.read_text(encoding="utf-8"))))
    result = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--baseline",
        str(baseline),
        "--fail-on-regression",
    )
    _check(kb, golden, result)


@pytest.mark.bats("evaluate_retrieval.bats", "evaluation rejects an unversioned fixture")
def test_rejects_unversioned_fixture(kb: KB, golden: Golden) -> None:
    fixture = kb.layout.root / "invalid.json"
    fixture.write_text('{"version": 2, "cases": []}\n', encoding="utf-8")
    _check(kb, golden, _evaluate(kb, "--fixture", str(fixture)))


@pytest.mark.bats(
    "evaluate_retrieval.bats",
    "evaluation rejects an expected path or section absent from the corpus",
)
@pytest.mark.parametrize(
    ("path", "section"),
    [("knowledge/missing.md", "Missing"), ("knowledge/operations.md", "Missing")],
    ids=["path", "section"],
)
def test_rejects_absent_locator(kb: KB, golden: Golden, path: str, section: str) -> None:
    kb.create_article("operations.md", "# Operations\n\n## Restart\n\nRestart documentation.")
    case = _single_case("missing-path", "systemctl restart kb-api", path, section)
    fixture = _write(kb, "invalid.json", case)
    _check(kb, golden, _evaluate(kb, "--fixture", str(fixture)))


@pytest.mark.bats(
    "evaluate_retrieval.bats",
    "fail-on-regression catches rank and evidence regressions while status stays pass",
)
def test_rank_and_evidence_regression(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "multi.md",
        "# Multi\n\n## First\n\nshared retrieval phrase\n\n## Second\n\n"
        "This section exists but does not match the query.",
    )
    fixture = _write(
        kb,
        "fixture.json",
        _fixture(
            [
                {
                    "id": "multi",
                    "category": "test",
                    "query": "shared retrieval phrase",
                    "expected_sections": [
                        {"path": "knowledge/multi.md", "section": "First"},
                        {"path": "knowledge/multi.md", "section": "Second"},
                    ],
                    "requires_all_sections": False,
                    "unanswerable": False,
                }
            ],
            "multi-section-regression",
            "synthetic-corpus-v1",
        ),
    )
    baseline = kb.layout.root / "baseline.json"
    written = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--write-baseline",
        str(baseline),
    )
    assert written.returncode == 0
    data = json.loads(baseline.read_text(encoding="utf-8"))
    for case in data["cases"]:
        if case["id"] == "multi":
            case.update(
                first_relevant_rank=0, all_required_evidence=True, matched_required_evidence_count=2
            )
    mutated = _write(kb, "mutated.json", data)
    result = _evaluate(
        kb,
        "--fixture",
        str(fixture),
        "--content-dir",
        str(kb.layout.content),
        "--baseline",
        str(mutated),
        "--fail-on-regression",
    )
    _check(kb, golden, result)


@pytest.mark.parametrize("args", [[], ["--fixture"], ["--bogus"], ["--max-bytes", "x"]])
def test_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    result = kb.run("evaluate-retrieval", *args)
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))

"""Retrieval over the committed fixture corpora: search, toc, and section.

Contract: for each fixture case, the top-ranked result and the set of the
top five (path, section) results; the toc outline of each corpus; the
content of every expected section. Reference: the full search, toc, and
section output. Retrieval quality is measured separately by
evaluate-retrieval against its baselines.
"""

from __future__ import annotations

import json
import shutil
from typing import Any

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.runner import KB, Result

FIXTURES = REPO / "tests" / "fixtures"
CORPORA = {
    "retrieval-v1": FIXTURES / "retrieval-v1" / "retrieval-v1.json",
    "retrieval-question-v1": FIXTURES / "retrieval-question-v1" / "retrieval-question-v1.json",
}


def _corpus(kb: KB, name: str) -> dict[str, str | None]:
    """Copy a fixture corpus into a content root and return the env selecting it."""
    root = kb.layout.root / "corpus"
    shutil.copytree(FIXTURES / name / "content", root)
    for sub in (
        "knowledge",
        "observations/pending",
        "observations/archived",
        "questions/open",
        "sources",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    kb.normalizer.add_path(root, "<CORPUS>")
    return {"KB_CONTENT_DIR": str(root)}


def _cases(name: str) -> list[dict[str, Any]]:
    return json.loads(CORPORA[name].read_text(encoding="utf-8"))["cases"]


def _query_args(case: dict[str, Any]) -> list[str]:
    if case.get("query_mode") == "question":
        return ["--query", case["query"]]
    return ["--", case["query"]]


def _top(result: Result, *, json_mode: bool) -> tuple[str, list[str]]:
    """The first result and the sorted top five, as 'path | section'."""
    if json_mode:
        rows = [
            f"{r['path']} | {r['locator']['section']}" for r in json.loads(result.out)["results"]
        ]
    else:
        rows = [
            " | ".join(line.split(" | ")[:2]) for line in result.out.splitlines() if " | " in line
        ]
    rows = rows[:5]
    return (rows[0] if rows else "none"), sorted(rows)


@pytest.mark.parametrize("mode", ["text", "json"])
@pytest.mark.parametrize("name", sorted(CORPORA))
def test_search_fixture(kb: KB, golden: Golden, name: str, mode: str) -> None:
    env = _corpus(kb, name)
    flags = ["--json"] if mode == "json" else []
    results, contract = [], []
    for case in _cases(name):
        result = kb.run(
            "search", *flags, "--limit", "5", "--per-file", "0", *_query_args(case), env=env
        )
        assert result.returncode == 0, (case["id"], result.err)
        if mode == "json":
            json.loads(result.out)
        first, top = _top(result, json_mode=mode == "json")
        contract.append(
            f"{case['id']}\n  first {first}\n" + "".join(f"  top {row}\n" for row in top)
        )
        results.append(result)
    golden.contract("top", kb.norm("".join(contract)))
    golden.check("transcript", kb.transcript(*results))


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_toc_fixture(kb: KB, golden: Golden, name: str) -> None:
    env = _corpus(kb, name)
    result = kb.run("toc", "--depth", "3", env=env)
    assert result.returncode == 0
    golden.contract("facts", kb.norm(facts.toc(result.out)))
    golden.check("stdout", kb.norm(result.out))


@pytest.mark.parametrize("mode", ["text", "json"])
@pytest.mark.parametrize("name", sorted(CORPORA))
def test_section_fixture(kb: KB, golden: Golden, name: str, mode: str) -> None:
    env = _corpus(kb, name)
    flags = ["--json"] if mode == "json" else []
    expected = sorted(
        {(s["path"], s["section"]) for case in _cases(name) for s in case["expected_sections"]}
    )
    contract, results = [], []
    for path, heading in expected:
        if heading == "alias":
            continue  # a routing locator, not a section
        selector = {"top": ["--top"], "title": ["--title"]}.get(
            heading, ["--heading", heading, "--exact"]
        )
        result = kb.run("section", *flags, "--file", path, *selector, env=env)
        assert result.returncode == 0, (path, heading, result.err)
        if mode == "json":
            body = json.loads(result.out)["content"]
        else:
            body = facts.section_body(result.out)
        contract.append(f"## {path} | {heading}\n{body}")
        results.append(result)
    golden.contract("content", kb.norm("".join(contract)))
    golden.check("transcript", kb.transcript(*results))


@pytest.mark.parametrize("mode", ["text", "json"])
def test_section_metadata_fixture(kb: KB, golden: Golden, mode: str) -> None:
    fixture = FIXTURES / "section-metadata"
    shutil.copy(fixture / "knowledge" / "metadata.md", kb.layout.content / "knowledge")
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    toc = kb.run("toc", "--depth", "3", "--path", "knowledge/metadata.md")
    golden.contract("toc", kb.norm(facts.toc(toc.out)))
    numbers = [
        line.split(" ")[1]
        for line in facts.toc(toc.out).splitlines()
        if line.startswith("heading ")
    ]
    flags = ["--json"] if mode == "json" else []
    results = [
        kb.run("section", *flags, "--file", "knowledge/metadata.md", "--number", n) for n in numbers
    ]
    values = []
    for number, result in zip(numbers, results, strict=True):
        assert result.returncode == 0, (number, result.err)
        if mode == "json":
            values.append(
                f"## {number}\n{json.dumps(json.loads(result.out), indent=2, sort_keys=True)}\n"
            )
        else:
            values.append(f"## {number}\n{facts.section_body(result.out)}")
    golden.contract("sections", kb.norm("".join(values)))
    golden.check("transcript", kb.transcript(toc, *results))


@pytest.mark.data
def test_fixture_corpora_exist() -> None:
    for path in CORPORA.values():
        assert path.is_file()
        assert (path.parent / "content").is_dir()
    assert (FIXTURES / "section-metadata" / "knowledge" / "metadata.md").is_file()

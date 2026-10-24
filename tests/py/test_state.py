"""Read-only commands against the state-v1 content repository."""

from __future__ import annotations

import re

import pytest

from kbtest import env as envmod
from kbtest import facts, state
from kbtest.golden import Golden
from kbtest.runner import KB, Result


@pytest.fixture
def stateful(kb: KB) -> KB:
    state.build(kb.layout.content, kb.git_env())
    return kb


def _pin(kb: KB, golden: Golden, result: Result, contract: str) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("facts", kb.norm(contract))
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.harness
def test_state_builds_are_identical(tmp_path_factory: pytest.TempPathFactory, kb: KB) -> None:
    builds = []
    for index in range(2):
        other = KB(
            layout=envmod.Layout.under(tmp_path_factory.mktemp(f"state{index}")),
            resolve_impl=kb.resolve_impl,
            default_impl=kb.default_impl,
            session_prefix=kb.session_prefix,
        )
        other.setup()
        state.build(other.layout.content, other.git_env())
        builds.append((state.snapshot(other.layout.content), other.commits()))
    assert builds[0] == builds[1]
    assert len(builds[0][1]) == 4


@pytest.mark.parametrize("args", [[], ["--count"], ["--full"], ["--preview"]])
def test_pending(stateful: KB, golden: Golden, args: list[str]) -> None:
    result = stateful.run("pending", *args)
    if args == ["--count"]:
        assert result.out == "3\n"
        contract = result.out
    elif args == ["--preview"]:
        contract = (
            "\n".join(
                line
                for line in result.out.splitlines()
                if line.startswith(("Batch-selectable", "Oldest", "Observation", "Transcript"))
            )
            + "\n"
        )
    elif args == ["--full"]:
        names = re.findall(r"^--- (\S+) ---$", result.out, re.MULTILINE)
        assert names == sorted(state.PENDING)
        for name in names:
            text = (stateful.layout.content / "observations" / "pending" / name).read_text(
                encoding="utf-8"
            )
            assert text in result.out
        contract = "\n".join(names) + "\n"
    else:
        contract = "\n".join(facts.pending(result.out)) + "\n"
        assert facts.pending(result.out) == sorted(state.PENDING)
    _pin(stateful, golden, result, contract)


@pytest.mark.parametrize("args", [[], ["--count"], ["--sections"], ["--path", "sources"]])
def test_stale(stateful: KB, golden: Golden, args: list[str]) -> None:
    result = stateful.run("stale", *args)
    assert result.returncode == 0
    _pin(stateful, golden, result, facts.stale(result.out))


@pytest.mark.parametrize("args", [[], ["--brief"]])
def test_status(stateful: KB, golden: Golden, args: list[str]) -> None:
    result = stateful.run("status", *args)
    assert result.returncode == 0
    _pin(stateful, golden, result, facts.status(result.out))


def test_context(stateful: KB, golden: Golden) -> None:
    result = stateful.run("context")
    assert result.returncode == 0
    _pin(stateful, golden, result, facts.status(result.out))


@pytest.mark.parametrize("args", [[], ["--all"], ["--path", "knowledge/people"]])
def test_questions(stateful: KB, golden: Golden, args: list[str]) -> None:
    result = stateful.run("questions", *args)
    assert result.returncode == 0
    listed = facts.questions(result.out)
    assert listed, "state-v1 has open questions"
    _pin(stateful, golden, result, "".join(f"{title} | {context}\n" for title, context in listed))


def test_session_context(stateful: KB, golden: Golden) -> None:
    result = stateful.run("session-context")
    assert result.returncode == 0
    _pin(stateful, golden, result, stateful.context_facts(result.out))

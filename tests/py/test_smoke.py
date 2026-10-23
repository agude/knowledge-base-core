"""Smoke tests: prove the harness drives a real implementation end to end."""

from __future__ import annotations

from kbtest.golden import Golden
from kbtest.normalize import OBSERVATION_NAME
from kbtest.runner import KB


def test_status_empty(kb: KB, golden: Golden) -> None:
    result = kb.run("status")
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


def test_status_brief_counts(kb: KB, golden: Golden) -> None:
    kb.create_article("a.md", "# A\n\nBody.")
    kb.create_observation("20260412T000000-00000001.md", "Pending", "Body.")
    kb.create_question("q.md", "Open question?")
    result = kb.run("status", "--brief")
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))


def test_status_unknown_option(kb: KB, golden: Golden) -> None:
    result = kb.run("status", "--bogus")
    assert result.returncode == 1
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


def test_observe_writes_and_commits(kb: KB, golden: Golden) -> None:
    result = kb.run("observe", "--title", "Smoke", "--body", "Line one.\nLine two.")
    assert result.returncode == 0
    pending = sorted((kb.layout.content / "observations" / "pending").iterdir())
    assert len(pending) == 1
    assert OBSERVATION_NAME.fullmatch(pending[0].name)
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    golden.check("file", kb.norm(pending[0].read_text(encoding="utf-8")))
    golden.check("log", kb.norm(kb.git("log", "--format=%H %s", "--name-only")))

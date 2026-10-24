"""observe: record a pending observation and commit it under the lock."""

from __future__ import annotations

import time

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git_log, tree
from kbtest.normalize import OBSERVATION_NAME
from kbtest.runner import KB, Result


def _pending(kb: KB) -> list[str]:
    return sorted(p.name for p in (kb.layout.content / "observations" / "pending").iterdir())


def _only_file(kb: KB) -> str:
    names = _pending(kb)
    assert len(names) == 1, names
    path = kb.layout.content / "observations" / "pending" / names[0]
    return kb.norm(path.read_text(encoding="utf-8"))


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    golden.check("pending", kb.norm("\n".join(_pending(kb)) + "\n"))
    golden.check("log", kb.norm(git_log(kb.layout.content, kb.git_env())))


@pytest.mark.bats("observe.bats", "observe creates file with correct frontmatter")
def test_observe_writes_front_matter(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "observe",
        "--title",
        "Test title",
        "--body",
        "Test body",
        "--no-commit",
        env={"KNOWLEDGE_OBSERVE": "1"},
    )
    _check(kb, golden, result)
    golden.check("file", _only_file(kb))


@pytest.mark.bats("observe.bats", "observe respects custom --source")
def test_observe_source(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "observe", "--title", "Test", "--body", "Body", "--source", "slack", "--no-commit"
    )
    _check(kb, golden, result)
    golden.check("file", _only_file(kb))


@pytest.mark.bats("observe.bats", "observe works without KNOWLEDGE_OBSERVE set")
@pytest.mark.parametrize("observe", [None, "0"], ids=["unset", "disabled"])
def test_observe_ignores_knowledge_observe(kb: KB, golden: Golden, observe: str | None) -> None:
    result = kb.run(
        "observe",
        "--title",
        "Test",
        "--body",
        "Body",
        "--no-commit",
        env={"KNOWLEDGE_OBSERVE": observe},
    )
    _check(kb, golden, result)


@pytest.mark.bats("observe.bats", "observe requires --title")
def test_observe_requires_title(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("observe", "--body", "Body", "--no-commit"))


@pytest.mark.bats("observe.bats", "observe reads body from stdin with --body -")
def test_observe_body_from_stdin(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "observe",
        "--title",
        "Stdin test",
        "--body",
        "-",
        "--no-commit",
        stdin="Piped body content\n",
    )
    _check(kb, golden, result)
    golden.check("file", _only_file(kb))


def test_observe_preserves_body_bytes(kb: KB, golden: Golden) -> None:
    body = "tab\there\n\nleading -n\n\\backslash\n\n\n"
    result = kb.run("observe", "--title", "Bytes", "--body", body, "--no-commit")
    _check(kb, golden, result)
    golden.check("file", _only_file(kb))


@pytest.mark.bats("observe.bats", "observe requires --body rather than silently reading stdin")
def test_observe_requires_body(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("observe", "--title", "No body", "--no-commit", stdin=""))


@pytest.mark.bats("observe.bats", "observe filenames carry enough entropy to avoid collisions")
def test_observe_file_names(kb: KB) -> None:
    for index in range(5):
        result = kb.run("observe", "--title", f"T{index}", "--body", "B", "--no-commit")
        assert result.returncode == 0
    names = _pending(kb)
    assert len(names) == 5
    for name in names:
        assert OBSERVATION_NAME.fullmatch(name), name


@pytest.mark.bats("observe.bats", "observe escapes quotes in title")
def test_observe_escapes_title(kb: KB, golden: Golden) -> None:
    result = kb.run("observe", "--title", 'Say "hello" \\ there', "--body", "Body")
    _check(kb, golden, result)
    golden.check("file", _only_file(kb))


@pytest.mark.bats("observe.bats", "observe leaves nothing in pending when the lock wait expires")
def test_observe_lock_wait_expires(kb: KB, golden: Golden) -> None:
    with kb.hold_lock():
        result = kb.run(
            "observe", "--title", "Blocked", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "0"}
        )
        # The lock belongs to a live process and must survive.
        assert (kb.layout.content / ".observe.lock" / "pid").is_file()
    _check(kb, golden, result)


@pytest.mark.bats("observe.bats", "observe waits up to KNOWLEDGE_LOCK_WAIT seconds")
def test_observe_lock_wait_bound(kb: KB) -> None:
    with kb.hold_lock():
        start = time.monotonic()
        result = kb.run(
            "observe", "--title", "Blocked", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "1"}
        )
        elapsed = time.monotonic() - start
    assert result.returncode == 1
    assert 1 <= elapsed < 3, elapsed


@pytest.mark.bats("observe.bats", "observe rejects a non-numeric KNOWLEDGE_LOCK_WAIT")
def test_observe_rejects_bad_lock_wait(kb: KB, golden: Golden) -> None:
    result = kb.run(
        "observe", "--title", "T", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "soon"}
    )
    _check(kb, golden, result)


@pytest.mark.bats("observe.bats", "observe removes its temporary files and lock after committing")
def test_observe_cleans_up(kb: KB, golden: Golden) -> None:
    result = kb.run("observe", "--title", "Clean", "--body", "-", stdin="Body\n")
    _check(kb, golden, result)
    assert list(kb.layout.tmp.iterdir()) == []
    assert not (kb.layout.content / ".observe.lock").exists()
    golden.check("content", kb.norm(tree(kb.layout.content)))


def test_observe_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("observe", "--bogus"))

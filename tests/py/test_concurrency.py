"""Concurrent writers and the .observe.lock protocol: outcomes, not timing."""

from __future__ import annotations

import subprocess
import time

import pytest

from kbtest import impl as implmod
from kbtest.runner import KB

# A-041: the Bash lock break races with a new owner, so these outcome tests
# fail intermittently under bash. Any other implementation must pass them.
BASH_LOCK_RACE = pytest.mark.xfail(
    implmod.selected_name() == "bash",
    reason="A-041: breaking a stale lock can delete a live owner's lock",
    strict=False,
)

WRITERS = 5


def _observations(kb: KB) -> list[str]:
    return sorted(p.name for p in (kb.layout.content / "observations" / "pending").glob("*.md"))


@pytest.mark.audit("A-038")
@pytest.mark.audit("A-041")
@BASH_LOCK_RACE
@pytest.mark.parametrize("attempt", range(20))
def test_concurrent_observe_loses_nothing(kb: KB, attempt: int) -> None:
    tree = kb.resolve_impl(kb.default_impl)
    env = kb.env(tree)
    processes = [
        subprocess.Popen(
            [str(tree.executable("observe")), "--title", f"Writer {n}", "--body", f"Body {n}"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for n in range(WRITERS)
    ]
    outcomes = [
        (p.wait(timeout=120), p.stderr.read().decode() if p.stderr else "") for p in processes
    ]
    assert all(code == 0 for code, _ in outcomes), outcomes
    assert len(_observations(kb)) == WRITERS
    subjects = kb.git("log", "--format=%s").splitlines()
    assert sorted(subjects[:-1]) == sorted(f"Observe: Writer {n}" for n in range(WRITERS))
    assert kb.git("status", "--porcelain") == ""
    assert not (kb.layout.content / ".observe.lock").exists()


RACERS = 8


@pytest.mark.audit("A-041")
@BASH_LOCK_RACE
@pytest.mark.parametrize("attempt", range(10))
def test_stale_lock_race_loses_nothing(kb: KB, attempt: int) -> None:
    """Writers that all find a dead owner's lock break it once, not each other's."""
    finished = subprocess.Popen(["true"])
    finished.wait()
    lock = kb.layout.content / ".observe.lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{finished.pid}\n", encoding="utf-8")
    tree = kb.resolve_impl(kb.default_impl)
    env = kb.env(tree)
    processes = [
        subprocess.Popen(
            [str(tree.executable("observe")), "--title", f"Racer {n}", "--body", "Body"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for n in range(RACERS)
    ]
    outcomes = [
        (p.wait(timeout=120), p.stderr.read().decode() if p.stderr else "") for p in processes
    ]
    assert all(code == 0 for code, _ in outcomes), outcomes
    assert len(_observations(kb)) == RACERS
    assert kb.git("status", "--porcelain") == ""
    assert not lock.exists()


def test_lock_from_dead_process_is_broken(kb: KB) -> None:
    finished = subprocess.Popen(["true"])
    finished.wait()
    lock = kb.layout.content / ".observe.lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{finished.pid}\n", encoding="utf-8")
    start = time.monotonic()
    result = kb.run(
        "observe", "--title", "After crash", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "5"}
    )
    assert result.returncode == 0, result.err
    assert time.monotonic() - start < 5, "a dead owner's lock is broken, not waited out"
    assert len(_observations(kb)) == 1
    assert not lock.exists()


def test_held_lock_times_out_within_bound(kb: KB) -> None:
    with kb.hold_lock():
        start = time.monotonic()
        result = kb.run(
            "observe", "--title", "Blocked", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "2"}
        )
        elapsed = time.monotonic() - start
        assert (kb.layout.content / ".observe.lock" / "pid").is_file()
    assert result.returncode == 1 and result.err.strip()
    assert 2 <= elapsed < 5, elapsed
    assert _observations(kb) == []


@pytest.mark.audit("A-037")
def test_lock_without_pid_is_never_broken(kb: KB) -> None:
    (kb.layout.content / ".observe.lock").mkdir()
    start = time.monotonic()
    result = kb.run(
        "observe", "--title", "Blocked", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "1"}
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 1 and result.err.strip()
    assert elapsed >= 1
    assert (kb.layout.content / ".observe.lock").is_dir()
    assert _observations(kb) == []


def test_lock_released_after_each_writer(kb: KB) -> None:
    for name in ("observe", "ask"):
        args = ["--title", "T", "--body", "B"] if name == "observe" else ["--title", "Q?"]
        assert kb.run(name, *args).returncode == 0
        assert not (kb.layout.content / ".observe.lock").exists(), name
    assert len(_observations(kb)) == 1
    assert len(list((kb.layout.content / "questions" / "open").glob("*.md"))) == 1
    assert len(kb.commits()) == 3

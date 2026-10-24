"""Concurrent writers and the .observe.lock protocol: outcomes, not timing."""

from __future__ import annotations

import os
import subprocess
import time

import pytest

from kbtest.marks import xfail_bash
from kbtest.runner import KB

# A lock directory with no pid file and an mtime this old has lost its owner.
STALE_PIDLESS_SECONDS = 60

WRITERS = 5


def _observations(kb: KB) -> list[str]:
    return sorted(p.name for p in (kb.layout.content / "observations" / "pending").glob("*.md"))


@pytest.mark.parametrize("attempt", range(20))
def test_concurrent_observe_loses_nothing(kb: KB, attempt: int) -> None:
    tree = kb.resolve_impl(kb.default_impl)
    env = kb.env(tree)
    processes = [
        subprocess.Popen(
            [str(kb.executable("observe")), "--title", f"Writer {n}", "--body", f"Body {n}"],
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
            [str(kb.executable("observe")), "--title", f"Racer {n}", "--body", "Body"],
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


def test_fresh_lock_without_pid_is_respected(kb: KB) -> None:
    """A lock just created, before its owner writes the pid, is held (A-037)."""
    (kb.layout.content / ".observe.lock").mkdir()
    result = kb.run(
        "observe", "--title", "Blocked", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "1"}
    )
    assert result.returncode == 1 and result.err.strip()
    assert (kb.layout.content / ".observe.lock").is_dir()
    assert _observations(kb) == []


@xfail_bash("A-037: bash never breaks a lock without a pid file")
def test_old_lock_without_pid_is_broken(kb: KB) -> None:
    """An owner killed between mkdir and writing its pid leaves a lock to break."""
    lock = kb.layout.content / ".observe.lock"
    lock.mkdir()
    then = time.time() - 2 * STALE_PIDLESS_SECONDS
    os.utime(lock, (then, then))
    result = kb.run(
        "observe", "--title", "After crash", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "5"}
    )
    assert result.returncode == 0, result.err
    assert len(_observations(kb)) == 1
    assert not lock.exists()


def test_stale_lock_is_broken_only_under_the_guard(kb: KB) -> None:
    """Breaking is serialized by .observe.lock.break, shared by every implementation (A-041)."""
    finished = subprocess.Popen(["true"])
    finished.wait()
    lock = kb.layout.content / ".observe.lock"
    lock.mkdir()
    (lock / "pid").write_text(f"{finished.pid}\n", encoding="utf-8")
    guard = kb.layout.content / ".observe.lock.break"
    guard.mkdir()
    held = kb.run(
        "observe", "--title", "Guarded", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "1"}
    )
    assert held.returncode == 1 and held.err.strip()
    assert (lock / "pid").is_file(), "another breaker holds the guard"
    guard.rmdir()
    freed = kb.run(
        "observe", "--title", "Freed", "--body", "Body", env={"KNOWLEDGE_LOCK_WAIT": "5"}
    )
    assert freed.returncode == 0, freed.err
    assert not lock.exists() and not guard.exists()
    assert len(_observations(kb)) == 1


def test_lock_released_after_each_writer(kb: KB) -> None:
    for name in ("observe", "ask"):
        args = ["--title", "T", "--body", "B"] if name == "observe" else ["--title", "Q?"]
        assert kb.run(name, *args).returncode == 0
        assert not (kb.layout.content / ".observe.lock").exists(), name
    assert len(_observations(kb)) == 1
    assert len(list((kb.layout.content / "questions" / "open").glob("*.md"))) == 1
    assert len(kb.commits()) == 3

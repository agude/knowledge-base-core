"""The .observe.lock protocol shared with the bash writers.

A writer holds the lock while it publishes and commits files, so commits
from concurrent writers never interleave. The lock is a directory, created
atomically by mkdir, holding a `pid` file with the owner's pid.

A stale lock is broken only while holding the guard directory
`.observe.lock.break`, and only if it still shows the state that was found
stale: the same dead pid, or (audit A-037) no pid file and an age over
PIDLESS_STALE_SECONDS. A writer that took the lock in between writes its
own pid into a directory it just created, so its lock never matches.
Bash's break_stale_lock in scripts/_lib.sh follows the same rules for a
dead pid (audit A-041).
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kb import platform
from kb.content import nonnegative

POLL_SECONDS = 0.05
PIDLESS_STALE_SECONDS = 60
DEFAULT_WAIT = "30"


class LockTimeout(Exception):
    pass


def _owner(lock: Path) -> str | None:
    """The pid file's content, or None when there is no pid file."""
    try:
        return (lock / "pid").read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return None


def _stale(lock: Path) -> tuple[str, str] | None:
    """What makes the lock stale, as a state to recheck, or None if it is live."""
    owner = _owner(lock)
    if owner is None:
        try:
            age = time.time() - lock.stat().st_mtime
        except FileNotFoundError:
            return None
        return ("pidless", "") if age > PIDLESS_STALE_SECONDS else None
    if owner.isdigit() and not platform.process_alive(int(owner)):
        return ("dead", owner)
    return None


def _break(lock: Path, found: tuple[str, str]) -> bool:
    """Remove lock if it still shows the stale state found; False if the guard is busy."""
    guard = lock.with_name(lock.name + ".break")
    try:
        guard.mkdir()
    except FileExistsError:
        return False
    try:
        if _stale(lock) == found:
            shutil.rmtree(lock, ignore_errors=True)
    finally:
        guard.rmdir()
    return True


def acquire(content: Path) -> Path:
    """Take the lock, waiting up to KNOWLEDGE_LOCK_WAIT seconds."""
    lock = content / ".observe.lock"
    wait = nonnegative("KNOWLEDGE_LOCK_WAIT", os.environ.get("KNOWLEDGE_LOCK_WAIT", DEFAULT_WAIT))
    deadline = time.monotonic() + wait
    while True:
        try:
            lock.mkdir()
        except FileExistsError:
            found = _stale(lock)
            if found is not None and _break(lock, found):
                continue
            if time.monotonic() >= deadline:
                raise LockTimeout("Could not acquire lock") from None
            time.sleep(POLL_SECONDS)
            continue
        platform.write_text(lock / "pid", f"{os.getpid()}\n")
        return lock


def release(lock: Path) -> None:
    shutil.rmtree(lock, ignore_errors=True)


@contextmanager
def held(content: Path) -> Iterator[Path]:
    """Hold the lock for the block; release it however the block ends."""
    lock = acquire(content)
    try:
        yield lock
    finally:
        release(lock)


def report_timeout(error: LockTimeout) -> int:
    print(error, file=sys.stderr)
    return 1

"""Running git in the content repository."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from kb import platform

STALE_INDEX_LOCK_SECONDS = 5 * 60


def run(repo: Path, *args: str) -> int:
    """Run git in repo with inherited output; return its exit status."""
    return subprocess.run(["git", *args], cwd=repo, check=False).returncode


def break_stale_index_lock(repo: Path) -> None:
    """Remove .git/index.lock when it is old and no git process holds it.

    The lock survives a killed git. Removing a live one would corrupt the
    index, so it must be older than five minutes and no git process may be
    running in repo (audit A-003).
    """
    lock = repo / ".git" / "index.lock"
    try:
        age = time.time() - lock.stat().st_mtime
    except FileNotFoundError:
        return
    if age <= STALE_INDEX_LOCK_SECONDS or platform.git_running_in(repo):
        return
    lock.unlink(missing_ok=True)
    print(f"Removed stale git lock: {lock}", file=sys.stderr)


def commit_paths(repo: Path, message: str, paths: list[str]) -> int:
    """Commit only the named paths; the caller holds the observe lock.

    A pathspec commit leaves anything else staged or modified alone.
    """
    status = 0
    for path in paths:
        status = run(repo, "add", path)
        if status:
            break
    if not status:
        status = run(repo, "commit", "-q", "-m", message, "--", *paths)
    if status:
        print(f"locked_commit: commit failed ({status}) for: {message}", file=sys.stderr)
    return status


def commit_index(repo: Path, message: str, paths: list[str]) -> int:
    """Stage every change under paths and commit the whole index.

    A whole-index commit keeps the pre-commit hook's `updated:` stamping,
    which a pathspec commit would discard. The caller holds the lock.
    """
    status = 0
    for path in paths:
        status = run(repo, "add", "-A", path)
        if status:
            break
    if not status:
        status = run(repo, "commit", "-q", "-m", message)
    if status:
        print(f"locked_commit_index: commit failed ({status}) for: {message}", file=sys.stderr)
    return status

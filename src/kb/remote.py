"""Fetch, rebase, and push the content repository's current branch against origin.

Callers hold the writer lock. This module takes no lock and never stages or
commits. Each function reports what it did; a failure names the Git step that
stopped it.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kb.errors import KbError


@dataclass(frozen=True)
class RemoteStatus:
    """The current branch's ahead and behind counts after fetching origin."""

    branch: str
    ahead: int
    behind: int


@dataclass(frozen=True)
class Result:
    """What one synchronization step did.

    pulled counts commits rebased from origin, and pushed counts local commits sent
    to origin. skipped_dirty lists the changed paths that stopped the step before any
    fetch. errors holds one message per failure. A rebase conflict is aborted, so the
    local commits stay in place.
    """

    pulled: int = 0
    pushed: int = 0
    already_in_sync: bool = False
    skipped_dirty: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def dirty_paths(root: Path) -> tuple[str, ...]:
    """Paths changed in the worktree or index."""
    result = _git(root, "status", "--porcelain", "--untracked-files=all")
    if result.returncode != 0:
        detail = result.stderr.rstrip("\n")
        raise KbError(f"cannot inspect working tree: {detail}")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return tuple(paths)


def fetch_status(root: Path) -> tuple[RemoteStatus | None, str | None]:
    """Fetch origin's current branch and calculate ahead/behind without moving HEAD."""
    branch_result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch_result.returncode != 0:
        return None, "sync: current branch is detached"
    branch = branch_result.stdout.strip()
    remote = _git(root, "remote", "get-url", "origin")
    if remote.returncode != 0:
        return None, "sync: no origin remote"
    fetched = _git(root, "fetch", "--no-write-fetch-head", "origin", branch)
    if fetched.returncode != 0:
        detail = fetched.stderr.rstrip("\n")
        return None, f"sync: fetch origin/{branch} failed: {detail}"
    remote_ref = f"refs/remotes/origin/{branch}"
    exists = _git(root, "show-ref", "--verify", "--quiet", remote_ref)
    if exists.returncode != 0:
        return None, f"sync: origin/{branch} does not exist"
    counts = _git(root, "rev-list", "--left-right", "--count", f"HEAD...{remote_ref}")
    if counts.returncode != 0:
        detail = counts.stderr.rstrip("\n")
        return None, f"sync: cannot compare with origin/{branch}: {detail}"
    values = counts.stdout.split()
    if len(values) != 2 or not all(value.isascii() and value.isdigit() for value in values):
        return None, f"sync: git returned invalid ahead/behind counts for origin/{branch}"
    return RemoteStatus(branch, int(values[0]), int(values[1])), None


def integrate(root: Path, remote: RemoteStatus, *, push: bool) -> Result:
    """Rebase onto origin's branch when behind, then push local commits when ahead.

    The caller has checked that the worktree is clean. A rebase conflict is aborted, and
    no push follows it.
    """
    target = f"origin/{remote.branch}"
    if remote.ahead == 0 and remote.behind == 0:
        return Result(already_in_sync=True)
    pulled = 0
    if remote.behind:
        rebased = _git(root, "rebase", target)
        if rebased.returncode != 0:
            _git(root, "rebase", "--abort")
            return Result(errors=(f"sync: rebase onto {target} failed; local commits kept",))
        pulled = remote.behind
    if not (remote.ahead and push):
        return Result(pulled=pulled)
    pushed = _git(root, "push", "origin", remote.branch)
    if pushed.returncode != 0:
        detail = pushed.stderr.rstrip("\n")
        return Result(
            pulled=pulled,
            errors=(f"sync: push origin/{remote.branch} failed: {detail}",),
        )
    return Result(pulled=pulled, pushed=remote.ahead)


def synchronize(root: Path, *, push: bool) -> Result:
    """Refuse a dirty worktree, fetch origin, then integrate the current branch."""
    dirty = dirty_paths(root)
    if dirty:
        return Result(skipped_dirty=dirty)
    remote, error = fetch_status(root)
    if error is not None:
        return Result(errors=(error,))
    assert remote is not None
    return integrate(root, remote, push=push)


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run one Git command in the content repository."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

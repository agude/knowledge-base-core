"""sync - Bring the content repo in line with its remote.

Observations accumulate on whichever machine ran the session, and each
machine commits them locally. Curation can only see what has reached
one place, so the workflow is: sync on every machine, then curate on
one. Doing that by hand is three commands and a decision about rebase
vs merge; this is one command with the decision already made.

Rebase, not merge: observation filenames are timestamped and unique, so
concurrent machines never touch the same file and a rebase is always
clean. Merge commits would just add noise to a log that is already
mostly "Observe:".

Runs under the same lock as the capture scripts, so a session cannot
commit an observation in the middle of a rebase.

Usage:
  sync [--status] [--no-push]

Options:
  --status     Report what is ahead or behind; change nothing
  --no-push    Pull only

Exit status:
  0  in sync (or successfully synced)
  1  could not sync — uncommitted work, no remote, unverifiable remote,
     or a failed rebase

Examples:
  sync              # pull, then push
  sync --status     # what would it do?
  sync --no-push    # pull, but leave local commits unpushed
"""

from __future__ import annotations

import compileall
import re
import subprocess
import sys
from pathlib import Path

from kb import cli, git, lock, platform
from kb.content import ROOT, content_dir


class Stop(Exception):
    """Sync cannot proceed; the message, if any, was printed or is printed now."""


def _out(content: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=content, capture_output=True, text=True, check=False)


def _assert_clean(content: Path) -> None:
    status = _out(
        content,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude).observe.lock",
    )
    if status.returncode != 0:
        raise Stop(f"Could not inspect the worktree in {content}.")
    if status.stdout.strip("\n"):
        lines = status.stdout.rstrip("\n").split("\n")
        raise Stop(
            f"Uncommitted changes in {content} — commit or stash first:\n" + "\n".join(lines[:10])
        )


def sync(content: Path, status_only: bool, push: bool) -> int:
    if _out(content, "remote", "get-url", "origin").returncode != 0:
        raise Stop(f"No 'origin' remote on {content} — nothing to sync.")
    head = _out(content, "rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode != 0:
        raise Stop(f"Could not determine the current branch in {content}.")
    branch = head.stdout.strip()
    _assert_clean(content)
    if git.run(content, "fetch", "--quiet", "origin", branch) != 0:
        raise Stop(f"Fetch failed; remote state could not be verified for origin/{branch}.")
    remote = f"refs/remotes/origin/{branch}"
    if _out(content, "rev-parse", "--verify", "--quiet", remote).returncode != 0:
        raise Stop(
            f"Remote branch origin/{branch} is unavailable; remote state could not be verified."
        )
    counts = _out(content, "rev-list", "--left-right", "--count", f"{remote}...HEAD")
    if counts.returncode != 0:
        raise Stop(
            "Could not compare local and remote history; remote state could not be verified."
        )
    parts = counts.stdout.split()
    if len(parts) != 2 or not all(re.fullmatch(r"\d+", p) for p in parts):
        raise Stop("Could not parse local and remote history; remote state could not be verified.")
    behind, ahead = int(parts[0]), int(parts[1])
    # Recheck: an observation written during the fetch must not look in sync.
    _assert_clean(content)
    if status_only:
        print(
            f"In sync with origin/{branch}."
            if not ahead and not behind
            else f"{ahead} to push, {behind} to pull (origin/{branch})."
        )
        return 0
    if not ahead and not behind:
        print(f"Already in sync with origin/{branch}.")
        return 0
    status = 0
    if behind:
        _assert_clean(content)
        print(f"Pulling {behind} commit(s)...", flush=True)
        status = git.run(content, "rebase", "--quiet", remote)
        if status:
            # The rebase stays in place: aborting would hide the conflict.
            print(f"Rebase failed. Resolve it in {content}, then run sync again.", file=sys.stderr)
    if not status and push:
        try:
            _assert_clean(content)
        except Stop as error:
            print(error, file=sys.stderr)
            return 1
        pushing = _out(content, "rev-list", "--count", f"{remote}..HEAD")
        if pushing.returncode != 0 or not re.fullmatch(r"\d+", pushing.stdout.strip()):
            print(
                "Could not determine commits to push; remote state could not be verified.",
                file=sys.stderr,
            )
            return 1
        if int(pushing.stdout):
            print(f"Pushing {int(pushing.stdout)} commit(s)...", flush=True)
            status = git.run(content, "push", "--quiet", "origin", branch)
    if status:
        return 1
    print(f"Synced {content} with origin/{branch}.")
    return 0


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(argv, __doc__, flags={"--status": "status", "--no-push": "no-push"})
    content = content_dir()
    if not (content / ".git").is_dir():
        cli.fail(f"Not a git repository: {content}")
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            status = sync(content, "status" in args.flags, "no-push" not in args.flags)
    except lock.LockTimeout as error:
        return lock.report_timeout(error)
    except Stop as error:
        print(error, file=sys.stderr)
        return 1
    # So the first hook after an update does not compile kb (plan 4.16).
    compileall.compile_dir(str(ROOT / "kb"), quiet=1)
    return status

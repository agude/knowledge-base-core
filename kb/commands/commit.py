"""commit - Commit curation work in the content repo.

Stages knowledge/, observations/, questions/ and sources/, then commits
them under the same lock the capture scripts use, so an observe firing
mid-run cannot interleave with a half-staged curation pass.

Use this instead of a bare `git commit`:

  - It finds the content repo through KB_CONTENT_DIR rather than
    assuming the caller is standing in ./content.
  - It takes the lock. `git commit` does not.
  - It commits the whole index, so the pre-commit hook's `updated:`
    stamping lands in the same commit. A pathspec commit would silently
    discard it.

Usage:
  commit -m "Curate: <summary>"

Options:
  -m, --message TEXT   Commit message (required)

Examples:
  commit -m "Curate: smoke alarms, front door hardware"
"""

from __future__ import annotations

import subprocess

from kb import cli, git, lock, platform
from kb.content import content_dir

AREAS = ("knowledge", "observations", "questions", "sources")


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(argv, __doc__, values={"-m": "message", "--message": "message"})
    message = args.get("message")
    if not message:
        cli.fail("Error: -m is required")
    content = content_dir()
    if not (content / ".git").is_dir():
        cli.fail(f"Not a git repository: {content}")
    # Only the four content areas are curation work (audit A-009).
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *AREAS],
        cwd=content,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode == 0 and not status.stdout.strip():
        print("Nothing to commit.")
        return 0
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            code = git.commit_index(content, message, [a for a in AREAS if (content / a).exists()])
    except lock.LockTimeout as error:
        return lock.report_timeout(error)
    if code:
        return code
    print(f"Committed: {message}")
    return 0

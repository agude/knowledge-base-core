"""init - Initialize an empty content repository.

Creates the content directory structure and initializes a git repo.
Safe to run if content/ already exists — skips what's already there.

Usage:
  init [--path DIR]

Options:
  --path DIR   Where to create the content repo (default: ./content)

Examples:
  init                          # creates ./content/
  init --path ~/my-kb-content   # creates at custom path
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from kb import cli, platform
from kb.commands import install
from kb.content import content_dir

DIRS = (
    "knowledge",
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
    "sources",
)


def _git(target: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(target), *args], capture_output=True, text=True, check=check
    )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(argv, __doc__, values={"--path": "path"})
    target = Path(args.get("path")) if args.get("path") else content_dir()
    print(f"Initializing content directory: {target}")
    for name in DIRS:
        directory = target / name
        if directory.is_dir():
            print(f"  exists: {name}/")
        else:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"  created: {name}/")
    if (target / ".git").is_dir():
        print("  git: already initialized")
    else:
        _git(target, "init", "-q")
        print("  git: initialized")
        # A default identity for CI runners and fresh machines.
        if _git(target, "config", "user.name", check=False).returncode != 0:
            _git(target, "config", "user.name", "Knowledge Base")
            _git(target, "config", "user.email", "kb@localhost")
        for name in DIRS:
            (target / name / ".gitkeep").touch()
        _git(target, "add", ".")
        _git(target, "commit", "-q", "-m", "Init content repo")
        print("  git: initial commit")
    sys.stdout.flush()
    # Wire the repository just created, not the configured one (audit A-008).
    install.install(Path(sys.argv[0]).resolve().parent, target)
    return 0

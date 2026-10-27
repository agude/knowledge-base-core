"""Runs kb as a process against a copy of the content fixture.

Tests in this package import nothing from kb. They check stdout, stderr, and
the exit status.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FIXTURE_CONTENT = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = "2026-10-26"
# Git reads no user or system configuration, and every commit gets this identity.
GIT_ISOLATION = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.invalid",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@example.invalid",
}


def run_git(repo: Path, *args: str) -> str:
    """Run git in repo, isolated from the user's configuration, and return its stdout.

    Raises CalledProcessError when git exits non-zero.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(repo), **GIT_ISOLATION},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    return result.stdout


@dataclass(frozen=True)
class Kb:
    """One test's kb: a home directory, a content repository, and a fixed clock."""

    home: Path
    content: Path

    def environment(self, overrides: Mapping[str, str | None]) -> dict[str, str]:
        """The process environment; a None override removes the variable."""
        env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", ""),
            "XDG_CONFIG_HOME": str(self.home / "xdg"),
            "KB_CONTENT": str(self.content),
            "KB_TODAY": TODAY,
            "KB_LOCK_WAIT": "1",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            **GIT_ISOLATION,
        }
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        return env

    def __call__(
        self,
        *args: str,
        env: Mapping[str, str | None] | None = None,
        stdin: str | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run `kb ARGS` and capture its output. The working directory defaults to home."""
        return subprocess.run(
            [sys.executable, "-m", "kb", *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            cwd=self.home if cwd is None else cwd,
            env=self.environment(env or {}),
            timeout=60,
        )

    def git(self, *args: str) -> str:
        """Run git in the content repository and return its stdout."""
        return run_git(self.content, *args)


def make_kb(root: Path) -> Kb:
    """A kb whose home and content repository live under root."""
    home = root / "home"
    (home / "xdg").mkdir(parents=True)
    content = root / "content"
    shutil.copytree(FIXTURE_CONTENT, content)
    return Kb(home=home, content=content)


def make_git_kb(root: Path) -> Kb:
    """A kb whose content repository is a git repository with the fixture as its only commit."""
    kb = make_kb(root)
    run_git(kb.content, "init", "-q", "-b", "main")
    run_git(kb.content, "add", "--all")
    run_git(kb.content, "commit", "-q", "-m", "Import the content fixture")
    return kb

"""Review regressions for the existing commit-outcome guard."""

import subprocess
from pathlib import Path

import pytest

from kb import write
from kb.errors import KbError


def git(root: Path, *words: str) -> str:
    return subprocess.run(
        ["git", *words], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def make_repo(root: Path) -> Path:
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Review Test")
    git(root, "config", "user.email", "review@example.invalid")
    return root


def test_snapshot_refuses_a_committed_subdirectory_path(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")
    nested = root / "content"
    nested.mkdir()
    path = nested / "record.md"
    path.write_text("committed\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Seed")
    before = git(root, "write-tree")

    with pytest.raises(KbError, match="existing HEAD path"):
        write._commit_snapshot(nested, "record.md", "observe")

    assert path.read_text() == "committed\n"
    assert git(root, "write-tree") == before


def test_a_rejected_initial_commit_rolls_back_its_new_path(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho rejected >&2\nexit 1\n")
    hook.chmod(0o755)
    path = root / "record.md"
    path.write_text("new record\n")

    with pytest.raises(KbError, match="commit failed: rejected"):
        write._commit(root, "record.md", "Observe: initial", "observe")

    assert not path.exists()
    assert git(root, "ls-files") == ""

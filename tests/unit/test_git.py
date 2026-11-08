"""The shared Git runner, exercised against real repositories."""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from kb import git


def make_repo(root: Path) -> Path:
    root.mkdir()
    for words in (
        ("init", "-q"),
        ("config", "user.name", "Git Test"),
        ("config", "user.email", "git@example.invalid"),
        ("config", "core.autocrlf", "false"),
    ):
        subprocess.run(["git", *words], cwd=root, check=True, capture_output=True)
    return root


def commit(root: Path, name: str, content: bytes) -> None:
    (root / name).write_bytes(content)
    subprocess.run(["git", "add", "--", name], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "Add"], cwd=root, check=True, capture_output=True)


def test_run_returns_text_output(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")
    commit(root, "é.md", b"text\n")

    result = git.run(root, "-c", "core.quotePath=false", "ls-files", "-z")

    assert result.returncode == 0
    assert "é.md" in result.stdout.split("\0")


def test_run_bytes_keeps_crlf_bytes(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")
    commit(root, "f.txt", b"a\r\nb\r\n")

    assert git.run_bytes(root, "show", "HEAD:f.txt").stdout == b"a\r\nb\r\n"


def test_read_only_sets_optional_locks_without_changing_os_environ(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")

    read_only = git._environment(True)
    assert read_only is not None
    assert read_only["GIT_OPTIONAL_LOCKS"] == "0"
    assert git._environment(False) is None
    assert "GIT_OPTIONAL_LOCKS" not in os.environ
    assert git.run(root, "status", "--porcelain", read_only=True).returncode == 0
    assert "GIT_OPTIONAL_LOCKS" not in os.environ


def test_input_text_and_input_bytes_reach_git(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")

    text = git.run(root, "hash-object", "--stdin", input_text="same content\n")
    raw = git.run_bytes(root, "hash-object", "--stdin", input_bytes=b"same content\n")

    assert text.returncode == 0
    assert text.stdout.strip() == raw.stdout.decode("ascii").strip()


def test_nonzero_exit_returns_a_result(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")

    result = git.run(root, "rev-parse", "--verify", "no-such-ref")

    assert result.returncode != 0


def test_run_sends_input_text_as_exact_utf8_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    sent: list[object] = []
    real_run = subprocess.run

    def record(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        sent.append(kwargs.get("input"))
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", record)

    git.run(root, "hash-object", "--stdin", input_text="é\nb\n")

    assert sent == ["é\nb\n".encode()]


def test_run_translates_output_newlines_like_text_mode(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo")
    commit(root, "f.txt", b"a\r\nb\rc\n")

    assert git.run(root, "show", "HEAD:f.txt").stdout == "a\nb\nc\n"

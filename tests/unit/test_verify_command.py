"""Tests of verify's locked, atomic, and non-Git write path."""

import subprocess
import sys
from pathlib import Path

import pytest

from kb import lock, secrets
from kb.commands import verify
from kb.errors import KbError


def _content(root: Path) -> tuple[Path, Path]:
    content = root / "content"
    subprocess.run(["git", "init", "-q", str(content)], check=True)
    article = content / "knowledge" / "article.md"
    article.parent.mkdir()
    article.write_text(
        "---\ntitle: Article\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\n---\n# Article\n",
        encoding="utf-8",
    )
    return content, article


def _environment(content: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KB_CONTENT", str(content))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    monkeypatch.setenv("KB_LOCK_WAIT", "0")


def test_checks_ttl_without_scanning_and_uses_the_common_git_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content, article = _content(tmp_path)
    _environment(content, monkeypatch)
    scanned: list[tuple[Path, str]] = []

    def scan(directory: Path, text: str) -> list[tuple[str, int]]:
        scanned.append((directory, text))
        return []

    git_calls: list[tuple[Path, str]] = []

    def common_directory(root: Path, command: str) -> Path:
        git_calls.append((root, command))
        return root / ".git"

    monkeypatch.setattr(secrets, "findings", scan)
    monkeypatch.setattr(lock, "git_dir", common_directory)

    status = verify.run(["knowledge/article.md"])

    assert status == 0
    assert capsys.readouterr().out == "Verified: knowledge/article.md (ttl domain)\n"
    assert scanned == []
    assert git_calls == [(content, "verify")]
    assert b"verified: 2026-10-26" in article.read_bytes()
    assert list((content / ".git" / "kb-tmp").iterdir()) == []


def test_invalid_stored_ttl_is_refused_before_mutation_or_scanning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content, article = _content(tmp_path)
    _environment(content, monkeypatch)
    article.write_bytes(article.read_bytes().replace(b"ttl: domain", b"ttl: weekly"))
    before = article.read_bytes()
    scans: list[Path] = []

    def scan(directory: Path, text: str) -> list[tuple[str, int]]:
        scans.append(directory)
        return []

    monkeypatch.setattr(secrets, "findings", scan)

    with pytest.raises(KbError, match="no valid ttl"):
        verify.run(["knowledge/article.md"])

    assert capsys.readouterr().out == ""
    assert scans == []
    assert article.read_bytes() == before
    assert not (content / ".git" / "kb-tmp").exists()


def test_handled_publication_error_cleans_the_temp_file_and_releases_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content, article = _content(tmp_path)
    _environment(content, monkeypatch)
    before = article.read_bytes()
    monkeypatch.setattr(secrets, "findings", lambda *_: [])

    def fail_replace(self: Path, target: str | Path) -> Path:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(KbError, match="synthetic replace failure"):
        verify.run(["knowledge/article.md"])

    scratch = content / ".git" / "kb-tmp"
    assert list(scratch.iterdir()) == []
    assert article.read_bytes() == before
    with lock.write_lock(content / ".git", 0, lock.default_backend(sys.platform)):
        pass


def test_interruption_cleans_the_temp_file_and_releases_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content, article = _content(tmp_path)
    _environment(content, monkeypatch)
    before = article.read_bytes()
    monkeypatch.setattr(secrets, "findings", lambda *_: [])

    def interrupt(self: Path, target: str | Path) -> Path:
        raise KeyboardInterrupt

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "replace", interrupt)
        with pytest.raises(KeyboardInterrupt):
            verify.run(["knowledge/article.md"])

    scratch = content / ".git" / "kb-tmp"
    assert list(scratch.iterdir()) == []
    assert article.read_bytes() == before
    assert verify.run(["knowledge/article.md"]) == 0

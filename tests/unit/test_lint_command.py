"""Tests for `kb lint` path handling and read-only behavior."""

import shutil
import socket
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from kb import corpus, lock
from kb.commands import lint as lint_command
from kb.model import Document

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file under a content root and its bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_run_parses_each_path_once_and_does_not_write_or_use_external_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = tmp_path / "content"
    shutil.copytree(FIXTURE, content)
    source = content / "knowledge" / "rules" / "backups.md"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n[existing](../infra/nas.md#1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KB_CONTENT", str(content))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    before = _tree_bytes(content)
    parsed: list[str] = []
    read_document = corpus.read_document

    def track_read(root: Path, relpath: str) -> Document:
        parsed.append(relpath)
        return read_document(root, relpath)

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("kb lint must not call Git, acquire locks, or use the network")

    monkeypatch.setattr(corpus, "read_document", track_read)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(lock, "acquire_kernel", forbidden)
    monkeypatch.setattr(lock, "take_legacy_lock", forbidden)

    result = lint_command.run(["knowledge/rules/backups.md", "knowledge/rules/backups.md"])

    assert result == 0
    assert parsed == ["knowledge/rules/backups.md", "knowledge/infra/nas.md"]
    assert capsys.readouterr().out == "Lint: 0 errors, 0 warnings in 1 file(s)\n"
    assert _tree_bytes(content) == before


def test_each_reference_target_is_parsed_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    content = tmp_path / "content"
    knowledge = content / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "target.md").write_text(
        "---\ntitle: Target\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
        "# Target\n## Section\nText.\n",
        encoding="utf-8",
    )
    (knowledge / "source.md").write_text(
        "---\ntitle: Source\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n"
        "sources:\n  - knowledge/target.md#1\n  - knowledge/target.md#Section\n---\n"
        "# Source\n[one](target.md#1)\n[two](target.md#Section)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KB_CONTENT", str(content))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    parsed: list[str] = []
    read_document = corpus.read_document

    def track_read(root: Path, relpath: str) -> Document:
        parsed.append(relpath)
        return read_document(root, relpath)

    monkeypatch.setattr(corpus, "read_document", track_read)

    result = lint_command.run(["knowledge/source.md"])

    assert result == 0
    assert parsed == ["knowledge/source.md", "knowledge/target.md"]
    assert capsys.readouterr().out == "Lint: 0 errors, 0 warnings in 1 file(s)\n"

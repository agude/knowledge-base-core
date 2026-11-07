"""Rollback and cleanup behavior for kb resolve."""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from kb import lock, secrets
from kb.commands import resolve
from kb.context import Context


@pytest.mark.parametrize("failure", [OSError("injected"), KeyboardInterrupt()])
def test_failure_after_publication_restores_open_question_and_releases_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    root = tmp_path / "content"
    git = root / ".git"
    source = root / "questions" / "open" / "question.md"
    source.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    original = b"---\ntitle: Old\n---\n\nQuestion.\n"
    source.write_bytes(original)
    original_unlink = Path.unlink
    interrupted = False

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        nonlocal interrupted
        if path == source and not interrupted:
            interrupted = True
            original_unlink(path, missing_ok=missing_ok)
            raise failure
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    context = Context(root=root, today=date(2026, 10, 26))

    with pytest.raises(type(failure), match="injected" if isinstance(failure, OSError) else None):
        resolve._resolve(context, "questions/open/question.md", "Retired.", None, True, 0)

    assert source.read_bytes() == original
    assert not (root / "questions" / "resolved" / "question.md").exists()
    assert list((git / "kb-tmp").iterdir()) == []

    fd = os.open(git / lock.KERNEL_LOCK, os.O_RDWR)
    backend = lock.default_backend(sys.platform)
    try:
        assert backend.try_lock(fd)
        backend.unlock(fd)
    finally:
        os.close(fd)


def test_resolution_scans_in_common_scratch_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "content"
    git = root / ".git"
    source = root / "questions" / "open" / "question.md"
    source.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    original = b"---\ntitle: Old\n---\n\nQuestion.\n"
    source.write_bytes(original)
    context = Context(root, date(2026, 10, 26))
    seen: list[Path] = []
    original_findings = secrets.findings

    def track_scan(directory: Path, text: str) -> list[tuple[str, int]]:
        seen.append(directory)
        return original_findings(directory, text)

    monkeypatch.setattr(secrets, "findings", track_scan)

    result = resolve._resolve(context, "questions/open/question.md", "Retired.", None, True, 0)

    assert result == "questions/open/question.md"
    assert seen == [git / "kb-tmp"]
    assert not source.exists()
    assert (root / "questions" / "resolved" / "question.md").exists()
    assert list((git / "kb-tmp").iterdir()) == []

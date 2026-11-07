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
from kb.errors import KbError


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


@pytest.mark.parametrize("occupied_kind", ["race", "dangling"])
def test_resolution_publication_preserves_an_occupied_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, occupied_kind: str
) -> None:
    if occupied_kind == "dangling" and os.name == "nt":
        pytest.skip("symbolic links need privilege")
    root = tmp_path / "content"
    git = root / ".git"
    source = root / "questions" / "open" / "question.md"
    target = root / "questions" / "resolved" / "question.md"
    source.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    original = b"---\ntitle: Old\n---\n\nQuestion.\n"
    source.write_bytes(original)
    marker_directory = git / "kb-tmp"
    marker_directory.mkdir()
    marker = marker_directory / "other-operation.tmp"
    marker.write_bytes(b"keep")
    if occupied_kind == "dangling":
        target.symlink_to(target.parent / "missing.md")
    else:
        original_exists = Path.exists
        inserted = False

        def create_competing_resolution(path: Path) -> bool:
            nonlocal inserted
            exists = original_exists(path)
            if path == target and not exists and not inserted:
                target.write_bytes(b"concurrent resolution")
                inserted = True
            return exists

        monkeypatch.setattr(Path, "exists", create_competing_resolution)

    with pytest.raises(KbError, match="resolved copy already exists"):
        resolve._publish(
            root,
            git,
            source,
            target,
            original,
            b"rendered resolution",
            0o600,
        )

    assert source.read_bytes() == original
    if occupied_kind == "dangling":
        assert target.is_symlink()
        assert not target.exists()
    else:
        assert target.read_bytes() == b"concurrent resolution"
    assert sorted(path.name for path in marker_directory.iterdir()) == [marker.name]
    assert marker.read_bytes() == b"keep"

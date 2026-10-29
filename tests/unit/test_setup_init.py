"""kb setup --init in process: the empty-path check, the layout, and each initialization branch."""

import shutil
from pathlib import Path

import pytest

from kb import lock
from kb.commands import setup
from kb.errors import KbError


def test_an_absent_or_empty_path_is_accepted(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    setup._check_empty(tmp_path / "absent")
    setup._check_empty(empty)


def test_a_file_or_a_non_empty_directory_is_refused(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_text("x\n", encoding="utf-8")
    full = tmp_path / "full"
    full.mkdir()
    (full / "a").write_text("x\n", encoding="utf-8")

    with pytest.raises(KbError, match="not an empty directory"):
        setup._check_empty(file)
    with pytest.raises(KbError, match="not an empty directory"):
        setup._check_empty(full)


def test_the_layout_has_each_directory_with_an_empty_gitkeep_and_the_two_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "content"

    setup._create_layout(target)

    for relative in setup.LAYOUT:
        assert (target / relative / ".gitkeep").read_bytes() == b""
    assert (target / ".gitattributes").read_bytes() == b"* text=auto eol=lf\n"
    assert (target / "AGENTS.md").read_text(encoding="utf-8").startswith("This file holds")


def test_a_failed_git_command_names_the_command_and_its_error(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="git rev-parse failed: fatal"):
        setup._git_ok(tmp_path, "rev-parse", "--verify", "no-such-ref")


def test_init_is_refused_before_anything_is_created_when_kb_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(given: str | None) -> str:
        raise KbError("kb is not on PATH; pass --kb PATH")

    monkeypatch.setattr(setup, "_kb_path", missing)
    failures: list[str] = []

    state = setup._initialize(tmp_path / "new", None, None, {}, failures)

    assert state == ("refused", "refused", None, None)
    assert not (tmp_path / "new").exists()
    assert failures == ["setup: kb is not on PATH; pass --kb PATH"]


def test_a_refused_hook_skips_the_commit_and_removes_what_init_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = tmp_path / "new" / ".git" / "hooks" / "pre-commit"
    monkeypatch.setattr(setup, "_kb_path", lambda given: "/opt/kb")
    monkeypatch.setattr(setup, "_install", lambda root, kb, environ, failures: ("refused", hook))
    monkeypatch.setattr(setup, "_initial_commit", lambda *args: pytest.fail("committed"))

    failures: list[str] = []

    state = setup._initialize(tmp_path / "new", None, None, {}, failures)

    assert state == ("refused", "refused", hook, None)
    assert not (tmp_path / "new").exists()
    assert failures == [f"setup: removed the partial repository at {tmp_path / 'new'}"]


def test_a_failed_initial_commit_refuses_and_removes_the_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = tmp_path / "new" / ".git" / "hooks" / "pre-commit"
    monkeypatch.setattr(setup, "_kb_path", lambda given: "/opt/kb")
    monkeypatch.setattr(setup, "_install", lambda root, kb, environ, failures: ("installed", hook))

    def refuse(*args: object) -> None:
        raise KbError("git commit failed: nothing to commit")

    monkeypatch.setattr(setup, "_initial_commit", refuse)
    failures: list[str] = []

    state = setup._initialize(tmp_path / "new", None, None, {}, failures)

    assert state == ("refused", "installed", hook, None)
    assert not (tmp_path / "new").exists()
    assert failures == [
        "setup: git commit failed: nothing to commit",
        f"setup: removed the partial repository at {tmp_path / 'new'}",
    ]


def test_a_busy_lock_during_the_initial_commit_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = tmp_path / "new" / ".git" / "hooks" / "pre-commit"
    monkeypatch.setattr(setup, "_kb_path", lambda given: "/opt/kb")
    monkeypatch.setattr(setup, "_install", lambda root, kb, environ, failures: ("installed", hook))

    def busy(*args: object) -> None:
        raise lock.LockBusy(2)

    monkeypatch.setattr(setup, "_initial_commit", busy)
    failures: list[str] = []

    state = setup._initialize(tmp_path / "new", None, None, {}, failures)

    assert state[0] == "refused"
    assert failures == [
        "setup: content repository is busy (waited 2s for the lock)",
        f"setup: removed the partial repository at {tmp_path / 'new'}",
    ]


def test_a_push_failure_keeps_the_created_repository_and_names_the_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = tmp_path / "new" / ".git" / "hooks" / "pre-commit"
    monkeypatch.setattr(setup, "_kb_path", lambda given: "/opt/kb")
    monkeypatch.setattr(setup, "_install", lambda root, kb, environ, failures: ("installed", hook))
    monkeypatch.setattr(setup, "_initial_commit", lambda *args: None)
    failures: list[str] = []

    state = setup._initialize(tmp_path / "new", str(tmp_path / "absent.git"), None, {}, failures)

    assert state == ("created", "installed", hook, tmp_path / "new")
    assert failures[0].startswith("setup: git push failed:")
    assert failures[1] == (
        "setup: the local repository is kept. After fixing origin, "
        f"in {tmp_path / 'new'}, run: git push --set-upstream origin main"
    )


def test_a_refusal_in_an_existing_empty_directory_leaves_it_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    monkeypatch.setattr(setup, "_kb_path", lambda given: "/opt/kb")
    monkeypatch.setattr(setup, "_install", lambda root, kb, environ, failures: ("refused", None))

    state = setup._initialize(target, None, None, {}, [])

    assert state == ("refused", "refused", None, None)
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_a_failed_removal_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(path: Path) -> None:
        raise OSError("busy")

    monkeypatch.setattr(shutil, "rmtree", fail)
    target = tmp_path / "new"
    target.mkdir()
    failures: list[str] = []

    setup._roll_back(target, False, failures)

    assert failures == [f"setup: cannot remove the partial repository at {target}: busy"]


def test_a_failed_remote_add_names_both_recovery_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(root: Path, *words: str) -> None:
        raise KbError(f"git {words[0]} failed: fatal: bad remote")

    monkeypatch.setattr(setup, "_git_ok", refuse)
    failures: list[str] = []

    setup._publish(tmp_path, "url", failures)

    assert failures == [
        "setup: git remote failed: fatal: bad remote",
        f"setup: the local repository is kept. In {tmp_path}, run: "
        "git remote add origin URL, then git push --set-upstream origin main",
    ]

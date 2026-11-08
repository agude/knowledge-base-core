"""Review regressions for the existing commit-outcome guard."""

import subprocess
from pathlib import Path

import pytest

from kb import write
from kb.errors import KbError

from . import git_fakes


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


def test_initial_commit_is_preserved_when_head_inspection_fails_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    path = root / "record.md"
    path.write_bytes(b"new record\n")
    fake = git_fakes.install(monkeypatch)
    run_git = fake.real_run
    commit_finished = False

    def interrupt_commit(worktree: Path, *words: str) -> subprocess.CompletedProcess[str]:
        nonlocal commit_finished
        if commit_finished and words == ("rev-parse", "--verify", "HEAD"):
            return subprocess.CompletedProcess(["git", *words], 1, "", "inspection failed\n")
        result = run_git(worktree, *words)
        if words[0] == "commit":
            assert result.returncode == 0
            commit_finished = True
            raise KeyboardInterrupt
        return result

    fake.wrap(interrupt_commit)

    with pytest.raises((KbError, KeyboardInterrupt)) as caught:
        write._commit(root, "record.md", "Observe: initial", "observe")

    assert path.read_bytes() == b"new record\n"
    assert git(root, "show", "HEAD:record.md") == "new record\n"
    assert git(root, "show", ":record.md") == "new record\n"
    assert git(root, "status", "--porcelain") == ""
    assert isinstance(caught.value, KbError)
    assert "commit outcome is uncertain" in str(caught.value)


def test_an_uncertain_observe_commit_reports_the_exact_recovery_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    (root / "record.md").write_bytes(b"new record\n")
    fake = git_fakes.install(monkeypatch)
    committed = False

    def hide_head_after_commit(worktree: Path, *words: str) -> subprocess.CompletedProcess[str]:
        nonlocal committed
        if committed and words == ("rev-parse", "--verify", "HEAD"):
            return git_fakes.completed(1, "", "inspection failed\n")
        result = fake.real_run(worktree, *words)
        if words[0] == "commit":
            committed = True
            return git_fakes.completed(1, "", "reported failure\n")
        return result

    fake.wrap(hide_head_after_commit)

    with pytest.raises(KbError) as caught:
        write._commit(root, "record.md", "Observe: initial", "observe")

    assert str(caught.value) == (
        "observe: commit outcome is uncertain for record.md; the file and index were "
        "preserved; inspect Git status and HEAD before retrying: inspection failed"
    )


def test_a_failed_report_for_an_existing_observe_commit_is_a_failure_that_keeps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo")
    (root / "record.md").write_bytes(b"new record\n")
    fake = git_fakes.install(monkeypatch)

    def report_failure_after_commit(
        worktree: Path, words: tuple[str, ...]
    ) -> git_fakes.Result | None:
        if words[:1] != ("commit",):
            return None
        result = fake.real_run(worktree, *words)
        assert result.returncode == 0
        return git_fakes.completed(1, "", "reported failure\n")

    fake.responders.append(report_failure_after_commit)

    with pytest.raises(KbError) as caught:
        write._commit(root, "record.md", "Observe: initial", "observe")

    assert str(caught.value) == "observe: commit failed: reported failure"
    assert git(root, "show", "HEAD:record.md") == "new record\n"
    assert git(root, "status", "--porcelain") == ""
    assert (root / "record.md").read_bytes() == b"new record\n"

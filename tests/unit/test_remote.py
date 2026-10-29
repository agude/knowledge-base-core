"""In-process tests for the shared remote steps against real bare origins."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kb import remote
from kb.errors import KbError

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Remote Test",
    "GIT_AUTHOR_EMAIL": "remote@example.invalid",
    "GIT_COMMITTER_NAME": "Remote Test",
    "GIT_COMMITTER_EMAIL": "remote@example.invalid",
}
CONFLICT = "sync: rebase onto origin/main failed; local commits kept"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout


def commit(root: Path, name: str, text: str, message: str) -> None:
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "--", name)
    git(root, "commit", "-q", "-m", message)


def clone(origin: Path, destination: Path) -> Path:
    git(origin.parent, "clone", "-q", str(origin), str(destination))
    return destination


def origin_head(origin: Path) -> str:
    return git(origin, "rev-parse", "refs/heads/main").strip()


def local_head(local: Path) -> str:
    return git(local, "rev-parse", "HEAD").strip()


@pytest.fixture
def pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """A local repository whose main branch tracks a bare origin with one commit.

    The in-process remote steps run Git with this process's environment, so the test
    identity is exported here as well as passed to the helper commands.
    """
    for name, value in GIT_ENV.items():
        monkeypatch.setenv(name, value)
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "--bare", "-q", "-b", "main", str(origin))
    local = tmp_path / "local"
    git(tmp_path, "init", "-q", "-b", "main", str(local))
    commit(local, "seed.txt", "seed\n", "Seed")
    git(local, "remote", "add", "origin", str(origin))
    git(local, "push", "-q", "--set-upstream", "origin", "main")
    return local, origin


def test_matching_branches_report_already_in_sync(pair: tuple[Path, Path]) -> None:
    local, _ = pair
    assert remote.synchronize(local, push=True) == remote.Result(already_in_sync=True)


def test_behind_origin_rebases_and_reports_the_pulled_count(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, origin = pair
    other = clone(origin, tmp_path / "other")
    commit(other, "other.txt", "other\n", "Other change")
    git(other, "push", "-q", "origin", "main")

    assert remote.synchronize(local, push=True) == remote.Result(pulled=1)
    assert local_head(local) == origin_head(origin)


def test_ahead_of_origin_pushes_and_reports_the_pushed_count(pair: tuple[Path, Path]) -> None:
    local, origin = pair
    commit(local, "local.txt", "local\n", "Local change")

    assert remote.synchronize(local, push=True) == remote.Result(pushed=1)
    assert origin_head(origin) == local_head(local)


def test_no_push_keeps_local_commits_on_this_machine(pair: tuple[Path, Path]) -> None:
    local, origin = pair
    before = origin_head(origin)
    commit(local, "local.txt", "local\n", "Local change")

    assert remote.synchronize(local, push=False) == remote.Result()
    assert origin_head(origin) == before
    assert local_head(local) != before


def test_diverged_branches_with_a_clean_rebase_pull_then_push(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, origin = pair
    other = clone(origin, tmp_path / "other")
    commit(other, "other.txt", "other\n", "Other change")
    git(other, "push", "-q", "origin", "main")
    commit(local, "local.txt", "local\n", "Local change")

    assert remote.synchronize(local, push=True) == remote.Result(pulled=1, pushed=1)
    assert origin_head(origin) == local_head(local)
    assert {"other.txt", "local.txt"} <= set(git(local, "ls-files").splitlines())


def test_rebase_conflict_is_aborted_and_keeps_the_local_commit(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, origin = pair
    other = clone(origin, tmp_path / "other")
    commit(other, "seed.txt", "remote\n", "Remote edit")
    git(other, "push", "-q", "origin", "main")
    commit(local, "seed.txt", "local\n", "Local edit")
    kept = local_head(local)

    assert remote.synchronize(local, push=True) == remote.Result(errors=(CONFLICT,))
    assert local_head(local) == kept
    assert not (local / ".git" / "rebase-merge").exists()
    assert not (local / ".git" / "rebase-apply").exists()
    assert git(local, "status", "--porcelain") == ""


@pytest.mark.skipif(sys.platform == "win32", reason="the rejecting hook is a POSIX script")
def test_rejected_push_keeps_pulled_commits_and_reports_the_error(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, origin = pair
    other = clone(origin, tmp_path / "other")
    commit(other, "other.txt", "other\n", "Other change")
    git(other, "push", "-q", "origin", "main")
    reject = origin / "hooks" / "pre-receive"
    reject.write_text("#!/bin/sh\necho refused >&2\nexit 1\n", encoding="utf-8")
    reject.chmod(0o755)
    commit(local, "local.txt", "local\n", "Local change")
    before = origin_head(origin)

    result = remote.synchronize(local, push=True)

    assert result.pulled == 1
    assert result.pushed == 0
    assert len(result.errors) == 1
    assert result.errors[0].startswith("sync: push origin/main failed:")
    assert "refused" in result.errors[0]
    assert origin_head(origin) == before


def test_missing_origin_is_reported(pair: tuple[Path, Path]) -> None:
    local, _ = pair
    git(local, "remote", "remove", "origin")

    assert remote.synchronize(local, push=True) == remote.Result(errors=("sync: no origin remote",))


def test_detached_head_is_reported_before_any_fetch(pair: tuple[Path, Path]) -> None:
    local, _ = pair
    git(local, "checkout", "-q", "--detach")

    assert remote.synchronize(local, push=True) == remote.Result(
        errors=("sync: current branch is detached",)
    )


def test_fetch_failure_is_reported_and_head_does_not_move(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, _ = pair
    kept = local_head(local)
    git(local, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    result = remote.synchronize(local, push=True)

    assert len(result.errors) == 1
    assert result.errors[0].startswith("sync: fetch origin/main failed:")
    assert local_head(local) == kept


def test_dirty_worktree_stops_before_any_fetch(pair: tuple[Path, Path], tmp_path: Path) -> None:
    local, _ = pair
    git(local, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    (local / "draft.md").write_text("draft\n", encoding="utf-8")

    assert remote.synchronize(local, push=True) == remote.Result(skipped_dirty=("draft.md",))


def test_fetch_status_counts_both_directions_without_moving_head(
    pair: tuple[Path, Path], tmp_path: Path
) -> None:
    local, origin = pair
    other = clone(origin, tmp_path / "other")
    commit(other, "other.txt", "other\n", "Other change")
    git(other, "push", "-q", "origin", "main")
    commit(local, "local.txt", "local\n", "Local change")
    kept = local_head(local)

    status, error = remote.fetch_status(local)

    assert error is None
    assert status == remote.RemoteStatus("main", ahead=1, behind=1)
    assert local_head(local) == kept


def test_dirty_paths_lists_changes_and_renames(
    pair: tuple[Path, Path],
) -> None:
    local, _ = pair
    git(local, "mv", "seed.txt", "renamed.txt")
    (local / "new.md").write_text("new\n", encoding="utf-8")

    assert sorted(remote.dirty_paths(local)) == ["new.md", "renamed.txt"]


def test_dirty_paths_reports_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot inspect working tree"):
        remote.dirty_paths(tmp_path)

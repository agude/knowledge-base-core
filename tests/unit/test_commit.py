"""The shared commit outcome and rollback module, against real repositories."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kb import commit, git
from kb.errors import KbError

from . import git_fakes


def run(root: Path, *words: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", *words],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout


def make_repo(root: Path, *, commit: bool) -> Path:
    root.mkdir()
    run(root, "init", "-q")
    run(root, "config", "user.name", "Commit Test")
    run(root, "config", "user.email", "commit@example.invalid")
    run(root, "config", "core.autocrlf", "false")
    if commit:
        (root / "seed.md").write_text("seed\n", encoding="utf-8")
        run(root, "add", "--", "seed.md")
        run(root, "commit", "-q", "-m", "Seed")
    return root


def test_reset_unstages_a_new_file_on_an_unborn_branch(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=False)
    (root / "new.md").write_text("new\n", encoding="utf-8")
    run(root, "add", "--", "new.md")

    result = git.run(root, "reset", "-q", "--", "new.md")

    assert result.returncode == 0, result.stderr
    assert run(root, "ls-files") == ""


def test_reset_unstages_a_new_file_a_hook_changed_after_staging(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    path = root / "new.md"
    path.write_text("staged\n", encoding="utf-8")
    run(root, "add", "--", "new.md")
    path.write_text("changed by a hook\n", encoding="utf-8")

    result = git.run(root, "reset", "-q", "--", "new.md")

    assert result.returncode == 0, result.stderr
    assert run(root, "ls-files") == "seed.md\n"
    assert path.read_text(encoding="utf-8") == "changed by a hook\n"


def test_reset_unstages_under_a_temporary_index(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    temporary = tmp_path / "index.tmp"
    shutil.copyfile(root / ".git" / "index", temporary)
    env = {**os.environ, "GIT_INDEX_FILE": str(temporary)}
    (root / "new.md").write_text("new\n", encoding="utf-8")
    run(root, "add", "--", "new.md", env=env)
    assert run(root, "ls-files", env=env) == "new.md\nseed.md\n"

    run(root, "reset", "-q", "--", "new.md", env=env)

    assert run(root, "ls-files", env=env) == "seed.md\n"
    assert run(root, "ls-files") == "seed.md\n"


def head_of(root: Path) -> str:
    return run(root, "rev-parse", "HEAD").strip()


def commit_file(root: Path, name: str, content: bytes, subject: str) -> None:
    (root / name).write_bytes(content)
    run(root, "add", "--", name)
    run(root, "commit", "-q", "-m", subject, "--", name)


def test_read_head_reports_an_unborn_branch(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=False)

    assert commit.read_head(root, allow_unborn=True) == (None, None)
    head, error = commit.read_head(root, allow_unborn=False)
    assert head is None
    assert error


def test_read_head_returns_a_commit(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)

    assert commit.read_head(root, allow_unborn=True) == (head_of(root), None)


def test_read_head_treats_a_missing_branch_beside_another_as_unborn(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    run(root, "symbolic-ref", "HEAD", "refs/heads/missing")

    assert commit.read_head(root, allow_unborn=True) == (None, None)


def test_read_head_reports_a_failed_reference_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(tmp_path / "repo", commit=False)
    fake = git_fakes.install(monkeypatch)
    fake.on(("rev-parse",), git_fakes.completed(1, "", "rev-parse failed\n"))
    fake.on(("show-ref",), git_fakes.completed(128, "", "show-ref failed\n"))

    assert commit.read_head(root, allow_unborn=True) == (None, "rev-parse failed")


def test_identify_reports_an_unchanged_head_as_failed(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)

    inspection = commit.identify(root, head_of(root), "Add", allow_unborn=False)

    assert inspection == commit.Inspection("failed", None, "HEAD is unchanged")


def test_identify_reports_a_commit_with_another_subject_as_unknown(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    before = head_of(root)
    commit_file(root, "new.md", b"new\n", "Other")

    inspection = commit.identify(root, before, "Add", allow_unborn=False)

    assert inspection == commit.Inspection(
        "unknown", None, "HEAD changed but does not identify this transaction's commit"
    )


def test_identify_recognizes_the_commit_on_an_unborn_branch(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=False)
    commit_file(root, "new.md", b"new\n", "Add")

    inspection = commit.identify(root, None, "Add", allow_unborn=True)

    assert inspection == commit.Inspection("committed", head_of(root), "")


@pytest.mark.parametrize("content", [b"a\nb\n", b"a\r\nb\r\n"])
def test_prove_new_files_accepts_committed_bytes(tmp_path: Path, content: bytes) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    before = head_of(root)
    (root / "new.md").write_bytes(content)
    _, files = commit.save_new_files(root, ["new.md"], "observe")
    run(root, "add", "--", "new.md")
    run(root, "commit", "-q", "-m", "Add", "--", "new.md")

    identified = commit.identify(root, before, "Add", allow_unborn=False)
    inspection = commit.prove_new_files(root, identified, files)

    assert inspection == commit.Inspection("committed", head_of(root), "")


def test_prove_new_files_reports_a_file_missing_from_the_commit(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    before = head_of(root)
    (root / "new.md").write_bytes(b"new\n")
    (root / "other.md").write_bytes(b"other\n")
    _, files = commit.save_new_files(root, ["new.md", "other.md"], "sync")
    run(root, "add", "--", "new.md")
    run(root, "commit", "-q", "-m", "Add", "--", "new.md")

    identified = commit.identify(root, before, "Add", allow_unborn=False)
    inspection = commit.prove_new_files(root, identified, files)

    assert inspection == commit.Inspection(
        "unknown", None, "the new commit does not contain the transaction path"
    )


def test_prove_new_files_passes_through_an_outcome_that_is_not_committed() -> None:
    failed = commit.Inspection("failed", None, "HEAD is unchanged")

    assert commit.prove_new_files(Path(), failed, []) is failed
    assert commit.prove_tree(Path(), failed, "") is failed


def test_prove_tree_accepts_a_matching_clean_commit(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    before = head_of(root)
    commit_file(root, "new.md", b"new\n", "Publish")
    tree = run(root, "write-tree").strip()

    identified = commit.identify(root, before, "Publish", allow_unborn=False)
    inspection = commit.prove_tree(root, identified, tree)

    assert inspection == commit.Inspection("committed", head_of(root), "")


def test_prove_tree_reports_a_worktree_change_as_unknown(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    before = head_of(root)
    commit_file(root, "new.md", b"new\n", "Publish")
    tree = run(root, "write-tree").strip()
    (root / "new.md").write_bytes(b"changed\n")

    identified = commit.identify(root, before, "Publish", allow_unborn=False)
    inspection = commit.prove_tree(root, identified, tree)

    assert inspection == commit.Inspection(
        "unknown", None, "the worktree differs from the committed publication"
    )


def test_inspect_turns_an_interrupt_into_an_unknown_outcome() -> None:
    def interrupted() -> commit.Inspection:
        raise KeyboardInterrupt

    assert commit.inspect(interrupted) == commit.Inspection(
        "unknown", None, "commit outcome inspection was interrupted"
    )
    assert commit.inspect(interrupted, fallback="") == commit.Inspection("unknown", None, "")


def test_save_new_files_refuses_a_path_already_in_head(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)

    with pytest.raises(KbError, match=r"refusing to commit an existing HEAD path: seed\.md"):
        commit.save_new_files(root, ["seed.md"], "observe")


def test_unstage_removes_only_the_named_paths(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    for name in ("new.md", "keep.md"):
        (root / name).write_text(f"{name}\n", encoding="utf-8")
        run(root, "add", "--", name)

    assert commit.unstage(root, ["new.md"]) is None

    assert run(root, "diff", "--cached", "--name-only") == "keep.md\n"
    assert (root / "new.md").read_text(encoding="utf-8") == "new.md\n"


def test_unstage_returns_git_error_text(tmp_path: Path) -> None:
    root = make_repo(tmp_path / "repo", commit=True)
    (root / ".git" / "index.lock").write_text("", encoding="utf-8")

    error = commit.unstage(root, ["seed.md"])

    assert error is not None
    assert "index.lock" in error


@pytest.mark.parametrize(
    ("preserved", "listing"),
    [
        ("file and index", "observations/pending/a.md"),
        ("files and index", "observations/pending/a.md, observations/pending/b.md"),
        ("publication files and index", "knowledge/a.md, observations/pending/a.md"),
    ],
)
@pytest.mark.parametrize("detail", ["", "HEAD inspection unavailable"])
def test_uncertain_message_names_what_was_preserved(
    preserved: str, listing: str, detail: str
) -> None:
    expected = (
        f"kb: commit outcome is uncertain for {listing}; the {preserved} were preserved; "
        "inspect Git status and HEAD before retrying"
    )
    if detail:
        expected = f"{expected}: {detail}"

    assert commit.uncertain_message("kb", listing, preserved, detail) == expected

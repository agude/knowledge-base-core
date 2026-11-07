"""In-process tests for the pre-commit hook: staging checks, validation, and stamping."""

import os
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from kb.commands import hook
from kb.context import Context
from kb.errors import KbError

TODAY = "2026-10-26"
NOW = {"KB_NOW": "2026-10-26T12:00:00Z"}
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "Hook Test",
    "GIT_AUTHOR_EMAIL": "hook@example.invalid",
    "GIT_COMMITTER_NAME": "Hook Test",
    "GIT_COMMITTER_EMAIL": "hook@example.invalid",
}
ARTICLE = (
    "---\ntitle: Backups\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Backups\n\n## 1. Schedule\n\nNightly.\n"
)


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


def repo(root: Path, files: dict[str, bytes]) -> Path:
    """A repository whose first commit holds the given files."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for relpath, data in files.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(root, "add", "--all")
    git(root, "commit", "-q", "-m", "Seed")
    return root


def stage_text(root: Path, relpath: str, text: str) -> None:
    (root / relpath).write_text(text, encoding="utf-8")
    git(root, "add", "--", relpath)


def test_a_commit_without_knowledge_changes_exits_silently(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    stage_text(root, "notes.txt", "note\n")

    assert hook.pre_commit(root, NOW) == 0
    assert capsys.readouterr().err == ""


def test_a_blocking_finding_rejects_the_commit_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    broken = ARTICLE + "\n# Second title\n"
    stage_text(root, "knowledge/a.md", broken)
    staged = git(root, "diff", "--cached", "--name-only")

    assert hook.pre_commit(root, NOW) == 1

    err = capsys.readouterr().err
    assert "hook: knowledge/a.md:" in err
    assert "second H1" in err
    assert "lint errors; commit rejected, nothing modified." in err
    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == broken
    assert git(root, "diff", "--cached", "--name-only") == staged


def test_a_partially_staged_article_is_refused_without_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    stage_text(root, "knowledge/a.md", ARTICLE.replace("Nightly.", "Staged."))
    worktree = ARTICLE.replace("Nightly.", "Worktree.")
    (root / "knowledge/a.md").write_text(worktree, encoding="utf-8")

    assert hook.pre_commit(root, NOW) == 1

    assert (
        "hook: knowledge/a.md has unstaged changes; stage or discard the unstaged changes"
        in capsys.readouterr().err
    )
    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == worktree


def test_a_staged_article_is_stamped_restaged_and_keeps_verified_and_ttl(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    stage_text(root, "knowledge/a.md", ARTICLE.replace("Nightly.", "Nightly and weekly."))

    assert hook.pre_commit(root, NOW) == 0

    text = (root / "knowledge/a.md").read_text(encoding="utf-8")
    assert text == ARTICLE.replace("Nightly.", "Nightly and weekly.").replace(
        "updated: 2026-10-20", f"updated: {TODAY}"
    )
    assert git(root, "show", ":knowledge/a.md") == text
    assert f"hook: stamped updated: {TODAY} on 1 article(s)" in capsys.readouterr().err


def test_a_partial_commit_is_validated_but_keeps_its_older_updated_value(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    edited = ARTICLE.replace("Nightly.", "Nightly and weekly.")
    stage_text(root, "knowledge/a.md", edited)
    temporary_index = root / ".git" / "kb-partial-index"
    shutil.copyfile(root / ".git" / "index", temporary_index)
    monkeypatch.setenv("GIT_INDEX_FILE", str(temporary_index))

    assert hook.pre_commit(root, {**NOW, "GIT_INDEX_FILE": str(temporary_index)}) == 0

    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == edited
    assert (
        f"hook: knowledge/a.md has updated: 2026-10-20, not {TODAY} "
        "(partial commit; not stamping)" in capsys.readouterr().err
    )


def test_a_temporary_index_at_the_normal_path_is_not_partial(tmp_path: Path) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})

    assert hook._is_partial(root, {"GIT_INDEX_FILE": str(root / ".git" / "index")}) is False


def test_partial_detection_reads_the_supplied_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / ".git" / "next-index-1.lock"))

    assert hook._is_partial(root, {}) is False
    assert hook._is_partial(root, {"GIT_INDEX_FILE": str(root / ".git" / "next-index-1.lock")})


def test_a_symbolic_link_article_keeps_its_link_and_the_target_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/real.md": ARTICLE.encode()})
    target = root / "knowledge/real.md"
    target.chmod(0o640)
    link = root / "knowledge/alias.md"
    link.symlink_to("real.md")
    git(root, "add", "--", "knowledge/alias.md")

    assert hook.pre_commit(root, NOW) == 0

    assert link.is_symlink()
    if sys.platform != "win32":  # Windows has no POSIX file modes
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert f"updated: {TODAY}" in target.read_text(encoding="utf-8")


def test_non_ascii_names_byte_order_marks_and_crlf_survive_stamping(
    tmp_path: Path,
) -> None:
    original = ("﻿" + ARTICLE.replace("\n", "\r\n")).encode("utf-8")
    root = repo(tmp_path / "content", {"knowledge/café.md": original})
    edited = original.replace(b"Nightly.", b"Weekly.")
    (root / "knowledge/café.md").write_bytes(edited)
    git(root, "add", "--", "knowledge/café.md")

    assert hook.pre_commit(root, NOW) == 0

    expected = edited.replace(b"updated: 2026-10-20", f"updated: {TODAY}".encode())
    assert (root / "knowledge/café.md").read_bytes() == expected


def test_preexisting_findings_are_reported_and_do_not_block(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    old = "---\ntitle: Old\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n# A\n# B\n"
    root = repo(
        tmp_path / "content",
        {"knowledge/old.md": old.encode(), "knowledge/a.md": ARTICLE.encode()},
    )
    stage_text(root, "knowledge/a.md", ARTICLE.replace("Nightly.", "Weekly."))

    assert hook.pre_commit(root, NOW) == 0

    err = capsys.readouterr().err
    assert "hook: Preexisting (not blocking): 1" in err
    assert "knowledge/old.md:" in err


def test_deleting_an_article_that_an_unchanged_article_cites_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    index = (
        "---\ntitle: Index\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
        "# Index\n\n## 1. Map\n\nSee [backups](backups.md).\n"
    )
    root = repo(
        tmp_path / "content",
        {"knowledge/index.md": index.encode(), "knowledge/backups.md": ARTICLE.encode()},
    )
    git(root, "rm", "-q", "--", "knowledge/backups.md")

    assert hook.pre_commit(root, NOW) == 1

    err = capsys.readouterr().err
    assert "hook: knowledge/index.md:" in err
    assert "missing local Markdown link target: backups.md" in err


def test_a_duplicated_updated_field_cannot_be_stamped_and_is_refused(tmp_path: Path) -> None:
    duplicated = (
        "---\ntitle: T\nupdated: 2026-10-20\nupdated: 2026-10-21\nverified: 2026-10-20\n"
        "ttl: domain\n---\n# T\n\n## 1. A\n\nText.\n"
    )
    root = repo(tmp_path / "content", {"knowledge/seed.md": ARTICLE.encode()})
    stage_text(root, "knowledge/dup.md", duplicated)

    with pytest.raises(KbError, match=r"hook: cannot stamp knowledge/dup\.md"):
        hook.pre_commit(root, NOW)


def test_outside_a_repository_the_staged_changes_cannot_be_read(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="hook: cannot read the staged changes"):
        hook.pre_commit(tmp_path, NOW)


def test_run_reports_usage_help_and_filesystem_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert hook.run(["--help"]) == 0
    assert "Usage: kb hook pre-commit" in capsys.readouterr().out
    with pytest.raises(KbError, match="Usage: kb hook pre-commit"):
        hook.run(["post-commit"])
    with pytest.raises(KbError, match="Usage: kb hook pre-commit"):
        hook.run(["pre-commit", "extra"])

    def unreadable(*_args: object) -> int:
        raise OSError("disk unavailable")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(hook, "load", lambda *_args: Context(tmp_path, date(2026, 10, 26)))
    monkeypatch.setattr(hook, "pre_commit", unreadable)
    with pytest.raises(KbError, match="hook: disk unavailable"):
        hook.run(["pre-commit"])


@pytest.mark.parametrize("target_state", ["untracked", "unstaged-anchor"])
def test_references_must_resolve_in_the_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], target_state: str
) -> None:
    files = {"knowledge/a.md": ARTICLE.encode()}
    if target_state == "unstaged-anchor":
        files["knowledge/target.md"] = ARTICLE.encode()
    root = repo(tmp_path / "content", files)
    target = root / "knowledge/target.md"
    target.write_text(ARTICLE + "\n## 2. Only in worktree\n", encoding="utf-8")
    source = ARTICLE + "\nSee [target](target.md#2).\n"
    stage_text(root, "knowledge/a.md", source)
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 1

    assert "missing" in capsys.readouterr().err
    assert git(root, "write-tree") == before
    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == source
    assert target.read_text(encoding="utf-8") == ARTICLE + "\n## 2. Only in worktree\n"


def test_external_article_symlinks_are_refused_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    outside = tmp_path / "external.md"
    outside.write_text(ARTICLE, encoding="utf-8")
    link = root / "knowledge/alias.md"
    link.symlink_to(outside)
    git(root, "add", "--", "knowledge/alias.md")
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 1

    assert "outside" in capsys.readouterr().err
    assert outside.read_text(encoding="utf-8") == ARTICLE
    assert link.is_symlink()
    assert git(root, "write-tree") == before


def test_internal_link_with_unstaged_target_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path / "content", {"knowledge/real.md": ARTICLE.encode()})
    link = root / "knowledge/alias.md"
    link.symlink_to("real.md")
    git(root, "add", "--", "knowledge/alias.md")
    target = root / "knowledge/real.md"
    edited = ARTICLE.replace("Nightly.", "Unstaged edit.")
    target.write_text(edited, encoding="utf-8")
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 1

    assert target.read_text(encoding="utf-8") == edited
    assert git(root, "write-tree") == before
    assert link.is_symlink()


def test_an_internal_link_stamps_only_the_worktree_target_outside_the_change_set(
    tmp_path: Path,
) -> None:
    root = repo(tmp_path / "content", {"knowledge/real.md": ARTICLE.encode()})
    link = root / "knowledge/alias.md"
    link.symlink_to("real.md")
    git(root, "add", "--", "knowledge/alias.md")

    assert hook.pre_commit(root, NOW) == 0

    assert git(root, "show", ":knowledge/real.md") == ARTICLE
    assert git(root, "show", ":knowledge/alias.md") == "real.md"
    assert git(root, "diff", "--cached", "--name-only") == "knowledge/alias.md\n"
    assert git(root, "diff", "--name-only") == "knowledge/real.md\n"
    assert (root / "knowledge/real.md").read_text(encoding="utf-8") == ARTICLE.replace(
        "updated: 2026-10-20", f"updated: {TODAY}"
    )


@pytest.mark.parametrize("target_state", ["head", "staged"])
def test_references_to_indexed_targets_pass(tmp_path: Path, target_state: str) -> None:
    root = repo(
        tmp_path / "content",
        {"knowledge/a.md": ARTICLE.encode(), "knowledge/target.md": ARTICLE.encode()},
    )
    fragment = "1"
    if target_state == "staged":
        fragment = "2"
        stage_text(root, "knowledge/target.md", ARTICLE + "\n## 2. New section\n")
    stage_text(root, "knowledge/a.md", ARTICLE + f"\nSee [target](target.md#{fragment}).\n")

    assert hook.pre_commit(root, NOW) == 0


def test_internal_link_and_its_staged_target_are_both_preserved(tmp_path: Path) -> None:
    root = repo(tmp_path / "content", {"knowledge/real.md": ARTICLE.encode()})
    link = root / "knowledge/alias.md"
    link.symlink_to("real.md")
    stage_text(root, "knowledge/real.md", ARTICLE.replace("Nightly.", "Weekly."))
    git(root, "add", "--", "knowledge/alias.md")

    assert hook.pre_commit(root, NOW) == 0

    assert link.is_symlink()
    assert git(root, "show", ":knowledge/alias.md") == "real.md"
    expected = ARTICLE.replace("Nightly.", "Weekly.").replace(
        "updated: 2026-10-20", f"updated: {TODAY}"
    )
    assert git(root, "show", ":knowledge/real.md") == expected
    assert git(root, "diff", "--name-only") == ""


def test_stamping_preserves_worktree_crlf_when_git_normalizes_the_index(tmp_path: Path) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    git(root, "config", "core.autocrlf", "true")
    path = root / "knowledge/a.md"
    edited = ARTICLE.replace("Nightly.", "Weekly.").replace("\n", "\r\n")
    path.write_bytes(edited.encode())
    git(root, "add", "--", "knowledge/a.md")
    assert git(root, "diff", "--name-only") == ""

    assert hook.pre_commit(root, NOW) == 0

    expected = edited.replace("updated: 2026-10-20", f"updated: {TODAY}")
    assert path.read_bytes() == expected.encode()
    assert git(root, "show", ":knowledge/a.md") == expected.replace("\r\n", "\n")
    assert git(root, "diff", "--name-only") == ""


def test_section_removal_blocks_an_unchanged_incoming_reference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = ARTICLE + "\nSee [b](b.md#2).\n"
    root = repo(
        tmp_path / "content",
        {
            "knowledge/a.md": source.encode(),
            "knowledge/b.md": (ARTICLE + "\n## 2. Second\n").encode(),
        },
    )
    stage_text(root, "knowledge/b.md", ARTICLE)
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 1

    assert "missing local Markdown link anchor '#2'" in capsys.readouterr().err
    assert git(root, "write-tree") == before
    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == source
    assert (root / "knowledge/b.md").read_text(encoding="utf-8") == ARTICLE


def test_an_invalid_incoming_reference_is_not_newly_broken_by_target_removal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = ARTICLE + "\nSee [b](b.md#99).\n"
    root = repo(
        tmp_path / "content",
        {"knowledge/a.md": source.encode(), "knowledge/b.md": ARTICLE.encode()},
    )
    git(root, "rm", "-q", "--", "knowledge/b.md")
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 0

    assert "Preexisting (not blocking): 1" in capsys.readouterr().err
    assert git(root, "write-tree") == before


def test_renaming_a_target_refuses_the_unchanged_incoming_reference(tmp_path: Path) -> None:
    source = ARTICLE + "\nSee [b](b.md#1).\n"
    root = repo(
        tmp_path / "content",
        {"knowledge/a.md": source.encode(), "knowledge/b.md": ARTICLE.encode()},
    )
    git(root, "mv", "knowledge/b.md", "knowledge/renamed.md")
    before = git(root, "write-tree")

    assert hook.pre_commit(root, NOW) == 1

    assert git(root, "write-tree") == before
    assert (root / "knowledge/renamed.md").read_text(encoding="utf-8") == ARTICLE
    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == source

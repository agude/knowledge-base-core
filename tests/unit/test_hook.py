"""In-process tests for the pre-commit hook: staging checks, validation, and stamping."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from kb.commands import hook
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

    assert hook.pre_commit(root, NOW) == 0

    assert (root / "knowledge/a.md").read_text(encoding="utf-8") == edited
    assert (
        f"hook: knowledge/a.md has updated: 2026-10-20, not {TODAY} "
        "(partial commit; not stamping)" in capsys.readouterr().err
    )


def test_a_temporary_index_at_the_normal_path_is_not_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path / "content", {"knowledge/a.md": ARTICLE.encode()})
    monkeypatch.setenv("GIT_INDEX_FILE", str(root / ".git" / "index"))

    assert hook._is_partial(root) is False


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
    monkeypatch.setattr(hook, "pre_commit", unreadable)
    with pytest.raises(KbError, match="hook: disk unavailable"):
        hook.run(["pre-commit"])

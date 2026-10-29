"""End-to-end tests for the content pre-commit hook, installed in fixture repositories.

The hook is a POSIX shell script that Git runs, so these tests run only where Git runs
it. Unit tests cover the same rules in process on every platform.
"""

import subprocess
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from .harness import Kb, run_git

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed pre-commit hook is a POSIX shell script"
)
TODAY = "2026-10-26"
ARTICLE = (
    "---\ntitle: Backups\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
    "# Backups\n\n## 1. Schedule\n\nNightly.\n"
)


def _install_hook(kb: Kb) -> Path:
    """Write the one-line hook that calls this interpreter's kb, as phase 4 setup will."""
    hook = kb.content / ".git" / "hooks" / "pre-commit"
    hook.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb hook pre-commit\n', encoding="utf-8")
    hook.chmod(0o755)
    return hook


def _commit(kb: Kb, message: str, *paths: str) -> CompletedProcess[str]:
    """Run git commit with the isolated environment, so the hook sees the fixed clock."""
    command = ["git", "commit", "-q", "-m", message]
    if paths:
        command.extend(["--", *paths])
    return subprocess.run(
        command,
        cwd=kb.content,
        env=kb.environment({}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )


def _write(kb: Kb, relative: str, text: str) -> Path:
    path = kb.content / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _committed(kb: Kb, relative: str) -> str:
    return run_git(kb.content, "show", f"HEAD:{relative}")


def test_a_commit_without_knowledge_changes_passes_silently(git_kb: Kb) -> None:
    _install_hook(git_kb)
    _write(git_kb, "notes.txt", "A note outside the knowledge base.\n")
    run_git(git_kb.content, "add", "--", "notes.txt")

    result = _commit(git_kb, "Add a note")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_an_invalid_article_is_rejected_and_nothing_is_changed(git_kb: Kb) -> None:
    _install_hook(git_kb)
    broken = ARTICLE + "\n# Second title\n"
    path = _write(git_kb, "knowledge/infra/backups.md", broken)
    run_git(git_kb.content, "add", "--", "knowledge/infra/backups.md")
    head = run_git(git_kb.content, "rev-parse", "HEAD")

    result = _commit(git_kb, "Break the backups article")

    assert result.returncode == 1
    assert "hook: knowledge/infra/backups.md:" in result.stderr
    assert "nothing modified" in result.stderr
    assert run_git(git_kb.content, "rev-parse", "HEAD") == head
    assert path.read_text(encoding="utf-8") == broken
    assert "knowledge/infra/backups.md" in run_git(
        git_kb.content, "diff", "--cached", "--name-only"
    )


def test_a_valid_edit_is_stamped_and_keeps_verified_and_ttl(git_kb: Kb) -> None:
    _install_hook(git_kb)
    _write(git_kb, "knowledge/infra/backups.md", ARTICLE.replace("Nightly.", "Nightly and weekly."))
    run_git(git_kb.content, "add", "--", "knowledge/infra/backups.md")

    result = _commit(git_kb, "Describe the backup schedule")

    assert result.returncode == 0, result.stderr
    assert f"hook: stamped updated: {TODAY} on 1 article(s)" in result.stderr
    committed = _committed(git_kb, "knowledge/infra/backups.md")
    assert f"updated: {TODAY}\n" in committed
    assert "verified: 2026-10-20\n" in committed
    assert "ttl: domain\n" in committed


def test_a_partially_staged_article_refuses_the_commit(git_kb: Kb) -> None:
    _install_hook(git_kb)
    _write(git_kb, "knowledge/infra/backups.md", ARTICLE.replace("Nightly.", "Staged."))
    run_git(git_kb.content, "add", "--", "knowledge/infra/backups.md")
    _write(git_kb, "knowledge/infra/backups.md", ARTICLE.replace("Nightly.", "Unstaged."))

    result = _commit(git_kb, "Commit a partly staged article")

    assert result.returncode == 1
    assert (
        "hook: knowledge/infra/backups.md has unstaged changes; "
        "stage or discard the unstaged changes" in result.stderr
    )
    assert "Unstaged." in (git_kb.content / "knowledge/infra/backups.md").read_text(
        encoding="utf-8"
    )


def test_a_path_limited_commit_is_partial_and_keeps_its_updated_value(git_kb: Kb) -> None:
    _install_hook(git_kb)
    edited = ARTICLE.replace("Nightly.", "Nightly and weekly.")
    _write(git_kb, "knowledge/infra/backups.md", edited)

    result = _commit(git_kb, "Commit one article by path", "knowledge/infra/backups.md")

    assert result.returncode == 0, result.stderr
    assert "not stamping" in result.stderr
    assert _committed(git_kb, "knowledge/infra/backups.md") == edited


def test_removing_an_article_that_another_article_cites_is_refused(git_kb: Kb) -> None:
    _write(
        git_kb,
        "knowledge/infra/index.md",
        "---\ntitle: Index\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n"
        "# Index\n\n## 1. Map\n\nSee [backups](backups.md).\n",
    )
    run_git(git_kb.content, "add", "--all")
    run_git(git_kb.content, "commit", "-q", "-m", "Add an index")
    _install_hook(git_kb)
    run_git(git_kb.content, "rm", "-q", "--", "knowledge/infra/backups.md")

    result = _commit(git_kb, "Remove the backups article")

    assert result.returncode == 1
    assert "hook: knowledge/infra/index.md:" in result.stderr
    assert "missing local Markdown link target: backups.md" in result.stderr


def test_removing_an_archived_observation_that_an_article_cites_is_refused(git_kb: Kb) -> None:
    archived = "observations/archived/20261015T120000-b1c2d3e4.md"
    _write(git_kb, archived, "---\ntitle: Cited\ncreated: 2026-10-15\n---\n\n## 1. Note\n\nText.\n")
    _write(
        git_kb,
        "knowledge/infra/cited.md",
        "---\ntitle: Cited\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n"
        f"sources:\n  - {archived}\n---\n# Cited\n\n## 1. Fact\n\nText.\n",
    )
    run_git(git_kb.content, "add", "--all")
    run_git(git_kb.content, "commit", "-q", "-m", "Cite an archived observation")
    _install_hook(git_kb)
    run_git(git_kb.content, "rm", "-q", "--", archived)

    result = _commit(git_kb, "Remove the archived observation")

    assert result.returncode == 1
    assert f"missing local source reference: {archived}" in result.stderr


def test_preexisting_findings_are_reported_and_do_not_block(git_kb: Kb) -> None:
    _install_hook(git_kb)
    _write(git_kb, "knowledge/infra/new.md", ARTICLE.replace("Backups", "New note"))
    run_git(git_kb.content, "add", "--", "knowledge/infra/new.md")

    result = _commit(git_kb, "Add a clean article beside preexisting problems")

    assert result.returncode == 0, result.stderr
    assert "hook: Preexisting (not blocking): " in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        ["observe", "--title", "Hook observation", "--body", "The hook must not wait."],
        [
            "gap",
            "--title",
            "Hook gap",
            "--body",
            "The hook must not wait.",
            "--context",
            "future/infra",
        ],
    ],
)
def test_observe_and_gap_commits_run_the_hook_without_waiting_for_the_lock(
    git_kb: Kb, command: list[str]
) -> None:
    _install_hook(git_kb)

    result = git_kb(*command)

    assert result.returncode == 0, result.stderr
    assert "busy" not in result.stderr
    assert run_git(git_kb.content, "status", "--porcelain") == ""

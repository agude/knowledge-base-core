"""End-to-end tests for recording an attributed question with `kb gap`."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from .harness import HOLD_KERNEL_LOCK, Kb

WROTE = re.compile(r"Wrote: questions/open/([0-9]{8}T[0-9]{6}-[0-9a-f]{8}\.md)\n")


def test_writes_an_attributed_question_for_a_missing_area(git_kb: Kb) -> None:
    result = git_kb(
        "gap",
        "--title",
        "Où is the backup?",
        "--body",
        "The backup location is not recorded.",
        "--context",
        "future/infra",
    )
    assert result.returncode == 0, result.stderr
    match = WROTE.fullmatch(result.stdout)
    assert match is not None
    relative = f"questions/open/{match.group(1)}"
    text = (git_kb.content / relative).read_text(encoding="utf-8")
    assert text.startswith(
        '---\ntitle: "Où is the backup?"\ncontext: "knowledge/future/infra"\nsource: session\n'
    )
    assert text.endswith("The backup location is not recorded.\n")
    assert git_kb.git("log", "-1", "--format=%s") == "Ask: Où is the backup?\n"
    assert git_kb.git("show", "--name-only", "--format=", "HEAD").split() == [relative]


def test_reads_stdin_and_normalizes_a_resolvable_context(git_kb: Kb) -> None:
    result = git_kb(
        "gap",
        "--title",
        "Backup owner",
        "--body",
        "-",
        "--context",
        "./infra/./nas.md/",
        stdin="The owner is not listed.\n",
    )
    assert result.returncode == 0, result.stderr
    match = WROTE.fullmatch(result.stdout)
    assert match is not None
    text = (git_kb.content / "questions" / "open" / match.group(1)).read_text(encoding="utf-8")
    assert 'context: "knowledge/infra/nas.md"\n' in text
    assert text.endswith("The owner is not listed.\n\n")


def test_reads_help_and_requires_all_three_options(kb: Kb) -> None:
    help_result = kb("gap", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("Usage: kb gap --title TITLE --body TEXT --context PATH\n")
    missing = kb("gap", "--title", "Title", "--body", "Body")
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr == "Usage: kb gap --title TITLE --body TEXT --context PATH\n"


def test_context_symlink_outside_content_is_stored_literally(git_kb: Kb, tmp_path: Path) -> None:
    outside = tmp_path / "external-target.md"
    outside.write_text("Private synthetic target.\n", encoding="utf-8")
    alias = git_kb.content / "knowledge" / "external.md"
    try:
        alias.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable")

    result = git_kb(
        "gap", "--title", "External context", "--body", "Literal only.", "--context", str(alias)
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "context must be a relative path" in result.stderr

    result = git_kb(
        "gap",
        "--title",
        "External context",
        "--body",
        "Literal only.",
        "--context",
        "knowledge/external.md",
    )
    assert result.returncode == 0, result.stderr
    match = WROTE.fullmatch(result.stdout)
    assert match is not None
    text = (git_kb.content / "questions" / "open" / match.group(1)).read_text(encoding="utf-8")
    assert 'context: "knowledge/external.md"\n' in text
    assert "Private synthetic target" not in text


def test_preserves_unrelated_staged_and_unstaged_files(git_kb: Kb) -> None:
    staged = git_kb.content / "knowledge" / "staged.md"
    staged.write_text("# Staged\n\nLeave staged.\n", encoding="utf-8")
    git_kb.git("add", "knowledge/staged.md")
    unstaged = git_kb.content / "knowledge" / "unstaged.md"
    unstaged.write_text("# Unstaged\n\nLeave unstaged.\n", encoding="utf-8")

    result = git_kb(
        "gap",
        "--title",
        "New question",
        "--body",
        "Commit only this question.",
        "--context",
        "infra",
    )
    assert result.returncode == 0, result.stderr
    match = WROTE.fullmatch(result.stdout)
    assert match is not None
    assert git_kb.git("show", "--name-only", "--format=", "HEAD").split() == [
        f"questions/open/{match.group(1)}"
    ]
    assert git_kb.git("diff", "--cached", "--name-only").split() == ["knowledge/staged.md"]
    assert git_kb.git("status", "--porcelain").splitlines() == [
        "A  knowledge/staged.md",
        "?? knowledge/unstaged.md",
    ]


@pytest.mark.parametrize("edit_question", [False, True])
def test_failed_commit_removes_only_the_new_question(git_kb: Kb, edit_question: bool) -> None:
    existing_question = git_kb.content / "questions" / "open" / "existing.md"
    existing_question.write_text(
        "---\ntitle: Existing question\n---\n\nKeep this question.\n", encoding="utf-8"
    )
    existing_observation = (
        git_kb.content / "observations" / "pending" / "20261026T110000-aaaa1111.md"
    )
    existing_observation.write_text(
        "---\ntitle: Existing observation\n---\n\nKeep this observation.\n", encoding="utf-8"
    )
    git_kb.git(
        "add", "questions/open/existing.md", "observations/pending/20261026T110000-aaaa1111.md"
    )
    git_kb.git("commit", "-q", "-m", "Add existing evidence")
    before_head = git_kb.git("rev-parse", "HEAD")
    existing_question.write_text("Existing staged change.\n", encoding="utf-8")
    git_kb.git("add", "questions/open/existing.md")
    existing_question.write_text("Existing unstaged change.\n", encoding="utf-8")
    before_status = git_kb.git("status", "--porcelain")
    before_index = git_kb.git("show", ":questions/open/existing.md")
    before_questions = sorted(
        path.name for path in (git_kb.content / "questions/open").glob("*.md")
    )
    before_pending = sorted(
        path.name for path in (git_kb.content / "observations/pending").glob("*.md")
    )
    hook = git_kb.content / ".git" / "hooks" / "pre-commit"
    edit = (
        "git diff --cached --name-only --diff-filter=A -- questions/open | "
        "while IFS= read -r path; do\n"
        "    printf '\\nHook edit\\n' >> \"$path\"\n"
        "done\n"
        if edit_question
        else ""
    )
    hook.write_text(
        f"#!/bin/sh\n{edit}echo 'hook rejected the commit' >&2\nexit 1\n", encoding="utf-8"
    )
    hook.chmod(0o755)

    result = git_kb(
        "gap",
        "--title",
        "Rejected question",
        "--body",
        "Do not leave a partial write.",
        "--context",
        "infra",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("gap: commit failed:")
    assert "hook rejected the commit" in result.stderr
    assert git_kb.git("rev-parse", "HEAD") == before_head
    assert sorted(path.name for path in (git_kb.content / "questions/open").glob("*.md")) == (
        before_questions
    )
    assert sorted(path.name for path in (git_kb.content / "observations/pending").glob("*.md")) == (
        before_pending
    )
    assert git_kb.git("diff", "--cached", "--name-only") == "questions/open/existing.md\n"
    assert git_kb.git("show", ":questions/open/existing.md") == before_index
    assert existing_question.read_text(encoding="utf-8") == "Existing unstaged change.\n"
    assert existing_observation.read_text(encoding="utf-8").endswith("Keep this observation.\n")
    assert git_kb.git("status", "--porcelain") == before_status
    assert list((git_kb.content / ".git" / "kb-tmp").iterdir()) == []


def test_kernel_lock_blocks_gap_before_publication(git_kb: Kb) -> None:
    before_questions = sorted(
        path.name for path in (git_kb.content / "questions/open").glob("*.md")
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_KERNEL_LOCK, str(git_kb.content / ".git" / "kb.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        result = git_kb(
            "gap", "--title", "Blocked", "--body", "Wait for the lock.", "--context", "infra"
        )
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "gap: content repository is busy (waited 1s for the lock)\n"
    assert sorted(path.name for path in (git_kb.content / "questions/open").glob("*.md")) == (
        before_questions
    )
    assert list((git_kb.content / ".git" / "kb-tmp").iterdir()) == []
    assert not (git_kb.content / ".observe.lock").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="legacy lock is a POSIX-only protocol")
def test_held_legacy_lock_blocks_gap_and_is_left_alone(git_kb: Kb) -> None:
    before_questions = sorted(
        path.name for path in (git_kb.content / "questions/open").glob("*.md")
    )
    legacy = git_kb.content / ".observe.lock"
    legacy.mkdir()
    (legacy / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    result = git_kb(
        "gap",
        "--title",
        "Blocked",
        "--body",
        "The old writer holds the lock.",
        "--context",
        "infra",
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "gap: content repository is busy (waited 1s for the lock)\n"
    assert sorted(entry.name for entry in legacy.iterdir()) == ["pid"]
    assert (legacy / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"
    assert sorted(path.name for path in (git_kb.content / "questions/open").glob("*.md")) == (
        before_questions
    )

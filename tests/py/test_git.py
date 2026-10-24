"""How the writers interact with git: messages, paths, dirty trees, locks, hooks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.inspect import tree
from kbtest.runner import KB


def _subjects_and_files(kb: KB) -> str:
    return kb.norm(kb.git("log", "--format=%s", "--name-status"))


def test_commit_messages_and_paths(kb: KB, golden: Golden) -> None:
    """Each writer's commit: its subject and exactly the paths it changed."""
    assert kb.run("observe", "--title", "Observed fact", "--body", "Body").returncode == 0
    assert kb.run("ask", "--title", "Open question?").returncode == 0
    (question,) = (kb.layout.content / "questions" / "open").glob("*.md")
    assert kb.run("resolve", "--file", question.name, "--answer", "Answered.").returncode == 0
    (observation,) = (kb.layout.content / "observations" / "pending").glob("*.md")
    assert kb.run("archive", observation.name).returncode == 0
    kb.create_article(
        "topic.md",
        '---\ntitle: "T"\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n\n# T\n\n## S\n\nC.',
    )
    assert kb.run("commit", "-m", "Curate: topic").returncode == 0
    sessions = kb.layout.sessions
    sessions.mkdir(mode=0o700, parents=True)
    buffer = sessions / "buffer.jsonl"
    buffer.write_text(
        "".join(
            json.dumps({"role": r, "message": m}) + "\n"
            for r, m in [("user", "Q"), ("assistant", "A"), ("user", "Q2")]
        ),
        encoding="utf-8",
    )
    assert kb.run("session-flush", str(buffer)).returncode == 0
    log = _subjects_and_files(kb)
    golden.contract("log", log)
    assert kb.git("status", "--porcelain") == ""


def test_observe_leaves_other_work_alone(kb: KB, golden: Golden) -> None:
    """An observe commit takes neither staged nor unstaged work in progress."""
    staged = kb.create_article("staged.md", "# Staged")
    kb.git("add", "knowledge/staged.md")
    unstaged = kb.layout.content / ".gitkeep"
    unstaged.write_text("edited\n", encoding="utf-8")
    kb.create_article("untracked.md", "# Untracked")
    assert kb.run("observe", "--title", "Fact", "--body", "Body").returncode == 0
    golden.contract("head", kb.norm(kb.git("show", "--name-status", "--format=%s", "HEAD")))
    golden.contract("status", kb.git("status", "--porcelain"))
    assert staged.is_file() and unstaged.read_text() == "edited\n"


@pytest.mark.audit("A-039")
@pytest.mark.parametrize("script", ["observe", "ask", "commit", "sync", "status"])
def test_content_dir_is_not_a_repository(kb: KB, golden: Golden, script: str) -> None:
    plain = kb.layout.root / "plain"
    for sub in (
        "knowledge",
        "observations/pending",
        "observations/archived",
        "questions/open",
        "sources",
    ):
        (plain / sub).mkdir(parents=True)
    args = {
        "observe": ["--title", "T", "--body", "B"],
        "ask": ["--title", "Q?"],
        "commit": ["-m", "Curate: x"],
        "sync": [],
        "status": [],
    }[script]
    result = kb.run(script, *args, env={"KB_CONTENT_DIR": str(plain)})
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("files", kb.norm(tree(plain)))
    if script == "status":
        assert "Knowledge articles=0" in facts.status(result.out), "status reports without git"
    if result.returncode != 0:
        assert result.err.strip(), "a failing run must say why"
    golden.check("stdout", kb.norm(result.out).replace(str(plain), "<PLAIN>"))
    golden.check("stderr", kb.norm_err(result.err).replace(str(plain), "<PLAIN>"))


def _index_lock(kb: KB, age_minutes: int) -> Path:
    lock = kb.layout.content / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    then = time.time() - age_minutes * 60
    os.utime(lock, (then, then))
    return lock


@pytest.mark.audit("A-003")
def test_stale_index_lock_is_removed(kb: KB, golden: Golden) -> None:
    lock = _index_lock(kb, 10)
    result = kb.run("observe", "--title", "After crash", "--body", "Body")
    assert result.returncode == 0, result.err
    assert not lock.exists()
    assert "Removed stale git lock" in result.err
    golden.contract("log", kb.git("log", "-1", "--format=%s"))


def test_recent_index_lock_is_kept(kb: KB) -> None:
    lock = _index_lock(kb, 1)
    result = kb.run("observe", "--title", "Blocked", "--body", "Body")
    assert result.returncode != 0 and result.err.strip()
    assert lock.exists()


@pytest.mark.audit("A-003")
def test_index_lock_kept_while_git_runs(kb: KB) -> None:
    lock = _index_lock(kb, 10)
    # A process whose command line looks like git working in this repository.
    holder = subprocess.Popen(
        ["bash", "-c", f'exec -a "git status {kb.layout.content}" sleep 60'],
    )
    try:
        time.sleep(0.2)
        result = kb.run("observe", "--title", "Blocked", "--body", "Body")
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode != 0 and result.err.strip()
    assert lock.exists()


def test_installed_hook_runs_on_observe_commits(hooked: KB) -> None:
    """Every observe commit runs the content repository's pre-commit hook."""
    hook = hooked.layout.content / ".git" / "hooks" / "pre-commit"
    real = hook.resolve()
    log = hooked.layout.root / "hook-runs"
    hook.unlink()
    hook.write_text(f"#!/bin/sh\necho ran >> '{log}'\nexec '{real}' \"$@\"\n", encoding="utf-8")
    hook.chmod(0o755)
    for index in range(2):
        assert hooked.run("observe", "--title", f"T{index}", "--body", "B").returncode == 0
    assert log.read_text(encoding="utf-8") == "ran\nran\n"

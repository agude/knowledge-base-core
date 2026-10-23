"""commit: stage curation work and commit it under the capture lock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git_log
from kbtest.runner import KB, Result

ARTICLE = """---
title: "{title}"
updated: 2020-01-01
verified: 2026-08-08
---

# {title}

## Section

Content."""

TWO_H1 = """---
title: "Bad"
updated: 2026-08-08
verified: 2026-08-08
---

# One

## S

Content.

# Two

## T

Content."""


@pytest.fixture
def hooked(kb: KB) -> KB:
    """The content repository with the implementation's pre-commit hook installed."""
    tree = kb.resolve_impl(kb.default_impl)
    hooks = kb.layout.content / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-commit").symlink_to(tree.executable("hooks/pre-commit"))
    # The hook stamps `updated:` with the real UTC date.
    kb.normalizer.extra[datetime.now(UTC).strftime("%Y-%m-%d")] = "<TODAY>"
    return kb


def _check(
    kb: KB, golden: Golden, result: Result, *, log: bool = True, stdout: bool = True
) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    if stdout:
        golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    if log:
        golden.check("log", kb.norm(git_log(kb.layout.content, kb.git_env())))
    golden.check("status", kb.norm(kb.git("status", "--porcelain")))
    lock = kb.layout.content / ".observe.lock"
    golden.check("lock", "held\n" if lock.exists() else "released\n")


@pytest.mark.bats("commit.bats", "commit requires a message")
def test_commit_requires_message(hooked: KB, golden: Golden) -> None:
    _check(hooked, golden, hooked.run("commit"))


@pytest.mark.bats("commit.bats", "commit reports nothing to do on a clean tree")
def test_commit_clean_tree(hooked: KB, golden: Golden) -> None:
    _check(hooked, golden, hooked.run("commit", "-m", "Curate: nothing"))


@pytest.mark.bats("commit.bats", "commit stages and commits articles")
@pytest.mark.bats("commit.bats", "commit keeps the hook's updated stamp")
def test_commit_article(hooked: KB, golden: Golden) -> None:
    hooked.create_article("net.md", ARTICLE.format(title="Networking"))
    _check(hooked, golden, hooked.run("commit", "-m", "Curate: networking"))
    golden.check("committed", hooked.norm(hooked.git("show", "HEAD:knowledge/net.md")))


@pytest.mark.bats("commit.bats", "commit fails when an article does not lint")
@pytest.mark.bats("commit.bats", "commit releases the lock when the hook rejects")
@pytest.mark.audit("A-010")
def test_commit_lint_failure(hooked: KB, golden: Golden) -> None:
    hooked.create_article("bad.md", TWO_H1)
    _check(hooked, golden, hooked.run("commit", "-m", "Curate: bad"))


@pytest.mark.bats("commit.bats", "commit picks up archived observations")
def test_commit_archived_observation(hooked: KB, golden: Golden) -> None:
    name = "20260412T000000-0000aaaa.md"
    hooked.create_observation(name, "Obs", "Body")
    hooked.git("add", "observations/")
    hooked.git("commit", "-q", "-m", "Observe: Obs")
    pending = hooked.layout.content / "observations" / "pending" / name
    pending.rename(hooked.layout.content / "observations" / "archived" / name)
    _check(hooked, golden, hooked.run("commit", "-m", "Curate: archive"))
    golden.check("tree", hooked.norm(hooked.git("ls-tree", "-r", "--name-only", "HEAD")))


def test_commit_all_areas(hooked: KB, golden: Golden) -> None:
    hooked.create_article("a.md", ARTICLE.format(title="A"))
    hooked.create_observation("20260412T000000-0000bbbb.md", "Obs", "Body")
    hooked.create_question("q.md", "Why?")
    (hooked.layout.content / "sources" / "s.txt").write_text("source\n", encoding="utf-8")
    _check(hooked, golden, hooked.run("commit", "-m", "Curate: all"))


@pytest.mark.audit("A-009")
def test_commit_ignores_files_outside_content_areas(hooked: KB, golden: Golden) -> None:
    (hooked.layout.content / "notes.txt").write_text("loose\n", encoding="utf-8")
    result = hooked.run("commit", "-m", "Curate: loose")
    # stdout is git's own status text, whose wording varies by git version.
    assert "nothing added to commit" in result.out
    _check(hooked, golden, result, stdout=False)


def test_commit_outside_git_repository(hooked: KB, golden: Golden) -> None:
    plain = hooked.layout.root / "plain"
    plain.mkdir()
    result = hooked.run("commit", "-m", "Curate: x", env={"KB_CONTENT_DIR": str(plain)})
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stderr", hooked.norm_err(result.err))


def test_commit_long_option(hooked: KB, golden: Golden) -> None:
    hooked.create_article("net.md", ARTICLE.format(title="Networking"))
    _check(hooked, golden, hooked.run("commit", "--message", "Curate: long"))


def test_commit_message_requires_argument(hooked: KB, golden: Golden) -> None:
    _check(hooked, golden, hooked.run("commit", "-m"), log=False)

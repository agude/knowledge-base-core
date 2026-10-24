"""archive: move pending observations to the archive (non-batch use).

Batch completion (--batch) is covered with batch.bats.
"""

from __future__ import annotations

import subprocess

import pytest

from kbtest.golden import Golden
from kbtest.inspect import git_log, tree
from kbtest.runner import KB, Result

LEGACY_BROKEN_LINK = """---
title: "Legacy"
updated: 2020-01-01
verified: 2020-01-01
---

# Legacy

## Historical

See [the missing article](missing.md)."""

LEGACY_SOURCE = """---
title: "Legacy"
updated: 2020-01-01
verified: 2020-01-01
sources:
  - observations/archived/evidence.md
---

# Legacy

## Historical

This article retains an archived source reference."""


def _seed(kb: KB, *names: str) -> None:
    for index, name in enumerate(names):
        kb.create_observation(name, f"Title {index}", f"Body {index}")
    kb.git("add", "-A")
    kb.git("commit", "-q", "-m", "add obs")


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    golden.contract("observations", kb.norm(tree(kb.layout.content / "observations")))
    golden.contract("log", kb.norm(git_log(kb.layout.content, kb.git_env())))
    lock = kb.layout.content / ".observe.lock"
    golden.contract("lock", "held\n" if lock.exists() else "released\n")


@pytest.mark.bats("archive.bats", "archive moves file from pending to archived")
@pytest.mark.bats("archive.bats", "archive preserves file content")
@pytest.mark.audit("A-011")
def test_archive_one(kb: KB, golden: Golden) -> None:
    _seed(kb, "obs1.md")
    _check(kb, golden, kb.run("archive", "obs1.md", "--no-commit"))
    archived = kb.layout.content / "observations" / "archived" / "obs1.md"
    golden.contract("archived", archived.read_text(encoding="utf-8"))


@pytest.mark.bats("archive.bats", "archive handles multiple files")
def test_archive_several(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md", "b.md")
    _check(kb, golden, kb.run("archive", "a.md", "b.md", "--no-commit"))


@pytest.mark.bats("archive.bats", "archive --all moves everything")
def test_archive_all(kb: KB, golden: Golden) -> None:
    _seed(kb, "c.md", "a.md", "b.md")
    _check(kb, golden, kb.run("archive", "--all", "--no-commit"))


@pytest.mark.bats("archive.bats", "archive fails for nonexistent file")
def test_archive_missing(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("archive", "nonexistent.md", "--no-commit"))


@pytest.mark.bats("archive.bats", "archive with no args prints message")
def test_archive_no_arguments(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("archive", "--no-commit"))


def test_archive_all_with_nothing_pending(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("archive", "--all"))


def test_archive_commits(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md", "b.md")
    _check(kb, golden, kb.run("archive", "a.md", "b.md"))


def test_archive_partial_success(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md")
    _check(kb, golden, kb.run("archive", "a.md", "missing.md"))


def test_archive_rejects_paths(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md")
    _check(kb, golden, kb.run("archive", "../pending/a.md", "--no-commit"))


def test_archive_existing_destination(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md")
    archived = kb.layout.content / "observations" / "archived" / "a.md"
    archived.write_text("already here\n", encoding="utf-8")
    _check(kb, golden, kb.run("archive", "a.md", "--no-commit"))


@pytest.mark.audit("A-012")
def test_archive_without_front_matter(kb: KB, golden: Golden) -> None:
    pending = kb.layout.content / "observations" / "pending"
    (pending / "plain.md").write_text("Plain body.\n", encoding="utf-8")
    (pending / "rule.md").write_text("Before.\n\n---\n\nAfter.\n", encoding="utf-8")
    result = kb.run("archive", "plain.md", "rule.md", "--no-commit")
    _check(kb, golden, result)
    archived = kb.layout.content / "observations" / "archived"
    golden.contract("plain", (archived / "plain.md").read_text(encoding="utf-8"))
    golden.contract("rule", (archived / "rule.md").read_text(encoding="utf-8"))


def test_archive_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("archive", "--bogus"))


@pytest.mark.parametrize(
    "args",
    [
        ["--disposition", "incorporated", "a.md"],
        ["--destination", "knowledge/x.md", "a.md"],
        ["--disposition", "bogus", "a.md"],
    ],
    ids=["incorporated-without-destination", "destination-without-incorporated", "unknown"],
)
def test_archive_disposition_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    _seed(kb, "a.md")
    _check(kb, golden, kb.run("archive", *args))


def test_archive_disposition_recorded(kb: KB, golden: Golden) -> None:
    _seed(kb, "a.md")
    result = kb.run(
        "archive",
        "--disposition",
        "incorporated",
        "--destination",
        "knowledge/x.md#Heading",
        "a.md",
        "--no-commit",
    )
    _check(kb, golden, result)
    archived = kb.layout.content / "observations" / "archived" / "a.md"
    golden.contract("archived", archived.read_text(encoding="utf-8"))


@pytest.mark.bats("archive.bats", "archive auto-commit ignores unrelated legacy broken references")
def test_archive_commit_ignores_legacy_broken_links(hooked: KB, golden: Golden) -> None:
    hooked.create_observation("obs1.md", "Important", "Critical body content")
    hooked.create_article("legacy.md", LEGACY_BROKEN_LINK)
    hooked.git("add", "-A")
    hooked.git("commit", "-q", "--no-verify", "-m", "Seed legacy content")
    _check(hooked, golden, hooked.run("archive", "obs1.md"))


@pytest.mark.bats("archive.bats", "archived observation removal rejects a broken source reference")
def test_removing_archived_source_is_rejected(hooked: KB, golden: Golden) -> None:
    archived = hooked.layout.content / "observations" / "archived" / "evidence.md"
    archived.write_text("Archived evidence.\n", encoding="utf-8")
    hooked.create_article("legacy.md", LEGACY_SOURCE)
    hooked.git("add", "-A")
    hooked.git("commit", "-q", "--no-verify", "-m", "Seed archived evidence")

    archived.unlink()
    hooked.git("add", "-u", "observations/archived/evidence.md")
    completed = subprocess.run(
        ["git", "commit", "-q", "-m", "Remove archived evidence"],
        cwd=hooked.layout.content,
        env=hooked.git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    golden.contract("result", f"exit {completed.returncode}\n")
    golden.check("stderr", hooked.norm_err(completed.stderr))
    golden.contract("log", hooked.norm(git_log(hooked.layout.content, hooked.git_env())))

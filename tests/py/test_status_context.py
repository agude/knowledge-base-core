"""status and context: summary statistics and the session-start topic list."""

from __future__ import annotations

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result

# Verified three days before the harness's fixed date (2026-10-23).
FRESH = """---
title: "A"
updated: 2026-10-20
verified: 2026-10-20
---

# A"""

OLD = """---
title: "Old"
updated: 2020-01-01
verified: 2020-01-01
---

# Old"""


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


# status


@pytest.mark.bats("status_context.bats", "status runs with empty content")
@pytest.mark.bats("status_context.bats", "status shows content path")
def test_status_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("status"))


@pytest.mark.bats("status_context.bats", "status counts articles")
def test_status_counts(kb: KB, golden: Golden) -> None:
    kb.create_article("a.md", "# A")
    kb.create_article("b.md", "# B")
    kb.create_article("sub/c.md", "# C")
    kb.create_observation("20260412T000000-0000aaaa.md", "Obs", "Body")
    archived = kb.layout.content / "observations" / "archived" / "20260411T000000-0000bbbb.md"
    archived.write_text("archived\n", encoding="utf-8")
    kb.git("add", "-A")
    kb.git("commit", "-q", "-m", "Seed")
    _check(kb, golden, kb.run("status"))


@pytest.mark.bats("status_context.bats", "status --brief prints one line of live state")
def test_status_brief(kb: KB, golden: Golden) -> None:
    kb.create_article("a.md", FRESH)
    kb.create_observation("20260412T000000-0000aaaa.md", "Obs", "Body")
    kb.create_question("20260412T000000-0000bbbb.md", "Who owns this?")
    result = kb.run("status", "--brief")
    assert len(result.out.splitlines()) == 1
    _check(kb, golden, result)


@pytest.mark.bats("status_context.bats", "status --brief counts stale articles")
def test_status_brief_stale(kb: KB, golden: Golden) -> None:
    kb.create_article("old.md", OLD)
    kb.create_article("fresh.md", FRESH)
    _check(kb, golden, kb.run("status", "--brief"))


@pytest.mark.bats("status_context.bats", "status rejects an unknown option")
def test_status_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("status", "--bogus"))


# context


@pytest.mark.bats("status_context.bats", "context runs with empty content")
@pytest.mark.audit("A-016")
def test_context_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("context"))


@pytest.mark.bats("status_context.bats", "context lists topics when articles exist")
def test_context_topics(kb: KB, golden: Golden) -> None:
    kb.create_article("networking.md", "# Networking\n\n## DNS\n\nContent.")
    kb.create_article("storage.md", "# Storage\n\n## Disks\n\nContent.")
    _check(kb, golden, kb.run("context"))


@pytest.mark.bats("status_context.bats", "context lists topics that live only in subdirectories")
def test_context_subdirectory_topics(kb: KB, golden: Golden) -> None:
    kb.create_article("infra/nas.md", "# NAS\n\n## Bind mounts\n\nContent.")
    _check(kb, golden, kb.run("context"))


@pytest.mark.bats("status_context.bats", "context counts sources in subdirectories")
def test_context_sources(kb: KB, golden: Golden) -> None:
    vendor = kb.layout.content / "sources" / "vendor"
    vendor.mkdir()
    (vendor / "manual.md").write_text("# Doc\n", encoding="utf-8")
    _check(kb, golden, kb.run("context"))


@pytest.mark.bats("status_context.bats", "context shows pending count")
def test_context_pending(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "Obs", "Body")
    _check(kb, golden, kb.run("context"))


def test_context_mixed(kb: KB, golden: Golden) -> None:
    kb.create_article("networking.md", "# Networking\n\n## DNS\n\nContent.")
    kb.create_article("infra/nas.md", "# NAS\n\n## Mounts\n\nContent.")
    kb.create_article("infra/deep/disk.md", "# Disk\n\n## SMART\n\nContent.")
    kb.create_observation("a.md", "Obs", "Body")
    kb.create_question("q.md", "Why?")
    _check(kb, golden, kb.run("context"))


@pytest.mark.audit("A-015")
def test_context_unknown_option(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("context", "--bogus"))

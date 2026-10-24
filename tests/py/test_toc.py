"""toc: headings, flat lists, scoped paths, directory trees, and area maps."""

from __future__ import annotations

import shutil
from collections.abc import Callable

import pytest

from kbtest import env as envmod
from kbtest.golden import Golden
from kbtest.runner import KB, Result

ARTICLE = """---
title: "Networking"
---

# Networking

## DNS Resolution

How DNS works.

### Recursive Lookup

Details on recursive lookups.

#### Deeper

Level four.

### Caching

TTL and cache behavior.

## TCP Handshake

Three-way handshake.

## TLS

TLS overview."""

MULTI = """# Multi

## First

### A

### B

## Second

### C"""


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.check("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


def _areas(kb: KB) -> None:
    kb.create_article("loose.md", "# Loose")
    kb.create_article("home/a.md", "# A\n\n## One")
    kb.create_article("home/remodel/b.md", "# B")
    kb.create_article("home/remodel/c.md", "# C")
    kb.create_article("shell/c.md", "# C Shell")
    (kb.layout.content / "knowledge" / "empty").mkdir()


@pytest.mark.bats("toc.bats", "toc --depth 1 shows only H1")
@pytest.mark.bats("toc.bats", "toc --depth 2 shows H1 and numbered H2s")
@pytest.mark.bats("toc.bats", "toc --depth 3 shows dot-numbered H3s")
@pytest.mark.parametrize("depth", ["1", "2", "3", "4"])
def test_toc_depth(kb: KB, golden: Golden, depth: str) -> None:
    kb.create_article("networking.md", ARTICLE)
    _check(kb, golden, kb.run("toc", "--depth", depth))


def test_toc_default_depth(kb: KB, golden: Golden) -> None:
    kb.create_article("networking.md", ARTICLE)
    kb.create_article("b/second.md", "# Second\n\n## Part")
    _check(kb, golden, kb.run("toc"))


@pytest.mark.bats("toc.bats", "toc --flat omits file grouping")
@pytest.mark.parametrize("depth", ["1", "2"])
def test_toc_flat(kb: KB, golden: Golden, depth: str) -> None:
    kb.create_article("networking.md", ARTICLE)
    kb.create_article("b/second.md", "# Second\n\n## Part")
    _check(kb, golden, kb.run("toc", "--flat", "--depth", depth))


@pytest.mark.bats("toc.bats", "toc shows nothing for empty knowledge dir")
@pytest.mark.null_ok("an empty knowledge directory produces no output and exit 0")
def test_toc_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("toc"))


@pytest.mark.bats("toc.bats", "toc --path scopes to a subdirectory")
@pytest.mark.parametrize(
    "path", ["knowledge/sub", "knowledge/sub/topic.md", "sub", "topic.md", "missing"]
)
def test_toc_path(kb: KB, golden: Golden, path: str) -> None:
    kb.create_article("sub/topic.md", "# Sub Topic\n\n## Section One\n\nContent.")
    kb.create_article("other.md", "# Other")
    _check(kb, golden, kb.run("toc", "--path", path))


@pytest.mark.audit("A-019")
@pytest.mark.parametrize("renderer", ["tree", "find"])
def test_toc_dirs(kb: KB, golden: Golden, without_tools: Callable[..., KB], renderer: str) -> None:
    if renderer == "tree" and shutil.which("tree", path=envmod.SYSTEM_PATH) is None:
        pytest.skip("the tree utility is not installed on this host")
    if renderer == "find":
        without_tools("tree")
    _areas(kb)
    _check(kb, golden, kb.run("toc", "--dirs"))


@pytest.mark.bats("toc.bats", "toc --map lists areas with counts")
@pytest.mark.bats("toc.bats", "toc --map counts nested directories in their parent")
@pytest.mark.bats("toc.bats", "toc --map omits directories with no articles")
@pytest.mark.bats("toc.bats", "toc --map reports files loose at the root")
def test_toc_map(kb: KB, golden: Golden) -> None:
    _areas(kb)
    _check(kb, golden, kb.run("toc", "--map"))


@pytest.mark.bats("toc.bats", "toc --map is far smaller than --depth 1")
def test_toc_map_is_compact(kb: KB) -> None:
    for index in range(1, 9):
        kb.create_article(f"area/topic{index}.md", f"# Topic {index}")
    map_out = kb.run("toc", "--map").stdout
    full_out = kb.run("toc", "--depth", "1").stdout
    assert map_out
    assert len(map_out) < len(full_out)


@pytest.mark.bats("toc.bats", "toc h3 counter resets per H2")
def test_toc_h3_counter_resets(kb: KB, golden: Golden) -> None:
    kb.create_article("multi.md", MULTI)
    _check(kb, golden, kb.run("toc", "--depth", "3"))


def test_toc_article_without_h1(kb: KB, golden: Golden) -> None:
    kb.create_article("noh1.md", "Intro.\n\n## Only H2\n\nText.")
    kb.create_article("title.md", '---\ntitle: "Front Matter Title"\n---\n\nBody.')
    _check(kb, golden, kb.run("toc", "--depth", "2"))


@pytest.mark.audit("A-018")
@pytest.mark.parametrize("args", [["--depth"], ["--depth", "x"], ["--depth", "0"], ["--bogus"]])
def test_toc_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article("networking.md", ARTICLE)
    _check(kb, golden, kb.run("toc", *args))

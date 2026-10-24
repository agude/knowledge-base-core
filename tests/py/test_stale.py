"""stale: freshness thresholds, ttl values, sources, and section reports.

Dates are relative to the harness clock (env.TODAY, 2026-10-23), which the
executables read through FRESHNESS_TODAY_EPOCH.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from kbtest import env as envmod
from kbtest.golden import Golden
from kbtest.runner import KB, Result


def days_ago(days: int) -> str:
    return (envmod.TODAY - timedelta(days=days)).strftime("%Y-%m-%d")


def article(verified: str | None, *, title: str = "", ttl: str = "", body: str = "") -> str:
    front = []
    if title:
        front.append(f'title: "{title}"')
    if verified is not None:
        front.append(f"verified: {verified}")
    if ttl:
        front.append(f"ttl: {ttl}")
    heading = title or "Article"
    text = ("---\n" + "\n".join(front) + "\n---\n\n") if front else ""
    return text + f"# {heading}\n\n## Section\n\n{body or 'Content.'}"


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


@pytest.mark.bats("stale.bats", "stale --count prints only a number")
@pytest.mark.bats("stale.bats", "stale --count includes articles with no verified date")
def test_stale_count(kb: KB, golden: Golden) -> None:
    kb.create_article("old.md", article("2020-01-01"))
    kb.create_article("fresh.md", article(days_ago(0)))
    kb.create_article("nodate.md", "# No Date")
    _check(kb, golden, kb.run("stale", "--count"))


@pytest.mark.bats("stale.bats", "stale --count prints 0 for a clean base")
def test_stale_count_clean(kb: KB, golden: Golden) -> None:
    kb.create_article("fresh.md", article(days_ago(0)))
    _check(kb, golden, kb.run("stale", "--count"))


@pytest.mark.bats("stale.bats", "stale reports nothing when no articles exist")
def test_stale_empty(kb: KB, golden: Golden) -> None:
    _check(kb, golden, kb.run("stale"))


@pytest.mark.bats("stale.bats", "stale reports nothing for recently verified article")
def test_stale_recent(kb: KB, golden: Golden) -> None:
    kb.create_article("fresh.md", article(days_ago(0), title="Fresh"))
    _check(kb, golden, kb.run("stale"))


@pytest.mark.bats("stale.bats", "stale flags article with old verified date")
@pytest.mark.bats("stale.bats", "stale flags article with no verified date")
@pytest.mark.bats("stale.bats", "stale shows correct day count")
@pytest.mark.audit("A-024")
def test_stale_report(kb: KB, golden: Golden) -> None:
    kb.create_article("old.md", article("2020-01-01", title="Old"))
    kb.create_article("nodate.md", article(None, title="No Date"))
    kb.create_article("month.md", article(days_ago(61), title="Month"))
    kb.create_article("year.md", article(days_ago(400), title="Year"))
    _check(kb, golden, kb.run("stale"))


@pytest.mark.bats("stale.bats", "stale --days overrides threshold")
@pytest.mark.parametrize("days", [None, "5", "10", "11", "0"])
def test_stale_days(kb: KB, golden: Golden, days: str | None) -> None:
    kb.create_article("recent.md", article(days_ago(10), title="Recent"))
    args = ["--days", days] if days else []
    _check(kb, golden, kb.run("stale", *args))


@pytest.mark.bats("stale.bats", "stale --path scopes to subdirectory")
@pytest.mark.parametrize("path", ["knowledge/sub", "sub", "knowledge/missing"])
def test_stale_path(kb: KB, golden: Golden, path: str) -> None:
    kb.create_article("top.md", article("2020-01-01", title="Top"))
    kb.create_article("sub/deep.md", article("2020-01-01", title="Deep"))
    _check(kb, golden, kb.run("stale", "--path", path))


@pytest.mark.bats("stale.bats", "stale honors a numeric ttl")
@pytest.mark.bats("stale.bats", "stale maps named ttl values")
@pytest.mark.bats("stale.bats", "stale falls back to 60 days without a ttl")
@pytest.mark.bats("stale.bats", "stale ignores an unparseable ttl and uses the default")
def test_stale_ttl_values(kb: KB, golden: Golden) -> None:
    thirty = days_ago(30)
    ninety = days_ago(90)
    kb.create_article("short.md", article(thirty, ttl="14"))
    kb.create_article("long.md", article(thirty, ttl="90"))
    kb.create_article("who.md", article(thirty, ttl="people"))
    kb.create_article("status.md", article(thirty, ttl="status"))
    kb.create_article("process.md", article(ninety, ttl="process"))
    kb.create_article("rules.md", article(thirty, ttl="domain"))
    kb.create_article("plain.md", article(ninety))
    kb.create_article("weird.md", article(ninety, ttl="whenever"))
    _check(kb, golden, kb.run("stale"))


@pytest.mark.bats("stale.bats", "stale --days overrides ttl")
def test_stale_days_overrides_ttl(kb: KB, golden: Golden) -> None:
    kb.create_article("long.md", article(days_ago(30), ttl="365"))
    _check(kb, golden, kb.run("stale", "--days", "10"))


@pytest.mark.bats("stale.bats", "stale reads synced for source documents")
@pytest.mark.bats("stale.bats", "stale reports a source document with no synced date")
def test_stale_sources(kb: KB, golden: Golden) -> None:
    sources = kb.layout.content / "sources"
    (sources / "manual.md").write_text(
        f'---\ntitle: "Vendor Manual"\nsynced: {days_ago(90)}\n---\n\n# Vendor Manual\n',
        encoding="utf-8",
    )
    (sources / "nodate.md").write_text("# No Date\n", encoding="utf-8")
    _check(kb, golden, kb.run("stale", "--path", "sources"))


@pytest.mark.bats("stale.bats", "stale labels an invalid freshness date")
def test_stale_invalid_date(kb: KB, golden: Golden) -> None:
    kb.create_article("bad.md", '---\ntitle: "Bad"\nverified: not-a-date\n---\n\n# Bad')
    _check(kb, golden, kb.run("stale"))


@pytest.mark.bats("stale.bats", "freshness boundary is shared by stale search and section")
def test_freshness_boundary_shared(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "boundary-fresh.md",
        '---\ntitle: "Boundary Fresh"\nverified: 2026-01-01\nttl: 10\n---\n\n'
        "# Boundary Fresh\n\n## Facts\n\nboundary",
    )
    kb.create_article(
        "boundary-stale.md",
        '---\ntitle: "Boundary Stale"\nverified: 2025-12-31\nttl: 10\n---\n\n'
        "# Boundary Stale\n\n## Facts\n\nboundary",
    )
    env = {"FRESHNESS_TODAY_EPOCH": "1768089600"}  # 2026-01-11, 10 days after 2026-01-01
    golden.contract("stale-count", kb.run("stale", "--count", env=env).out)
    search = json.loads(kb.run("search", "--json", "boundary", env=env).out)
    statuses = {r["path"]: r["freshness"]["status"] for r in search["results"]}
    golden.contract("search-status", json.dumps(statuses, indent=2, sort_keys=True) + "\n")
    section = json.loads(
        kb.run(
            "section", "--json", "--file", "knowledge/boundary-fresh.md", "--number", "1", env=env
        ).out
    )
    golden.contract("section-freshness", json.dumps(section["freshness"], indent=2) + "\n")


@pytest.mark.bats("stale.bats", "stale --sections reports the affected locator")
@pytest.mark.bats("stale.bats", "stale --sections preserves an explicit section count")
@pytest.mark.parametrize("args", [["--sections"], ["--sections", "--count"]])
def test_stale_sections(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article(
        "mixed.md",
        '---\ntitle: "Mixed"\nverified: 2026-10-03\n---\n\n# Mixed\n\n## Historical\n\n'
        "<!-- kb-section: verified=2026-01-01; status=superseded -->\nOld guidance.\n\n"
        "## Current\n\n<!-- kb-section: verified=2026-01-01 -->\nOld current guidance.\n\n"
        "## Replacement\n\nCurrent guidance.",
    )
    _check(kb, golden, kb.run("stale", *args, env={"FRESHNESS_TODAY_EPOCH": "1790985600"}))


@pytest.mark.audit("A-023")
@pytest.mark.parametrize("args", [["--days"], ["--days", "x"], ["--bogus"]])
def test_stale_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("stale", *args))

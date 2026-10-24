"""lint: article structure, metadata, links, sources, and section metadata."""

from __future__ import annotations

import re
import shutil

import pytest

from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.runner import KB, Result

FIXTURES = REPO / "tests" / "fixtures"

GOOD = """---
title: "Networking"
updated: 2026-08-08
verified: 2026-08-08
---

# Networking

## DNS

How DNS works.

## TLS

TLS overview."""

FILLER = "filler\n" * 60


def front(
    title: str, *, updated: str = "2026-08-08", verified: str | None = "2026-08-08", extra: str = ""
) -> str:
    lines = [f'title: "{title}"', f"updated: {updated}"]
    if verified is not None:
        lines.append(f"verified: {verified}")
    if extra:
        lines.append(extra)
    return "---\n" + "\n".join(lines) + "\n---\n\n"


LONG = front("Long") + "# Long\n\n## Big Section\n\n" + FILLER


SUMMARY = re.compile(r"^(\d+) file\(s\): (\d+) error\(s\), (\d+) warning\(s\)$", re.MULTILINE)
FINDING = re.compile(r"^  (error|warning) +(\S+:\d+)  ", re.MULTILINE)


def _lint_facts(text: str) -> str:
    """Lint's verdict: the summary counts and each finding's severity and location.

    Message wording is reference; what was found, where, and how severe is contract.
    """
    summary = SUMMARY.search(text)
    lines = [f"summary {' '.join(summary.groups())}" if summary else "summary none"]
    lines += [f"{severity} {location}" for severity, location in FINDING.findall(text)]
    return "\n".join(lines) + "\n"


def _check(kb: KB, golden: Golden, result: Result) -> None:
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("lint", kb.norm(_lint_facts(result.out + result.err)))
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))


def _start_batch(kb: KB) -> str:
    kb.git("add", "observations/pending")
    kb.git("commit", "-q", "-m", "add test observation")
    out = kb.run("batch", "start").out
    match = re.search(r"^Created batch: (\S+)$", out, re.MULTILINE)
    assert match, out
    return match.group(1)


def _archived(kb: KB, name: str, text: str) -> None:
    path = kb.layout.content / "observations" / "archived" / name
    path.write_text(text + "\n", encoding="utf-8")


@pytest.mark.bats("lint.bats", "lint passes a well-formed article")
def test_lint_good(kb: KB, golden: Golden) -> None:
    kb.create_article("net.md", GOOD)
    _check(kb, golden, kb.run("lint"))


@pytest.mark.bats("lint.bats", "lint validates relative links, anchors, and source references")
def test_lint_valid_links(kb: KB, golden: Golden) -> None:
    kb.create_article("target.md", front("Target") + "# Target\n\n## Details\n\nContent.")
    _archived(kb, "evidence.md", "archived evidence")
    kb.create_article(
        "linked.md",
        front("Linked", extra="sources:\n  - observations/archived/evidence.md")
        + "# Linked\n\n## Links\n\n[Target](target.md#details), [angle](<target.md>), "
        "and [external](https://example.com/missing.md).\n",
    )
    _check(kb, golden, kb.run("lint", "--file", "knowledge/linked.md"))


@pytest.mark.bats("lint.bats", "lint flags missing links, anchors, and source references")
def test_lint_broken_links(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "broken.md",
        front("Broken", extra="sources:\n  - observations/archived/moved.md")
        + "# Broken\n\n## Links\n\n[Missing](missing.md) and [wrong anchor](broken.md#not-a-heading).\n"
        "[Moved](moved.md).\n",
    )
    kb.create_article("renamed.md", GOOD)
    _check(kb, golden, kb.run("lint", "--file", "knowledge/broken.md"))


@pytest.mark.bats("lint.bats", "lint ignores external URLs and fenced examples")
def test_lint_ignores_external_and_fenced(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "fenced-links.md",
        front("Fenced Links")
        + "# Fenced Links\n\n## Examples\n\n```markdown\n[Missing](missing.md)\n```\n\n"
        "[External](https://example.com/missing.md)\n\n`[Inline example](missing-inline.md)`\n",
    )
    _check(kb, golden, kb.run("lint", "--file", "knowledge/fenced-links.md"))


@pytest.mark.bats(
    "lint.bats", "lint accepts a selected pending observation as a future archive source"
)
def test_lint_batch_future_source(kb: KB, golden: Golden) -> None:
    kb.create_observation("selected.md", "Selected", "Evidence")
    batch = _start_batch(kb)
    kb.create_article(
        "pending-source.md",
        front("Pending Source", extra="sources:\n  - observations/archived/selected.md")
        + "# Pending Source\n\n## Claim\n\nClaim.",
    )
    with_batch = kb.run("lint", "--batch", batch, "--file", "knowledge/pending-source.md")
    without_batch = kb.run("lint", "--file", "knowledge/pending-source.md")
    kb.run(
        "archive",
        "--batch",
        batch,
        "--disposition",
        "incorporated",
        "--destination",
        "knowledge/pending-source.md#Claim",
        "selected.md",
        "--no-commit",
    )
    after_archive = kb.run("lint", "--file", "knowledge/pending-source.md")
    for name, result in (
        ("with-batch", with_batch),
        ("without-batch", without_batch),
        ("archived", after_archive),
    ):
        golden.contract(f"{name}-result", f"exit {result.returncode}\n")
        golden.check(f"{name}-stderr", kb.norm_err(result.err))
        golden.check(f"{name}-stdout", kb.norm(result.out))


@pytest.mark.bats(
    "lint.bats", "lint rejects a deferred observation used as a future archive source"
)
def test_lint_batch_deferred_source(kb: KB, golden: Golden) -> None:
    kb.create_observation("deferred.md", "Deferred", "Evidence")
    batch = _start_batch(kb)
    kb.run("batch", "defer", batch, "deferred.md")
    kb.create_article(
        "deferred-source.md",
        front("Deferred Source", extra="sources:\n  - observations/archived/deferred.md")
        + "# Deferred Source\n\n## Claim\n\nClaim.",
    )
    _check(kb, golden, kb.run("lint", "--batch", batch, "--file", "knowledge/deferred-source.md"))


@pytest.mark.bats(
    "lint.bats", "correction fixture preserves superseded evidence and canonical reason"
)
def test_lint_corrections_fixture(kb: KB, golden: Golden) -> None:
    fixture = FIXTURES / "lint" / "corrections"
    shutil.copytree(fixture / "knowledge", kb.layout.content / "knowledge", dirs_exist_ok=True)
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    article = kb.layout.content / "knowledge" / "corrections.md"
    before = article.read_text(encoding="utf-8")
    _check(kb, golden, kb.run("lint", "--path", str(kb.layout.content / "knowledge")))
    assert article.read_text(encoding="utf-8") == before
    for text in ("Effective 2026-09-01", "Retained old evidence", "Reason: authoritative roster"):
        assert text in before


STRUCTURE = {
    "second-h1": GOOD + "\n\n# Second Title\n\n## More\n\nContent.",
    "no-h1": front("No Title") + "## Section\n\nContent.",
    "missing-verified": front("Bare", verified=None) + "# Bare\n\n## Section\n\nContent.",
    "bad-verified": front("Bad", verified="last Tuesday") + "# Bad\n\n## Section\n\nContent.",
    "unclosed-fence": front("Open") + "# Open\n\n## Section\n\n```bash\necho hi",
    "fenced-heading": front("Fenced")
    + "# Fenced\n\n## Section\n\n```bash\n# a comment, not a second H1\necho hi\n```",
    "oversized-h2": LONG,
    "duplicate-h2": front("Dup")
    + "# Dup\n\n## Setup\n\nFirst.\n\n## Other\n\nMiddle.\n\n## Setup\n\nSecond.",
    "no-front-matter": "# Only\n\n## Section\n\nContent.",
    "missing-title": "---\nupdated: 2026-08-08\nverified: 2026-08-08\n---\n\n# T\n\n## S\n\nC.",
}


@pytest.mark.bats("lint.bats", "lint flags a second H1")
@pytest.mark.bats("lint.bats", "lint flags a file with no H1")
@pytest.mark.bats("lint.bats", "lint flags missing verified")
@pytest.mark.bats("lint.bats", "lint flags a malformed verified date")
@pytest.mark.bats("lint.bats", "lint flags an unclosed code fence")
@pytest.mark.bats("lint.bats", "lint does not count headings inside fences as H1s")
@pytest.mark.bats("lint.bats", "lint warns about an oversized H2 without failing")
@pytest.mark.bats("lint.bats", "lint warns about duplicate H2 text")
@pytest.mark.audit("A-028")
@pytest.mark.parametrize("case", sorted(STRUCTURE))
def test_lint_structure(kb: KB, golden: Golden, case: str) -> None:
    kb.create_article(f"{case}.md", STRUCTURE[case])
    _check(kb, golden, kb.run("lint"))


@pytest.mark.bats("lint.bats", "lint --strict fails on warnings")
@pytest.mark.bats("lint.bats", "lint --max-lines raises the threshold")
@pytest.mark.parametrize(
    "args",
    [
        ["--strict"],
        ["--max-lines", "100"],
        ["--max-lines", "10"],
        ["--strict", "--max-lines", "100"],
    ],
)
def test_lint_thresholds(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article("long.md", LONG)
    _check(kb, golden, kb.run("lint", *args))


SECTIONS_VALID = front("Sections", updated="2026-10-03", verified="2026-10-03") + (
    "# Sections\n\n## Current\n\n"
    "<!-- kb-section: effective=2026-09-01; status=current; supersedes=2; "
    "sources=observations/archived/section.md -->\nCurrent guidance.\n\n"
    "## Replacement\n\n<!-- kb-section: verified=2026-01-01; status=superseded -->\nOlder replacement."
)

SECTIONS_INVALID = {
    "effective-after-verified": "## Broken\n\n<!-- kb-section: effective=2026-10-04; status=superseded -->\nBroken guidance.",
    "self-supersession": "## Current\n\n<!-- kb-section: status=current; supersedes=1 -->\nCurrent guidance.",
    "cycle": (
        "## Current\n\n<!-- kb-section: status=current; supersedes=2 -->\nCurrent guidance.\n\n"
        "## Previous\n\n<!-- kb-section: status=current; supersedes=1 -->\nPrevious guidance."
    ),
    "backward-link": (
        "## Current\n\n<!-- kb-section: status=current; supersedes=2 -->\nCurrent guidance.\n\n"
        "## Historical\n\n<!-- kb-section: status=superseded; supersedes=1 -->\nHistorical guidance."
    ),
    "unclosed": "## Unclosed\n\n<!-- kb-section: verified=2026-01-01; status=superseded\nHistorical guidance.",
    "conflicting": "## Contradictory\n\n<!-- kb-section: status=current; status=superseded -->\nContradictory guidance.",
}


@pytest.mark.bats("lint.bats", "lint validates section metadata and local section sources")
def test_lint_section_metadata_valid(kb: KB, golden: Golden) -> None:
    _archived(kb, "section.md", "section evidence")
    kb.create_article("sections.md", SECTIONS_VALID)
    _check(kb, golden, kb.run("lint", "--file", "knowledge/sections.md"))


@pytest.mark.bats("lint.bats", "lint rejects invalid section metadata")
@pytest.mark.bats("lint.bats", "lint rejects invalid supersession links and cycles")
@pytest.mark.bats("lint.bats", "lint rejects unclosed and contradictory section metadata")
@pytest.mark.parametrize("case", sorted(SECTIONS_INVALID))
def test_lint_section_metadata_invalid(kb: KB, golden: Golden, case: str) -> None:
    body = (
        front(case, updated="2026-10-03", verified="2026-10-03")
        + f"# {case}\n\n"
        + SECTIONS_INVALID[case]
    )
    kb.create_article(f"{case}.md", body)
    _check(kb, golden, kb.run("lint", "--file", f"knowledge/{case}.md"))


@pytest.mark.bats("lint.bats", "lint accepts the section metadata fixture")
@pytest.mark.bats("lint.bats", "lint reports fixture section metadata failures")
@pytest.mark.parametrize("name", ["metadata.md", "invalid.md"])
def test_lint_section_metadata_fixture(kb: KB, golden: Golden, name: str) -> None:
    fixture = FIXTURES / "section-metadata"
    shutil.copy(fixture / "knowledge" / name, kb.layout.content / "knowledge" / name)
    if name == "metadata.md":
        shutil.copytree(
            fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
        )
    _check(kb, golden, kb.run("lint", "--file", f"knowledge/{name}"))


@pytest.mark.bats("lint.bats", "lint --path scopes to a subdirectory")
@pytest.mark.bats("lint.bats", "lint accepts a single file")
@pytest.mark.parametrize(
    "args",
    [
        ["--path", "knowledge/bad"],
        ["--path", "bad"],
        ["--file", "knowledge/ok.md"],
        ["--file", "ok.md"],
        [],
    ],
    ids=["path", "bare-path", "file", "bare-file", "all"],
)
def test_lint_scope(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article("ok.md", GOOD)
    kb.create_article("bad/broken.md", "# Only\n\n## Section\n\nContent.")
    _check(kb, golden, kb.run("lint", *args))


@pytest.mark.bats(
    "lint.bats", "lint rejects an existing file outside the content root before reading it"
)
@pytest.mark.bats("lint.bats", "lint rejects an existing symlink that escapes the content root")
@pytest.mark.parametrize("via", ["path", "symlink"])
def test_lint_rejects_outside_content(kb: KB, golden: Golden, via: str) -> None:
    external = kb.layout.root / "external.md"
    external.write_text("# Not an article\n", encoding="utf-8")
    target = external
    if via == "symlink":
        target = kb.layout.content / "knowledge" / "escaped.md"
        target.symlink_to(external)
    result = kb.run("lint", "--file", str(target))
    _check(kb, golden, result)
    assert "no H1" not in result.out + result.err


@pytest.mark.parametrize(
    "args", [["--max-lines"], ["--max-lines", "x"], ["--bogus"], ["--file", "missing.md"]]
)
def test_lint_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    _check(kb, golden, kb.run("lint", *args))

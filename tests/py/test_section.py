"""section: selectors, output modes, metadata, provenance, and byte budgets."""

from __future__ import annotations

import json
import shutil

import pytest

from kbtest import facts
from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.marks import xfail_bash
from kbtest.runner import KB, Result

FIXTURES = REPO / "tests" / "fixtures"

ARTICLE = """---
title: "Networking"
---

# Networking

## DNS Resolution

How DNS works.

### Recursive Lookup

Recursive resolver details.

### Caching

TTL and cache behavior.

## TCP Handshake

Three-way handshake.

### Client Hello

SYN packet.

### Server Hello

SYN-ACK packet.

## TLS

TLS overview."""

TRUNCATED_MARKER = "[content truncated: retrieve without --max-bytes]"


def _value(result: Result) -> str:
    """The contract view of section output.

    JSON output is compared by parsed value; text output by the content after
    its metadata header (the header's facts are pinned through --json tests).
    """
    try:
        data = json.loads(result.out)
    except ValueError:
        return facts.section_body(result.out)
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _check(kb: KB, golden: Golden, result: Result, name: str = "") -> None:
    prefix = f"{name}-" if name else ""
    golden.contract(f"{prefix}result", f"exit {result.returncode}\n")
    golden.contract(f"{prefix}value", kb.norm(_value(result)))
    if result.returncode != 0:
        assert result.err.strip(), "a failing run must say why"
    golden.check(f"{prefix}stdout", kb.norm(result.out))
    golden.check(f"{prefix}stderr", kb.norm_err(result.err))


def _section(kb: KB, *args: str, env: dict[str, str | None] | None = None) -> Result:
    return kb.run("section", *args, env=env)


def _json(result: Result) -> dict:
    assert result.returncode == 0, result.err
    return json.loads(result.out)


@pytest.mark.bats("section.bats", "section --number extracts H2 by count")
@pytest.mark.bats("section.bats", "section --number with dot notation extracts H3")
@pytest.mark.bats("section.bats", "section --number 1.2 gets second H3 under first H2")
@pytest.mark.bats("section.bats", "section fails for nonexistent number")
@pytest.mark.parametrize(
    "number",
    [
        "1",
        "2",
        "3",
        "2.1",
        "1.2",
        "2.3",
        "99",
        "0",
        pytest.param("x", marks=xfail_bash("A-018: bash does not validate numeric arguments")),
    ],
)
def test_section_number(kb: KB, golden: Golden, number: str) -> None:
    kb.create_article("net.md", ARTICLE)
    result = _section(kb, "--file", "knowledge/net.md", "--number", number)
    assert "unbound variable" not in result.err
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section --heading does substring match")
@pytest.mark.bats("section.bats", "section --heading --exact requires full match")
@pytest.mark.bats("section.bats", "section --heading --exact matches full heading")
@pytest.mark.parametrize(
    "args",
    [
        ["--heading", "DNS"],
        ["--heading", "dns"],
        ["--heading", "DNS", "--exact"],
        ["--heading", "DNS Resolution", "--exact"],
        ["--heading", "Hello"],
        ["--heading", "Caching"],
        ["--heading", "Missing"],
    ],
    ids=["substring", "case", "exact-miss", "exact-hit", "first-of-two", "h3", "missing"],
)
def test_section_heading(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article("net.md", ARTICLE)
    _check(kb, golden, _section(kb, "--file", "knowledge/net.md", *args))


@pytest.mark.bats("section.bats", "section resolves bare filename")
@pytest.mark.parametrize("file", ["net.md", "knowledge/net.md", "missing.md"])
def test_section_file_resolution(kb: KB, golden: Golden, file: str) -> None:
    kb.create_article("net.md", ARTICLE)
    _check(kb, golden, _section(kb, "--file", file, "--number", "1"))


@pytest.mark.bats("section.bats", "section default output labels freshness and provenance")
def test_section_default_labels(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "old.md",
        "---\nverified: 2020-01-01\nsources:\n  - observations/archived/evidence.md\n---\n\n"
        "# Old\n\n## Details\n\nHistorical details.",
    )
    _check(kb, golden, _section(kb, "--file", "knowledge/old.md", "--number", "1"))


@pytest.mark.bats("section.bats", "section exposes unresolved conflicts separately from freshness")
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["text", "json"])
def test_section_conflicts(kb: KB, golden: Golden, mode: list[str]) -> None:
    fixture = FIXTURES / "lint" / "corrections"
    shutil.copytree(fixture / "knowledge", kb.layout.content / "knowledge", dirs_exist_ok=True)
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    result = _section(
        kb, *mode, "--file", "knowledge/corrections.md", "--heading", "Unresolved conflict"
    )
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section text-only preserves the body without metadata")
def test_section_text_only(kb: KB, golden: Golden) -> None:
    kb.create_article("net.md", ARTICLE)
    _check(kb, golden, _section(kb, "--text-only", "--file", "knowledge/net.md", "--number", "1"))


@pytest.mark.bats("section.bats", "section --top retrieves the preamble before the first H2")
@pytest.mark.bats("section.bats", "section --title retrieves the frontmatter title")
@pytest.mark.parametrize("selector", ["--top", "--title"])
@pytest.mark.parametrize(
    "mode", [[], ["--text-only"], ["--json"]], ids=["text", "text-only", "json"]
)
def test_section_top_and_title(kb: KB, golden: Golden, selector: str, mode: list[str]) -> None:
    kb.create_article(
        "top.md",
        '---\ntitle: "A quoted title"\n---\n\n# Top\n\nPreamble text.\n\n## Details\n\nH2 text.',
    )
    _check(kb, golden, _section(kb, *mode, "--file", "knowledge/top.md", selector))


def test_section_title_missing(kb: KB, golden: Golden) -> None:
    kb.create_article("untitled.md", "# Heading\n\nBody.")
    _check(kb, golden, _section(kb, "--file", "knowledge/untitled.md", "--title"))


@pytest.mark.bats(
    "section.bats", "section JSON includes locator, freshness, provenance, and multiline content"
)
def test_section_json_full(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "résumé notes.md",
        '---\ntitle: "Résumé Notes"\nverified: 2020-01-01\nttl: people\nsources:\n'
        '  - "observations/archived/evidence file.md"\n---\n\n# Résumé Notes\n\n## Cité\n\n'
        'Line "one".\nLine two.',
    )
    _check(
        kb,
        golden,
        _section(kb, "--json", "--file", "knowledge/résumé notes.md", "--heading", "Cité"),
    )


@pytest.mark.bats("section.bats", "section JSON includes section metadata and section provenance")
@pytest.mark.parametrize("number", ["1", "2"])
def test_section_json_metadata(kb: KB, golden: Golden, number: str) -> None:
    kb.create_article(
        "section-metadata.md",
        '---\ntitle: "Section Metadata"\nverified: 2026-10-03\n---\n\n# Section Metadata\n\n## Current\n\n'
        "<!-- kb-section: verified=2026-10-03; status=current; supersedes=2 -->\nCurrent guidance.\n\n"
        "## Historical\n\n<!-- kb-section: verified=2026-01-01; status=superseded; "
        "sources=observations/archived/old.md -->\nHistorical guidance.",
    )
    result = _section(
        kb,
        "--json",
        "--file",
        "knowledge/section-metadata.md",
        "--number",
        number,
        env={"FRESHNESS_TODAY_EPOCH": "1790985600"},
    )
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section H3 inherits metadata from its H2")
@pytest.mark.parametrize("number", ["1", "2", "2.1", "3"])
def test_section_metadata_fixture(kb: KB, golden: Golden, number: str) -> None:
    fixture = FIXTURES / "section-metadata"
    shutil.copy(fixture / "knowledge" / "metadata.md", kb.layout.content / "knowledge")
    shutil.copytree(
        fixture / "observations", kb.layout.content / "observations", dirs_exist_ok=True
    )
    _check(
        kb, golden, _section(kb, "--json", "--file", "knowledge/metadata.md", "--number", number)
    )


@pytest.mark.bats("section.bats", "section metadata reports per-field inheritance")
def test_section_field_scopes(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "field-origins.md",
        '---\ntitle: "Field Origins"\nverified: 2026-10-03\nttl: domain\n---\n\n# Field Origins\n\n'
        "## Status override\n\n<!-- kb-section: status=superseded -->\nHistorical guidance.",
    )
    _check(
        kb, golden, _section(kb, "--json", "--file", "knowledge/field-origins.md", "--number", "1")
    )


@pytest.mark.bats(
    "section.bats", "section metadata marks unclosed and contradictory comments invalid"
)
@pytest.mark.parametrize(
    "comment",
    [
        "<!-- kb-section: verified=2026-01-01; status=superseded\nHistorical guidance.",
        "<!-- kb-section: status=current; status=superseded -->\nContradictory guidance.",
    ],
    ids=["unclosed", "contradictory"],
)
def test_section_invalid_metadata(kb: KB, golden: Golden, comment: str) -> None:
    kb.create_article(
        "malformed.md",
        f'---\ntitle: "Malformed"\nverified: 2026-10-03\n---\n\n# Malformed\n\n## Section\n\n{comment}',
    )
    _check(kb, golden, _section(kb, "--json", "--file", "knowledge/malformed.md", "--number", "1"))


@pytest.mark.bats("section.bats", "section references returns the complete provenance list")
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["text", "json"])
def test_section_references(kb: KB, golden: Golden, mode: list[str]) -> None:
    sources = "".join(f"  - observations/evidence-{i}.md\n" for i in range(1, 8))
    kb.create_article(
        "many-sources.md",
        f'---\ntitle: "Many Sources"\nsources:\n{sources}---\n\n# Many Sources\n\n## Facts\n\nDetails.',
    )
    _check(kb, golden, _section(kb, "--references", *mode, "--file", "knowledge/many-sources.md"))


@pytest.mark.bats("section.bats", "article references enforce output byte budgets")
@pytest.mark.parametrize("mode", [[], ["--json"]], ids=["text", "json"])
def test_section_references_budget(kb: KB, golden: Golden, mode: list[str]) -> None:
    kb.create_article(
        "many-sources.md",
        '---\ntitle: "Many Sources"\nsources:\n  - observations/evidence-1.md\n'
        "  - observations/evidence-2.md\n---\n\n# Many Sources\n\nDetails.",
    )
    _check(
        kb,
        golden,
        _section(
            kb, "--references", *mode, "--max-bytes", "1", "--file", "knowledge/many-sources.md"
        ),
    )


@pytest.mark.bats("section.bats", "section rejects an invalid byte budget")
@pytest.mark.parametrize("value", ["nope", "-1"])
def test_section_invalid_budget(kb: KB, golden: Golden, value: str) -> None:
    kb.create_article("budget.md", "# Budget\n\n## Evidence\n\nContent.")
    _check(
        kb,
        golden,
        _section(kb, "--max-bytes", value, "--file", "knowledge/budget.md", "--number", "1"),
    )


def _lines(template: str, count: int) -> str:
    return "".join(template.format(i) + "\n" for i in range(1, count + 1))


BUDGET_BODY = _lines("Complete line {:02d} with enough text to exceed the output budget.", 10)


@pytest.mark.bats("section.bats", "section JSON byte budgets preserve metadata and complete lines")
def test_json_budget_preserves_metadata(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "budget.md",
        '---\ntitle: "Budget"\nverified: 2026-10-03\n---\n\n# Budget\n\n## Evidence\n\n'
        "<!-- kb-section: status=current -->\n" + BUDGET_BODY,
    )
    result = _section(
        kb, "--json", "--max-bytes", "800", "--file", "knowledge/budget.md", "--number", "1"
    )
    assert len(result.stdout) <= 800
    _check(kb, golden, result)


@pytest.mark.bats(
    "section.bats", "section JSON byte budgets serialize each candidate before accepting a line"
)
def test_json_budget_serializes_candidates(kb: KB, golden: Golden) -> None:
    body = "x\ny\nz\nq\n" + _lines("line {:02d} with enough content.", 10)
    kb.create_article(
        "a.md",
        f'---\ntitle: "Budget"\nverified: 2026-10-03\n---\n\n# Budget\n\n## Evidence\n\n{body}',
    )
    result = _section(
        kb, "--json", "--max-bytes", "751", "--file", "knowledge/a.md", "--number", "1"
    )
    assert len(result.stdout) <= 751
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section text-only byte budgets signal truncation")
@pytest.mark.bats(
    "section.bats", "section text budgets clean scratch files after finalizer allocation failures"
)
@pytest.mark.parametrize("mode", [[], ["--text-only"]], ids=["text", "text-only"])
def test_text_budget_truncates_and_cleans_up(kb: KB, golden: Golden, mode: list[str]) -> None:
    body = _lines("Complete line {:02d} with enough text to exceed the output budget.", 40)
    kb.create_article("budget.md", f"# Budget\n\n## Evidence\n\n{body}")
    result = _section(
        kb, *mode, "--max-bytes", "512", "--file", "knowledge/budget.md", "--number", "1"
    )
    assert len(result.stdout) <= 512
    _check(kb, golden, result)
    assert list(kb.layout.tmp.iterdir()) == [], "scratch files left in TMPDIR"


@pytest.mark.bats(
    "section.bats", "section text budgets preserve metadata and a contiguous body prefix"
)
def test_text_budget_contiguous_prefix(kb: KB, golden: Golden) -> None:
    first = (
        "Do not perform this action until the current deployment has been verified "
        "and the rollback procedure is ready."
    )
    second = (
        "Proceed with the action only after verification and record the completed "
        "change in the deployment log for later review."
    )
    kb.create_article(
        "budget.md",
        "---\ntitle: Budget\nverified: 2026-10-03\n---\n\n# Budget\n\n## Evidence\n\n"
        "<!-- kb-section: status=unresolved; sources=observations/archived/evidence.md -->\n"
        f"{first}\n{second}",
    )
    full = _section(kb, "--file", "knowledge/budget.md", "--number", "1").stdout
    prefix = full[: full.index(first.encode()) + len(first) + 1]
    cap = len(prefix) + len((TRUNCATED_MARKER + "\n").encode())
    result = _section(kb, "--max-bytes", str(cap), "--file", "knowledge/budget.md", "--number", "1")
    assert first in result.out
    assert second not in result.out
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section text budgets handle a large bounded prefix")
def test_text_budget_large_prefix(kb: KB, golden: Golden) -> None:
    body = _lines("Large bounded line {:04d} with enough content to exceed the cap.", 1000)
    kb.create_article("large-budget.md", f"# Large Budget\n\n## Evidence\n\n{body}")
    result = _section(
        kb,
        "--text-only",
        "--max-bytes",
        "4096",
        "--file",
        "knowledge/large-budget.md",
        "--number",
        "1",
    )
    assert len(result.stdout) <= 4096
    _check(kb, golden, result)


@pytest.mark.bats(
    "section.bats", "section truncation closes an open fenced block before its marker"
)
@pytest.mark.parametrize(
    ("mode", "cap"),
    [(["--json"], "800"), ([], "800"), (["--text-only"], "180")],
    ids=["json", "text", "text-only"],
)
def test_truncation_closes_fence(kb: KB, golden: Golden, mode: list[str], cap: str) -> None:
    body = _lines("echo line {:02d}", 30)
    kb.create_article("fenced-budget.md", f"# Budget\n\n## Evidence\n\n```bash\n{body}```\n")
    result = _section(
        kb, *mode, "--max-bytes", cap, "--file", "knowledge/fenced-budget.md", "--number", "1"
    )
    assert len(result.stdout) <= int(cap)
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section budget keeps a first oversized body line whole")
def test_budget_oversized_first_line(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "long-first-line.md", "# Budget\n\n## Evidence\n\n" + "x" * 1200 + "\nSecond line."
    )
    result = _section(
        kb,
        "--json",
        "--max-bytes",
        "800",
        "--file",
        "knowledge/long-first-line.md",
        "--number",
        "1",
    )
    assert "x" * 1200 not in result.out
    _check(kb, golden, result)


@pytest.mark.bats("section.bats", "section output modes honor exact and one-byte-short budgets")
@pytest.mark.parametrize(
    "mode", [["--json"], [], ["--text-only"]], ids=["json", "text", "text-only"]
)
def test_exact_and_short_budgets(kb: KB, golden: Golden, mode: list[str]) -> None:
    body = _lines("Budget line {:02d} with enough content to force truncation.", 10)
    kb.create_article("budget-matrix.md", f"# Budget\n\n## Evidence\n\n{body}")
    args = ["--file", "knowledge/budget-matrix.md", "--number", "1"]
    full = _section(kb, *mode, *args)
    exact = _section(kb, *mode, "--max-bytes", str(len(full.stdout)), *args)
    assert exact.stdout == full.stdout
    short_cap = len(full.stdout) - 1
    short = _section(kb, *mode, "--max-bytes", str(short_cap), *args)
    assert short.returncode == 0
    assert len(short.stdout) <= short_cap
    _check(kb, golden, short, "short")


@pytest.mark.bats(
    "section.bats", "section metadata ignores inline examples and rejects misplaced comments"
)
@pytest.mark.parametrize("number", ["1", "2"])
def test_metadata_placement(kb: KB, golden: Golden, number: str) -> None:
    kb.create_article(
        "placement.md",
        "---\ntitle: Placement\nverified: 2026-10-04\n---\n# Placement\n\n## Inline\n"
        "<!-- kb-section: status=current -->\nExample `<!-- kb-section: status=unresolved -->` in prose.\n\n"
        "## Misplaced\nOrdinary body.\n<!-- kb-section: status=superseded -->",
    )
    _check(
        kb, golden, _section(kb, "--json", "--file", "knowledge/placement.md", "--number", number)
    )


@pytest.mark.bats(
    "section.bats", "section metadata before the first section reports invalid placement"
)
def test_metadata_before_first_section(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "leading-metadata.md",
        "---\ntitle: Leading\nverified: 2026-10-04\n---\n# Leading\n"
        "<!-- kb-section: status=unresolved -->\n\n## Evidence\nA fact.",
    )
    _check(
        kb,
        golden,
        _section(kb, "--json", "--file", "knowledge/leading-metadata.md", "--number", "1"),
    )


@pytest.mark.bats("section.bats", "section reference formats agree for every selector")
@pytest.mark.parametrize(
    "selector",
    [
        ["--top"],
        ["--title"],
        ["--number", "1"],
        ["--number", "1.1"],
        ["--heading", "Detail", "--exact"],
    ],
    ids=["top", "title", "parent", "child", "detail"],
)
def test_section_reference_formats_agree(kb: KB, golden: Golden, selector: list[str]) -> None:
    kb.create_article(
        "reference-selectors.md",
        "---\ntitle: Reference selectors\nverified: 2026-10-04\nsources:\n"
        "  - observations/archived/article.md\n---\n# References\nPreamble.\n\n## Parent\n"
        "<!-- kb-section: sources=observations/archived/section.md -->\nBody.\n\n"
        "### Child\nChild body.\n\n#### Detail\nDetail body.",
    )
    args = ["--file", "knowledge/reference-selectors.md", *selector, "--section-references"]
    as_json = _json(_section(kb, *args, "--json"))["provenance"]["references"]
    as_text = _section(kb, *args)
    assert as_text.out.splitlines() == as_json
    golden.contract("references", as_text.out)


@pytest.mark.bats(
    "section.bats", "section ignores metadata comments followed by prose on the closing line"
)
@pytest.mark.parametrize(
    "comment",
    [
        "<!-- kb-section: status=unresolved --> Inline evidence.",
        "<!-- kb-section:\nstatus=unresolved\n--> Inline evidence.",
    ],
    ids=["one-line", "multi-line"],
)
def test_metadata_with_trailing_prose(kb: KB, golden: Golden, comment: str) -> None:
    kb.create_article(
        "inline-closing.md",
        f"---\ntitle: Inline closing\nverified: 2026-10-04\n---\n## Service\n{comment}\nBody evidence.",
    )
    _check(
        kb, golden, _section(kb, "--json", "--file", "knowledge/inline-closing.md", "--number", "1")
    )


@pytest.mark.bats("section.bats", "section treats a leading-zero numeric TTL as decimal days")
def test_leading_zero_section_ttl(kb: KB, golden: Golden) -> None:
    kb.create_article(
        "decimal-ttl.md",
        "---\ntitle: Decimal TTL\nverified: 2026-10-04\n---\n## Service\n"
        "<!-- kb-section: ttl=08 -->\nBody evidence.",
    )
    result = _section(
        kb,
        "--file",
        "knowledge/decimal-ttl.md",
        "--number",
        "1",
        "--json",
        env={"FRESHNESS_TODAY_EPOCH": "1792022400"},
    )
    _check(kb, golden, result)


@pytest.mark.bats(
    "section.bats", "section metadata retains standalone closing delimiters with CRLF endings"
)
def test_crlf_metadata(kb: KB, golden: Golden) -> None:
    path = kb.layout.content / "knowledge" / "crlf-metadata.md"
    path.write_bytes(
        b"## Service\r\n<!-- kb-section: verified=2026-10-04; status=unresolved -->\r\nNeedle evidence.\r\n"
    )
    _check(
        kb,
        golden,
        _section(kb, "--json", "--file", "knowledge/crlf-metadata.md", "--number", "1"),
        "section",
    )
    _check(
        kb,
        golden,
        kb.run("search", "--json", "--path", "knowledge/crlf-metadata.md", "Needle"),
        "search",
    )


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--file"],
        ["--file", "knowledge/net.md"],
        ["--file", "knowledge/net.md", "--number", "1", "--json", "--text-only"],
        ["--bogus"],
    ],
    ids=["none", "file-no-value", "no-selector", "json-and-text-only", "unknown"],
)
def test_section_argument_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_article("net.md", ARTICLE)
    _check(kb, golden, _section(kb, *args))

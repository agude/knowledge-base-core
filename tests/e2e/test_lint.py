"""End-to-end tests for `kb lint`."""

from .harness import Kb


def test_help_describes_paths_and_the_ttl_switch(kb: Kb) -> None:
    result = kb("lint", "--help")

    assert result.returncode == 0
    assert result.stdout == (
        "Usage: kb lint [PATH...] [--require-ttl]\n\n"
        "Check article structure and metadata. PATH is under knowledge/ "
        "(default: all of knowledge/).\n"
    )
    assert result.stderr == ""


def test_clean_article_has_the_exact_summary(kb: Kb) -> None:
    article = kb.content / "knowledge" / "clean.md"
    article.write_text(
        "---\ntitle: Clean\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n# Clean\n",
        encoding="utf-8",
    )

    result = kb("lint", "knowledge/clean.md")

    assert result.returncode == 0
    assert result.stdout == "Lint: 0 errors, 0 warnings in 1 file(s)\n"
    assert result.stderr == ""


def test_rule_fixtures_report_only_their_expected_findings(kb: Kb) -> None:
    result = kb("lint", "knowledge/rules")

    assert result.returncode == 1
    assert result.stdout == (
        "knowledge/rules/heading-errors.md:9: error: second H1 (one article, one H1)\n"
        "knowledge/rules/heading-errors.md:10: error: unclosed code fence\n"
        "knowledge/rules/heading-warnings.md:9: warning: H2 is 51 lines (max 50): Repeated heading\n"
        "knowledge/rules/heading-warnings.md:60: warning: duplicate H2 text: Repeated heading\n"
        "knowledge/rules/invalid-date.md:4: error: verified is not a YYYY-MM-DD date\n"
        "knowledge/rules/metadata-unclosed.md:11: error: section metadata comment is unclosed\n"
        "knowledge/rules/metadata-values.md:11: error: effective date 2026-10-02 is after verified date 2026-10-01\n"
        "knowledge/rules/metadata-values.md:14: error: conflicting values for field 'verified'\n"
        "knowledge/rules/metadata-values.md:14: error: invalid section status\n"
        "knowledge/rules/metadata-values.md:14: error: invalid section ttl\n"
        "knowledge/rules/metadata-values.md:14: error: invalid section verified date\n"
        "knowledge/rules/metadata-values.md:17: error: invalid supersedes locator: abc\n"
        "knowledge/rules/metadata-values.md:20: error: supersedes section does not exist: 9\n"
        "knowledge/rules/metadata-values.md:23: error: section cannot supersede itself: 5\n"
        "knowledge/rules/metadata-values.md:26: error: supersedes relationship contains a cycle\n"
        "knowledge/rules/metadata-values.md:32: error: superseded section must not declare supersedes\n"
        "knowledge/rules/no-date.md:1: error: front matter missing verified\n"
        "knowledge/rules/no-front-matter.md:1: error: front matter missing title\n"
        "knowledge/rules/no-front-matter.md:1: error: front matter missing updated\n"
        "knowledge/rules/no-front-matter.md:1: error: front matter missing verified\n"
        "knowledge/rules/no-h1.md:1: error: no H1\n"
        "knowledge/rules/section-metadata.md:11: error: section metadata appears before the first section\n"
        "knowledge/rules/section-metadata.md:44: error: section metadata appears after section content\n"
        "knowledge/rules/section-metadata.md:50: error: section metadata has trailing text\n"
        "knowledge/rules/section-metadata.md:60: error: malformed field 'nonsense'\n"
        "knowledge/rules/section-metadata.md:60: error: unknown field 'colour'\n"
        "knowledge/rules/ttl-oversized.md:5: error: ttl is not a named TTL or positive integer within the limit\n"
        "knowledge/rules/ttl-unknown.md:5: error: ttl is not a named TTL or positive integer within the limit\n"
        "knowledge/rules/unclosed-front-matter.md:1: error: front matter missing title\n"
        "knowledge/rules/unclosed-front-matter.md:1: error: front matter missing updated\n"
        "knowledge/rules/unclosed-front-matter.md:1: error: front matter missing verified\n"
        "Lint: 29 errors, 2 warnings in 24 file(s)\n"
    )
    assert result.stderr == ""


def test_no_path_checks_all_markdown_files_under_knowledge(kb: Kb) -> None:
    expected_files = len(list((kb.content / "knowledge").rglob("*.md")))

    result = kb("lint")

    assert result.returncode == 1
    assert result.stdout.endswith(f"in {expected_files} file(s)\n")
    assert "sources/vendor-guide.md" not in result.stdout


def test_warning_only_output_exits_successfully(kb: Kb) -> None:
    result = kb("lint", "knowledge/rules/heading-warnings.md")

    assert result.returncode == 0
    assert result.stdout == (
        "knowledge/rules/heading-warnings.md:9: warning: "
        "H2 is 51 lines (max 50): Repeated heading\n"
        "knowledge/rules/heading-warnings.md:60: warning: "
        "duplicate H2 text: Repeated heading\n"
        "Lint: 0 errors, 2 warnings in 1 file(s)\n"
    )
    assert result.stderr == ""


def test_reports_structural_findings_in_path_and_line_order(kb: Kb) -> None:
    long_section = "## Repeated\n" + "body\n" * 50
    content = (
        "---\n"
        "title: Example\n"
        "updated: invalid\n"
        "verified: 2026-10-20\n"
        "ttl: 1000001\n"
        "---\n"
        "# Title\n"
        "# Second title\n" + long_section + "## Repeated\n"
    )
    (kb.content / "knowledge" / "sample.md").write_text(content, encoding="utf-8")

    result = kb("lint", "knowledge/sample.md")

    assert result.returncode == 1
    assert result.stdout == (
        "knowledge/sample.md:3: error: updated is not a YYYY-MM-DD date\n"
        "knowledge/sample.md:5: error: ttl is not a named TTL or positive integer within the limit\n"
        "knowledge/sample.md:8: error: second H1 (one article, one H1)\n"
        "knowledge/sample.md:9: warning: H2 is 51 lines (max 50): Repeated\n"
        "knowledge/sample.md:60: warning: duplicate H2 text: Repeated\n"
        "Lint: 3 errors, 2 warnings in 1 file(s)\n"
    )
    assert result.stderr == ""


def test_require_ttl_reports_missing_ttl(kb: Kb) -> None:
    article = kb.content / "knowledge" / "missing-ttl.md"
    article.write_text(
        "---\ntitle: Missing TTL\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n# Missing TTL\n",
        encoding="utf-8",
    )

    result = kb("lint", "knowledge/missing-ttl.md", "--require-ttl")

    assert result.returncode == 1
    assert result.stdout == (
        "knowledge/missing-ttl.md:1: error: front matter missing ttl\n"
        "Lint: 1 error, 0 warnings in 1 file(s)\n"
    )


def test_path_outside_knowledge_is_a_usage_error(kb: Kb) -> None:
    result = kb("lint", "sources/vendor-guide.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Usage: kb lint [PATH...] [--require-ttl]\n"


def test_runtime_path_error_uses_the_lint_prefix(kb: Kb) -> None:
    result = kb("lint", "knowledge/missing.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "lint: no such path: knowledge/missing.md\n"


def test_missing_and_escaping_references_report_their_source_lines(kb: Kb) -> None:
    article = kb.content / "knowledge" / "references.md"
    article.write_text(
        "---\n"
        "title: Reference failures\n"
        "updated: 2026-10-20\n"
        "verified: 2026-10-20\n"
        "ttl: domain\n"
        "sources:\n"
        "  - missing-source.md#nope\n"
        "  - ../../outside-source.md\n"
        "  - knowledge/infra/nas.md#missing-source-fragment\n"
        "---\n"
        "\n"
        "# Reference failures\n"
        "[missing](missing-link.md)\n"
        "[escape](../../outside.md)\n"
        "[missing heading](infra/nas.md#missing)\n"
        "[fenced heading](rules/sections-structure.md#not-a-heading-inside-a-fence)\n"
        "\n"
        "## Section sources\n"
        "<!-- kb-section: sources=missing-section-source.md#nope -->\n",
        encoding="utf-8",
    )

    result = kb("lint", "knowledge/references.md")

    assert result.returncode == 1
    assert result.stdout == (
        "knowledge/references.md:7: error: missing local source reference: missing-source.md#nope\n"
        "knowledge/references.md:8: error: local source reference escapes content root: "
        "../../outside-source.md\n"
        "knowledge/references.md:9: error: missing source reference anchor "
        "'#missing-source-fragment': knowledge/infra/nas.md#missing-source-fragment\n"
        "knowledge/references.md:13: error: missing local Markdown link target: missing-link.md\n"
        "knowledge/references.md:14: error: local Markdown link escapes content root: ../../outside.md\n"
        "knowledge/references.md:15: error: missing local Markdown link anchor '#missing': infra/nas.md#missing\n"
        "knowledge/references.md:16: error: missing local Markdown link anchor "
        "'#not-a-heading-inside-a-fence': "
        "rules/sections-structure.md#not-a-heading-inside-a-fence\n"
        "knowledge/references.md:19: error: missing local source reference: "
        "missing-section-source.md#nope\n"
        "Lint: 8 errors, 0 warnings in 1 file(s)\n"
    )
    assert result.stderr == ""


def test_existing_source_and_link_fragments_resolve(kb: Kb) -> None:
    target = kb.content / "knowledge" / "target.md"
    target.write_text(
        "---\n"
        "title: Reference target\n"
        "updated: 2026-10-20\n"
        "verified: 2026-10-20\n"
        "ttl: domain\n"
        "---\n"
        "# Target\n"
        "Top text.\n"
        "## Exact Heading\n"
        "Section text.\n"
        "## GitHub Heading\n"
        "Heading text.\n"
        "### Child Heading\n"
        "Child text.\n",
        encoding="utf-8",
    )
    source = kb.content / "knowledge" / "reference-source.md"
    source.write_text(
        "---\n"
        "title: Reference source\n"
        "updated: 2026-10-20\n"
        "verified: 2026-10-20\n"
        "ttl: domain\n"
        "sources:\n"
        "  - knowledge/target.md#1\n"
        "  - knowledge/target.md#title\n"
        "  - knowledge/target.md#top\n"
        "  - knowledge/target.md#Exact Heading\n"
        "  - knowledge/target.md#github-heading\n"
        "  - knowledge/target.md#Child Heading\n"
        "  - sources/vendor-guide.md#Firmware update\n"
        "  - observations/archived/20260412T101500-a1b2c3d4.md\n"
        "---\n"
        "# Reference source\n"
        "[numbered](target.md#2.1)\n"
        "[exact](<../sources/vendor-guide.md#Firmware update>)\n"
        "`[inline code](missing-inline.md)`\n"
        "```markdown\n"
        "[fenced code](missing-fenced.md)\n"
        "```\n"
        "\n"
        "## Section sources\n"
        "<!-- kb-section: sources=knowledge/target.md#Child Heading -->\n",
        encoding="utf-8",
    )

    result = kb("lint", "knowledge/reference-source.md")

    assert result.returncode == 0
    assert result.stdout == "Lint: 0 errors, 0 warnings in 1 file(s)\n"
    assert result.stderr == ""


def test_external_mailto_and_absolute_references_are_skipped(kb: Kb) -> None:
    article = kb.content / "knowledge" / "external-references.md"
    article.write_text(
        "---\n"
        "title: External references\n"
        "updated: 2026-10-20\n"
        "verified: 2026-10-20\n"
        "ttl: domain\n"
        "sources:\n"
        "  - https://example.invalid/guide\n"
        "  - mailto:help@example.invalid\n"
        "  - /absolute/source.md\n"
        "---\n"
        "# External references\n"
        "[url](https://example.invalid/guide)\n"
        "[mail](mailto:help@example.invalid)\n"
        "[absolute](/absolute/guide.md)\n"
        "[protocol relative](//example.invalid/guide)\n",
        encoding="utf-8",
    )

    result = kb("lint", "knowledge/external-references.md")

    assert result.returncode == 0
    assert result.stdout == "Lint: 0 errors, 0 warnings in 1 file(s)\n"
    assert result.stderr == ""

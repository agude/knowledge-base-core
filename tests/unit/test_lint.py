"""Unit tests for article structure and metadata checks."""

from pathlib import Path

from kb import lint, model


def inspect(text: str, require_ttl: bool = False) -> list[tuple[int, str, str]]:
    """Return line, severity, and message for a synthetic article."""
    document = model.parse("knowledge/test.md", text)
    return [
        (finding.line, finding.severity, finding.message)
        for finding in lint.check_document(document, require_ttl)
    ]


def valid_article(body: str) -> str:
    """An article with valid required front matter."""
    return (
        f"---\ntitle: Example\nupdated: 2026-10-20\nverified: 2026-10-20\nttl: domain\n---\n{body}"
    )


def test_missing_and_duplicate_h1_findings() -> None:
    assert inspect(valid_article("## Section\n")) == [(1, "error", "no H1")]
    assert inspect(valid_article("# First\n# Second\n")) == [
        (8, "error", "second H1 (one article, one H1)")
    ]


def test_h1_inside_a_fence_does_not_count() -> None:
    text = valid_article("```markdown\n# Example\n```\n")

    assert inspect(text) == [(1, "error", "no H1")]


def test_unclosed_fence_is_reported_at_its_opening_line() -> None:
    text = valid_article("# Example\n## Section\n~~~python\n")

    assert inspect(text) == [(9, "error", "unclosed code fence")]


def test_front_matter_dates_and_ttl_are_checked() -> None:
    text = (
        "---\n"
        "title: Example\n"
        "updated: 2026-02-30\n"
        "verified: 2026-10-20\n"
        "ttl: 1000001\n"
        "---\n"
        "# Example\n"
    )

    assert inspect(text) == [
        (3, "error", "updated is not a YYYY-MM-DD date"),
        (5, "error", "ttl is not a named TTL or positive integer within the limit"),
    ]


def test_require_ttl_and_positive_ttl_values() -> None:
    missing_ttl = "---\ntitle: Example\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n# Example\n"
    assert inspect(missing_ttl, require_ttl=True) == [(1, "error", "front matter missing ttl")]

    for ttl in ("people", "status", "process", "domain", "1", "1000000"):
        article = valid_article("# Example\n").replace("ttl: domain", f"ttl: {ttl}")
        assert inspect(article) == []

    for ttl in ("unknown", "0", "1000001", "1.5"):
        article = valid_article("# Example\n").replace("ttl: domain", f"ttl: {ttl}")
        assert [finding[2] for finding in inspect(article)] == [
            "ttl is not a named TTL or positive integer within the limit"
        ]

    huge_ttl = valid_article("# Example\n").replace("ttl: domain", f"ttl: {'9' * 5000}")
    assert [finding[2] for finding in inspect(huge_ttl)] == [
        "ttl is not a named TTL or positive integer within the limit"
    ]


def test_long_and_duplicate_h2_sections_are_warnings() -> None:
    long_section = "## Same\n" + "body\n" * 50
    text = valid_article("# Example\n" + long_section + "## Same\n")

    assert inspect(text) == [
        (8, "warning", "H2 is 51 lines (max 50): Same"),
        (59, "warning", "duplicate H2 text: Same"),
    ]


def test_section_metadata_values_and_inherited_effective_dates() -> None:
    text = valid_article(
        "# Example\n"
        "## Parent\n"
        "<!-- kb-section: verified=2026-10-01; ttl=domain -->\n"
        "### Child\n"
        "<!-- kb-section: effective=2026-10-02 -->\n"
        "## Invalid values\n"
        "<!-- kb-section: verified=bad; ttl=0; status=archived -->\n"
    )

    assert inspect(text) == [
        (11, "error", "effective date 2026-10-02 is after verified date 2026-10-01"),
        (13, "error", "invalid section status"),
        (13, "error", "invalid section ttl"),
        (13, "error", "invalid section verified date"),
    ]


def test_section_metadata_requires_key_value_syntax() -> None:
    text = valid_article("# Example\n## Section\n<!-- kb-section: ttl: people -->\n")

    assert [finding[2] for finding in inspect(text)] == ["malformed field 'ttl: people'"]


def test_invalid_inherited_date_does_not_create_an_ordering_finding() -> None:
    text = (
        "---\n"
        "title: Example\n"
        "updated: 2026-10-20\n"
        "verified: invalid\n"
        "ttl: domain\n"
        "---\n"
        "# Example\n"
        "## Section\n"
        "<!-- kb-section: effective=2026-10-01 -->\n"
    )

    messages = [finding[2] for finding in inspect(text)]
    assert messages == ["verified is not a YYYY-MM-DD date"]


def test_child_effective_date_ignores_an_invalid_inherited_verification_date() -> None:
    text = valid_article(
        "# Example\n"
        "## Parent\n"
        "<!-- kb-section: verified=invalid -->\n"
        "### Child\n"
        "<!-- kb-section: effective=2026-10-01 -->\n"
    )

    assert [finding[2] for finding in inspect(text)] == ["invalid section verified date"]


def test_supersedes_requires_existing_other_sections_and_acyclic_edges() -> None:
    text = valid_article(
        "# Example\n"
        "## One\n<!-- kb-section: supersedes=abc -->\n"
        "## Two\n<!-- kb-section: status=superseded; supersedes=3 -->\n"
        "## Three\n<!-- kb-section: supersedes=2 -->\n"
        "## Four\n<!-- kb-section: supersedes=4 -->\n"
    )

    messages = [finding[2] for finding in inspect(text)]
    assert messages == [
        "invalid supersedes locator: abc",
        "superseded section must not declare supersedes",
        "supersedes relationship contains a cycle",
        "section cannot supersede itself: 4",
    ]


def test_missing_supersedes_target_is_reported() -> None:
    text = valid_article("# Example\n## One\n<!-- kb-section: supersedes=9 -->\n")

    assert [finding[2] for finding in inspect(text)] == ["supersedes section does not exist: 9"]


def test_fragments_accept_kb_locators_exact_headings_and_ascii_slugs() -> None:
    document = model.parse(
        "knowledge/target.md",
        valid_article(
            "# Example\n## Exact Heading!\n### Child Heading\n#### Deep Heading\n"
            "```markdown\n## Hidden Heading\n```\n"
        ),
    )

    assert lint.fragment_resolves(document, "title")
    assert lint.fragment_resolves(document, "top")
    assert lint.fragment_resolves(document, "1")
    assert lint.fragment_resolves(document, "01")
    assert not lint.fragment_resolves(document, "Example")
    assert not lint.fragment_resolves(document, "example")
    assert lint.fragment_resolves(document, "Exact Heading!")
    assert lint.fragment_resolves(document, "exact-heading")
    assert lint.fragment_resolves(document, "Child Heading")
    assert lint.fragment_resolves(document, "child-heading")
    assert not lint.fragment_resolves(document, "Deep Heading")
    assert not lint.fragment_resolves(document, "Hidden Heading")
    assert not lint.fragment_resolves(document, "missing")
    assert not lint.fragment_resolves(document, "9" * 5000)
    assert lint.fragment_resolves(document, "EXACT-HEADING")
    assert lint.fragment_resolves(document, "Child-Heading")
    for fragment in ("exact-heading!!!", "Exact Heading?", "EXACT HEADING", "exact-headingİ"):
        assert not lint.fragment_resolves(document, fragment)


def test_links_with_parentheses_and_reference_labels_keep_their_destinations() -> None:
    document = model.parse(
        "knowledge/source.md",
        valid_article(
            "# Source\n"
            '[inline](guide(v2).md "Guide")\n'
            "[full][Guide label]\n[collapsed][]\n[shortcut]\n"
            "\n[guide LABEL]: guide(v2).md\n"
            "[collapsed]: <guide(v2).md#Exact Heading!>\n"
            "[shortcut]: missing.md\n"
        ),
    )

    assert [(reference.line, reference.destination) for reference in lint.references(document)] == [
        (8, "guide(v2).md"),
        (9, "guide(v2).md"),
        (10, "guide(v2).md#Exact Heading!"),
        (11, "missing.md"),
    ]


def test_reference_findings_check_reference_links_and_exact_anchors(tmp_path: Path) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    (knowledge / "guide(v2).md").write_text(
        valid_article("# Guide\n## Exact Heading!\n"), encoding="utf-8"
    )
    document = model.parse(
        "knowledge/source.md",
        valid_article(
            "# Source\n[valid](guide(v2).md#exact-heading)\n"
            "[broken][missing]\n[wrong](guide(v2).md#Exact-Heading!)\n"
            "[missing]: missing.md\n"
        ),
    )

    findings = lint.reference_findings(tmp_path, document, {})

    assert [(finding.line, finding.message) for finding in findings] == [
        (9, "missing local Markdown link target: missing.md"),
        (
            10,
            "missing local Markdown link anchor '#Exact-Heading!': guide(v2).md#Exact-Heading!",
        ),
    ]


def test_references_keep_frontmatter_items_and_skip_code() -> None:
    document = model.parse(
        "knowledge/source.md",
        "---\n"
        "title: Source\n"
        "sources:\n"
        "  - first.md\n"
        "  - second.md#section\n"
        "---\n"
        "# Source\n"
        "[body](third.md)\n"
        "`[inline](inline.md)`\n"
        "```markdown\n"
        "[fenced](fenced.md)\n"
        "```\n"
        "## Section\n"
        "<!-- kb-section: sources=fourth.md, fifth.md#part; "
        "label=[not a link](missing-meta-link.md) -->\n",
    )

    assert [
        (reference.kind, reference.destination, reference.line)
        for reference in lint.references(document)
    ] == [
        ("source", "first.md", 4),
        ("source", "second.md#section", 5),
        ("link", "third.md", 8),
        ("source", "fourth.md", 14),
        ("source", "fifth.md#part", 14),
    ]


def test_superseded_section_must_not_declare_even_an_invalid_supersedes_target() -> None:
    text = valid_article(
        "# Example\n## One\n<!-- kb-section: status=superseded; supersedes=abc -->\n"
    )

    assert [finding[2] for finding in inspect(text)] == [
        "invalid supersedes locator: abc",
        "superseded section must not declare supersedes",
    ]

"""End-to-end tests for explicit article verification."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .harness import HOLD_KERNEL_LOCK, Kb


def _article(kb: Kb, name: str) -> Path:
    return kb.content / "knowledge" / name


def _add_updated(article: Path) -> None:
    """Make the fixture article satisfy the required updated field without changing other bytes."""
    contents = article.read_bytes()
    if b"updated:" not in contents:
        article.write_bytes(
            contents.replace(b'title: "NAS"\n', b'title: "NAS"\nupdated: 2026-10-20\n')
        )


def test_help_and_required_article_argument(git_kb: Kb) -> None:
    help_result = git_kb("verify", "--help")
    assert help_result.returncode == 0
    assert help_result.stdout.startswith("Usage: kb verify ARTICLE [--ttl TTL]\n\n")
    assert help_result.stderr == ""

    missing = git_kb("verify")
    assert missing.returncode == 1
    assert missing.stdout == ""
    assert missing.stderr == "Usage: kb verify ARTICLE [--ttl TTL]\n"


def test_replaces_verified_and_adds_ttl_after_it(git_kb: Kb) -> None:
    article = _article(git_kb, "rules/ttl-missing.md")
    original = article.read_bytes()
    expected = original.replace(
        b"verified: 2026-08-20\n---",
        b"verified: 2026-10-26\nttl: domain\n---",
    )

    result = git_kb("verify", "knowledge/rules/ttl-missing.md", "--ttl", "domain")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Verified: knowledge/rules/ttl-missing.md (ttl domain)\n"
    assert result.stderr == ""
    assert article.read_bytes() == expected


@pytest.mark.parametrize(
    "link",
    [
        "[broken](target(v2).md#Exact-Heading!)",
        "[broken][answer]\n\n[answer]: missing.md",
    ],
)
def test_invalid_anchors_and_reference_links_prevent_verification(git_kb: Kb, link: str) -> None:
    target = _article(git_kb, "target(v2).md")
    target.write_text("# Target\n## Exact Heading!\n", encoding="utf-8")
    article = _article(git_kb, "source.md")
    original = (
        "---\ntitle: Source\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        f"ttl: domain\n---\n# Source\n{link}\n"
    ).encode()
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/source.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "proposed result has lint errors" in result.stderr
    assert article.read_bytes() == original


def test_valid_links_with_parentheses_and_reference_labels_allow_verification(git_kb: Kb) -> None:
    target = _article(git_kb, "target(v2).md")
    target.write_text("# Target\n## Exact Heading!\n", encoding="utf-8")
    article = _article(git_kb, "source.md")
    article.write_text(
        "---\ntitle: Source\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\n---\n# Source\n[inline](target(v2).md#exact-heading)\n"
        "[upper](target(v2).md#EXACT-HEADING)\n"
        "[reference][answer]\n\n[answer]: target(v2).md#1\n",
        encoding="utf-8",
    )

    result = git_kb("verify", "knowledge/source.md")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Verified: knowledge/source.md (ttl domain)\n"


@pytest.mark.parametrize("ttl", ["people", "14"])
def test_replaces_an_existing_ttl_with_a_named_or_numeric_value(git_kb: Kb, ttl: str) -> None:
    article = _article(git_kb, "infra/nas.md")
    _add_updated(article)
    original = article.read_bytes()
    expected = original.replace(b"verified: 2026-08-16", b"verified: 2026-10-26").replace(
        b"ttl: domain", f"ttl: {ttl}".encode()
    )

    result = git_kb("verify", "infra/nas.md", "--ttl", ttl)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Verified: knowledge/infra/nas.md (ttl {ttl})\n"
    assert article.read_bytes() == expected


def test_repairs_invalid_ttl_and_verified_values(git_kb: Kb) -> None:
    article = _article(git_kb, "rules/invalid-date.md")
    original = article.read_bytes()
    expected = original.replace(b"verified: 2026-13-40", b"verified: 2026-10-26").replace(
        b"ttl: domain", b"ttl: 30"
    )

    result = git_kb("verify", "knowledge/rules/invalid-date.md", "--ttl", "30")

    assert result.returncode == 0, result.stderr
    assert article.read_bytes() == expected
    assert result.stdout == "Verified: knowledge/rules/invalid-date.md (ttl 30)\n"


def test_valid_ttl_override_repairs_an_invalid_stored_ttl(git_kb: Kb) -> None:
    article = _article(git_kb, "invalid-ttl.md")
    original = (
        b"---\ntitle: Invalid TTL\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        b"ttl: weekly\n---\n# Invalid TTL\n"
    )
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/invalid-ttl.md", "--ttl", "people")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Verified: knowledge/invalid-ttl.md (ttl people)\n"
    assert article.read_bytes() == original.replace(
        b"verified: 2026-10-20", b"verified: 2026-10-26"
    ).replace(b"ttl: weekly", b"ttl: people")


def test_adds_missing_verified_then_ttl_in_order(git_kb: Kb) -> None:
    article = _article(git_kb, "rules/no-date.md")
    original = article.read_bytes()
    expected = original.replace(
        b"ttl: domain\n---",
        b"ttl: process\nverified: 2026-10-26\n---",
    )

    result = git_kb("verify", "knowledge/rules/no-date.md", "--ttl", "process")

    assert result.returncode == 0, result.stderr
    assert article.read_bytes() == expected


def test_requires_a_valid_ttl_when_none_is_supplied(git_kb: Kb) -> None:
    article = _article(git_kb, "rules/ttl-missing.md")
    before = article.read_bytes()

    result = git_kb("verify", "knowledge/rules/ttl-missing.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("verify:")
    assert "--ttl" in result.stderr
    assert article.read_bytes() == before


@pytest.mark.parametrize("ttl", ["weekly", "0", "1000001", "1.5"])
def test_refuses_invalid_ttl_values_without_writing(git_kb: Kb, ttl: str) -> None:
    article = _article(git_kb, "infra/nas.md")
    before = article.read_bytes()

    result = git_kb("verify", "knowledge/infra/nas.md", "--ttl", ttl)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("verify:")
    assert "TTL" in result.stderr
    assert article.read_bytes() == before


def test_refuses_an_invalid_stored_ttl_without_override(git_kb: Kb) -> None:
    article = _article(git_kb, "rules/ttl-unknown.md")
    before = article.read_bytes()

    result = git_kb("verify", "knowledge/rules/ttl-unknown.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "--ttl" in result.stderr
    assert article.read_bytes() == before


def test_rejects_fragments_non_knowledge_paths_and_ambiguous_names(git_kb: Kb) -> None:
    cases = [
        ("knowledge/infra/nas.md#1", "fragment"),
        ("sources/vendor-guide.md", "knowledge"),
    ]
    for article, cause in cases:
        result = git_kb("verify", article, "--ttl", "domain")
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr.startswith("verify:")
        assert cause in result.stderr

    for directory in ("a", "b"):
        path = _article(git_kb, f"{directory}/shared.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntitle: Shared\nupdated: 2026-10-20\nverified: 2026-10-20\n"
            "ttl: domain\n---\n# Shared\n",
            encoding="utf-8",
        )
    result = git_kb("verify", "shared.md")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "matches 2 files" in result.stderr


def test_refuses_an_unrelated_lint_error_without_partial_repair(git_kb: Kb) -> None:
    article = _article(git_kb, "unrelated-error.md")
    original = (
        b"---\ntitle: Broken\nupdated: 2026-10-20\nverified: invalid\n---\n# Broken\n# Duplicate\n"
    )
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/unrelated-error.md", "--ttl", "domain")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("verify:")
    assert "second H1" in result.stderr
    assert article.read_bytes() == original


def test_refuses_a_missing_local_reference_without_writing(git_kb: Kb) -> None:
    article = _article(git_kb, "missing-reference.md")
    original = (
        b"---\ntitle: Broken reference\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        b"ttl: domain\n---\n# Broken reference\n\n[missing](missing.md)\n"
    )
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/missing-reference.md")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "missing local Markdown link target: missing.md" in result.stderr
    assert article.read_bytes() == original


@pytest.mark.parametrize(
    ("body", "cause"),
    [
        ("# Missing front matter\n", "front matter is missing"),
        ("---\ntitle: Open\n", "front matter is unclosed"),
        (
            "---\ntitle: Duplicated\nupdated: 2026-10-20\nverified: 2026-10-20\n"
            "verified: 2026-10-21\nttl: domain\n---\n# Duplicated\n",
            "duplicated",
        ),
        (
            "---\ntitle: Duplicated TTL\nupdated: 2026-10-20\nverified: 2026-10-20\n"
            "ttl: domain\nttl: people\n---\n# Duplicated TTL\n",
            "duplicated",
        ),
        (
            "---\ntitle: Block list\nupdated: 2026-10-20\nverified: 2026-10-20\n"
            "ttl:\n  - domain\n---\n# Block list\n",
            "block list",
        ),
    ],
)
def test_refuses_unsafe_front_matter_without_writing(git_kb: Kb, body: str, cause: str) -> None:
    article = _article(git_kb, "unsafe.md")
    original = body.encode()
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/unsafe.md", "--ttl", "people")

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith("verify:")
    assert cause in result.stderr
    assert article.read_bytes() == original


def test_refuses_unresolved_conflicts_and_section_verified_metadata(git_kb: Kb) -> None:
    conflict = _article(git_kb, "conflict.md")
    conflict.write_text(
        "---\ntitle: Conflict\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\nconflict: unresolved\n---\n# Conflict\n",
        encoding="utf-8",
    )
    before_conflict = conflict.read_bytes()
    result = git_kb("verify", "knowledge/conflict.md")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "unresolved" in result.stderr
    assert conflict.read_bytes() == before_conflict

    section = _article(git_kb, "section-verified.md")
    section.write_text(
        "---\ntitle: Section\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        "ttl: domain\n---\n# Section\n## Locally verified\n"
        "<!-- kb-section: verified=2026-10-01 -->\n\nText.\n",
        encoding="utf-8",
    )
    before_section = section.read_bytes()
    result = git_kb("verify", "knowledge/section-verified.md")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "knowledge/section-verified.md#1" in result.stderr
    assert section.read_bytes() == before_section


def test_crlf_edit_preserves_all_other_bytes(git_kb: Kb) -> None:
    article = _article(git_kb, "crlf-verify.md")
    original = (
        b'---\r\ntitle: "CRLF article"\r\nupdated: 2026-10-20\r\n'
        b"verified: 2026-10-20\r\nttl: domain\r\n---\r\n"
        b"\r\n# CRLF article\r\n"
    )
    article.write_bytes(original)
    expected = original.replace(b"verified: 2026-10-20", b"verified: 2026-10-26")

    result = git_kb("verify", "knowledge/crlf-verify.md")

    assert result.returncode == 0, result.stderr
    assert article.read_bytes() == expected


def test_utf8_bom_is_preserved_when_verifying(git_kb: Kb) -> None:
    article = _article(git_kb, "bom.md")
    original = (
        b"\xef\xbb\xbf---\n"
        b"title: BOM article\nupdated: 2026-10-20\nverified: 2026-10-20\n"
        b"ttl: domain\n---\n# BOM article\n"
    )
    article.write_bytes(original)

    result = git_kb("verify", "knowledge/bom.md")

    assert result.returncode == 0, result.stderr
    assert article.read_bytes() == original.replace(
        b"verified: 2026-10-20", b"verified: 2026-10-26"
    )


def test_same_day_repeat_keeps_bytes_and_mtime(git_kb: Kb) -> None:
    article = _article(git_kb, "infra/nas.md")
    _add_updated(article)
    result = git_kb("verify", "knowledge/infra/nas.md")
    assert result.returncode == 0, result.stderr
    os.utime(article, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before = article.read_bytes(), article.stat().st_mtime_ns

    repeat = git_kb("verify", "knowledge/infra/nas.md")

    assert repeat.returncode == 0, repeat.stderr
    assert repeat.stdout == result.stdout
    assert (article.read_bytes(), article.stat().st_mtime_ns) == before


def test_read_and_recall_show_freshness_without_automatically_reverifying(git_kb: Kb) -> None:
    article = _article(git_kb, "infra/nas.md")
    _add_updated(article)
    result = git_kb("verify", "knowledge/infra/nas.md")
    assert result.returncode == 0, result.stderr

    read = git_kb("read", "knowledge/infra/nas.md")
    assert "knowledge/infra/nas.md | NAS | fresh, verified 2026-10-26 |" in read.stdout
    recalled = git_kb("recall", "power loss")
    assert "knowledge/infra/nas.md#2 | Power loss | fresh, verified 2026-10-26" in recalled.stdout

    article.write_bytes(article.read_bytes() + b"\nA later edit.\n")
    after_edit = git_kb("read", "knowledge/infra/nas.md")
    assert "fresh, verified 2026-10-26" in after_edit.stdout


def test_lock_wait_setting_must_be_valid(git_kb: Kb) -> None:
    result = git_kb("verify", "knowledge/infra/nas.md", env={"KB_LOCK_WAIT": "soon"})

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Usage: kb verify ARTICLE [--ttl TTL]\n"


def test_kernel_lock_blocks_before_publication(git_kb: Kb) -> None:
    article = git_kb.content / "knowledge" / "infra" / "nas.md"
    before = article.read_bytes()
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_KERNEL_LOCK, str(git_kb.content / ".git" / "kb.lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert holder.stdin is not None
    assert holder.stdout is not None
    try:
        assert holder.stdout.readline() == "locked\n"
        result = git_kb("verify", "knowledge/infra/nas.md")
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "verify: content repository is busy (waited 1s for the lock)\n"
    assert article.read_bytes() == before
    assert not (git_kb.content / ".git" / "kb-tmp").exists()

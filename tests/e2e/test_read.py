"""End-to-end tests for `kb read`."""

import pytest

from .harness import Kb

pytestmark = pytest.mark.xfail(strict=True, reason="kb read is not implemented yet")

POWER_LOSS = (
    "knowledge/infra/nas.md#2 | Power loss | fresh, verified 2026-08-16 | 1 source\n"
    "## Power loss\n"
    "\n"
    "After a power loss, check the disks before starting Plex.\n"
)
TRANSCODING = (
    "knowledge/infra/plex.md#2 | Transcoding | fresh, verified 2026-10-01 | 1 source\n"
    "## Transcoding\n"
    "\n"
    "Transcoding uses a cache under /var/cache/plex.\n"
)
PLEX_FILE = (
    "knowledge/infra/plex.md | Plex | fresh, verified 2026-10-01 | 1 source\n"
    "knowledge/infra/plex.md#title | Plex\n"
    "knowledge/infra/plex.md#1 | Library paths\n"
    "knowledge/infra/plex.md#2 | Transcoding\n"
    "\n"
    "# Plex\n"
    "\n"
    "Plex serves the media library from the NAS.\n"
)
SECTIONS_FILE = (
    "knowledge/rules/sections-structure.md | Section Structure | fresh, verified 2026-10-20 "
    "| 0 sources\n"
    "knowledge/rules/sections-structure.md#title | Section Structure\n"
    "knowledge/rules/sections-structure.md#1 | First section\n"
    "  knowledge/rules/sections-structure.md#1.1 | First sub\n"
    "  knowledge/rules/sections-structure.md#1.2 | Second sub\n"
    "knowledge/rules/sections-structure.md#2 | Second section\n"
    "knowledge/rules/sections-structure.md#3 | Third section\n"
    "\n"
    "# Section Structure\n"
    "\n"
    "### Early H3 before any H2\n"
    "\n"
    "This H3 belongs to the top prose, so it has no number.\n"
)
SECTION_STATUS = [
    ("#1", "Valid override", "stale, verified 2026-08-01 (ttl 60), conflict", "2 sources"),
    (
        "#1.1",
        "Inherits the parent's verified date",
        "stale, verified 2026-08-01 (ttl 14), conflict",
        "2 sources",
    ),
    ("#2", "Blank lines before the comment", "fresh, verified 2026-07-01, conflict", "0 sources"),
    ("#3", "Multi-line comment", "stale, verified 2026-05-05 (ttl 14), conflict", "0 sources"),
    ("#4", "Comment after body text", "fresh, verified 2026-09-01, conflict", "0 sources"),
    ("#5", "Comment with trailing text", "fresh, verified 2026-09-01, conflict", "0 sources"),
    ("#6", "Comment inside a fence", "fresh, verified 2026-09-01, conflict", "0 sources"),
    (
        "#7",
        "Unknown keys and bad pairs",
        "stale, verified 2026-04-04 (ttl 60), conflict",
        "0 sources",
    ),
]
TTL_FORMS = [
    ("ttl-people.md", "TTL people", "stale, verified 2026-10-01 (ttl 14)"),
    ("ttl-status.md", "TTL status", "fresh, verified 2026-10-20"),
    ("ttl-process.md", "TTL process", "stale, verified 2026-08-01 (ttl 60)"),
    ("ttl-domain.md", "TTL domain", "fresh, verified 2026-08-01"),
    ("ttl-number.md", "TTL number", "stale, verified 2026-09-01 (ttl 30)"),
    ("ttl-quoted-number.md", "TTL quoted number", "fresh, verified 2026-09-01"),
    ("ttl-unknown.md", "TTL unknown name", "fresh, verified 2026-09-01"),
    ("ttl-oversized.md", "TTL oversized", "invalid"),
    ("ttl-missing.md", "TTL missing", "stale, verified 2026-08-20 (ttl 60)"),
    ("invalid-date.md", "Invalid date", "invalid"),
    ("no-date.md", "No date", "unknown"),
]


def test_section_prints_header_and_body(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nas.md#2")
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == POWER_LOSS


def test_stale_section_uses_its_own_verified_date_and_ttl(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/plex.md#1")
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == (
        "knowledge/infra/plex.md#1 | Library paths | stale, verified 2026-05-01 (ttl 60) | 1 source"
    )


def test_file_prints_outline_then_top_prose(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/plex.md")
    assert result.returncode == 0
    assert result.stdout == PLEX_FILE


def test_unique_file_name_resolves_and_prints_the_canonical_path(kb: Kb) -> None:
    result = kb("read", "plex.md")
    assert result.stdout == PLEX_FILE


def test_knowledge_relative_path_resolves(kb: Kb) -> None:
    result = kb("read", "infra/plex.md#2")
    assert result.stdout == TRANSCODING


def test_several_locators_are_separated_by_a_blank_line(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nas.md#2", "knowledge/infra/plex.md#2")
    assert result.stdout == POWER_LOSS + "\n" + TRANSCODING


def test_title_locator_prints_the_title(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nas.md#title")
    assert result.stdout == (
        "knowledge/infra/nas.md#title | NAS | fresh, verified 2026-08-16 | 1 source\nNAS\n"
    )


def test_top_locator_prints_prose_before_the_first_h2(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nas.md#top")
    assert result.stdout == (
        "knowledge/infra/nas.md#top | NAS | fresh, verified 2026-08-16 | 1 source\n"
        "# NAS\n"
        "\n"
        "The NAS runs Traefik, Syncthing, and Plex. Its disks are in one pool.\n"
    )


def test_h2_section_includes_its_h3_sections(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/sections-structure.md#1")
    lines = result.stdout.splitlines()
    assert lines[0] == (
        "knowledge/rules/sections-structure.md#1 | First section | fresh, verified 2026-10-20 "
        "| 0 sources"
    )
    assert "### First sub" in lines
    assert "### Second sub" in lines


def test_h3_section_runs_to_the_next_h3_and_keeps_fences_and_h4(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/sections-structure.md#1.1")
    lines = result.stdout.splitlines()
    assert "```markdown" in lines
    assert "#### Deep heading" in lines
    assert "### Second sub" not in lines


def test_h3_section_prints_its_header_and_body(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/sections-structure.md#1.2")
    assert result.stdout == (
        "knowledge/rules/sections-structure.md#1.2 | Second sub | fresh, verified 2026-10-20 "
        "| 0 sources\n"
        "### Second sub\n"
        "\n"
        "Second sub text.\n"
    )


def test_closing_hashes_are_dropped_from_the_heading(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/sections-structure.md#2")
    lines = result.stdout.splitlines()
    assert lines[0] == (
        "knowledge/rules/sections-structure.md#2 | Second section | fresh, verified 2026-10-20 "
        "| 0 sources"
    )
    assert "## ##" in lines


def test_outline_lists_h3_under_its_h2_and_keeps_early_h3_in_top(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/sections-structure.md")
    assert result.stdout == SECTIONS_FILE


@pytest.mark.parametrize(("locator", "heading", "status", "sources"), SECTION_STATUS)
def test_section_metadata_overrides_and_invalid_positions(
    kb: Kb, locator: str, heading: str, status: str, sources: str
) -> None:
    result = kb("read", f"knowledge/rules/section-metadata.md{locator}")
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == (
        f"knowledge/rules/section-metadata.md{locator} | {heading} | {status} | {sources}"
    )


@pytest.mark.parametrize(("name", "title", "status"), TTL_FORMS)
def test_freshness_for_each_ttl_form(kb: Kb, name: str, title: str, status: str) -> None:
    result = kb("read", f"knowledge/rules/{name}")
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == (
        f"knowledge/rules/{name} | {title} | {status} | 0 sources"
    )


def test_quoted_title_unescapes_quotes_and_backslashes(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/frontmatter-quoted.md#title")
    assert result.stdout.splitlines()[-1] == 'Quoted "title" with a \\ backslash'


def test_first_duplicate_key_wins_and_single_quotes_unwrap(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/frontmatter-block-lists.md#title")
    assert result.stdout.splitlines()[-1] == "Single 'quoted' title"


def test_missing_front_matter_uses_the_h1_as_the_title(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/no-front-matter.md")
    assert result.stdout == (
        "knowledge/rules/no-front-matter.md | Heading Title Only | unknown | 0 sources\n"
        "knowledge/rules/no-front-matter.md#1 | Section after a rule\n"
        "\n"
        "# Heading Title Only\n"
        "\n"
        "Without front matter, the H1 stands in for the title.\n"
        "\n"
        "---\n"
        "\n"
        "title: this line is body text, not front matter\n"
    )


def test_unclosed_front_matter_is_body_text(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/unclosed-front-matter.md")
    lines = result.stdout.splitlines()
    assert lines[0] == (
        "knowledge/rules/unclosed-front-matter.md | Unclosed Front Matter | unknown | 0 sources"
    )
    assert "title: Unclosed front matter" in lines


def test_crlf_article_prints_lf_lines(kb: Kb) -> None:
    result = kb("read", "knowledge/rules/crlf-line-endings.md#1")
    assert "\r" not in result.stdout
    assert result.stdout == (
        "knowledge/rules/crlf-line-endings.md#1 | CRLF section | fresh, verified 2026-10-20 "
        "| 0 sources\n"
        "## CRLF section\n"
        "\n"
        "Text in a CRLF section.\n"
    )


def test_sources_flag_prints_the_section_sources(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/plex.md#1", "--sources")
    assert result.returncode == 0
    assert result.stdout == "observations/archived/20260903T120000-c3d4e5f6.md\n"


def test_sources_flag_falls_back_to_the_article_sources(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/plex.md#2", "--sources")
    assert result.returncode == 0
    assert result.stdout == "observations/archived/20260903T120000-c3d4e5f6.md\n"


def test_sources_flag_prints_nothing_without_sources(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/syncthing.md#1", "--sources")
    assert result.returncode == 0
    assert result.stdout == ""


def test_observation_prints_title_without_status(kb: Kb) -> None:
    result = kb("read", "observations/archived/20260412T101500-a1b2c3d4.md")
    assert result.stdout == (
        "observations/archived/20260412T101500-a1b2c3d4.md | Traefik first on restart\n"
        "observations/archived/20260412T101500-a1b2c3d4.md#title | Traefik first on restart\n"
        "\n"
        "Traefik must come up before Syncthing when the NAS restarts.\n"
    )


def test_sources_document_reports_its_sync_date(kb: Kb) -> None:
    result = kb("read", "sources/vendor-guide.md")
    assert result.stdout.splitlines()[0] == (
        "sources/vendor-guide.md | Vendor guide: NAS firmware | source, synced 2026-09-01 "
        "| 0 sources"
    )


def test_missing_locator_is_a_usage_error(kb: Kb) -> None:
    result = kb("read")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "Usage: kb read LOCATOR... [--sources]\n"


def test_unknown_option_is_a_usage_error(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/plex.md", "--bogus")
    assert result.returncode == 1
    assert result.stderr == "Unknown option: --bogus\n"


def test_missing_file_is_reported(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nope.md")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == 'kb read: no file matches "knowledge/infra/nope.md"\n'


def test_ambiguous_file_name_lists_the_candidates(kb: Kb) -> None:
    result = kb("read", "backups.md")
    assert result.returncode == 1
    assert result.stderr == (
        'kb read: "backups.md" matches 2 files:\n'
        "  knowledge/infra/backups.md\n"
        "  knowledge/rules/backups.md\n"
    )


def test_missing_section_lists_the_file_locators(kb: Kb) -> None:
    result = kb("read", "knowledge/infra/nas.md#9")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == (
        "kb read: knowledge/infra/nas.md has no section 9. Its locators:\n"
        "  knowledge/infra/nas.md#title | NAS\n"
        "  knowledge/infra/nas.md#1 | Restart order\n"
        "  knowledge/infra/nas.md#2 | Power loss\n"
    )


def test_locators_before_a_failure_are_printed_and_later_ones_are_not(kb: Kb) -> None:
    result = kb(
        "read",
        "knowledge/infra/nas.md#2",
        "knowledge/infra/nas.md#9",
        "knowledge/infra/plex.md#2",
    )
    assert result.returncode == 1
    assert result.stdout == POWER_LOSS
    assert "has no section 9" in result.stderr


def test_symlink_outside_the_content_root_is_refused(kb: Kb) -> None:
    outside = kb.content.parent / "outside.md"
    outside.write_text("# Outside\n\nNot part of the repository.\n", encoding="utf-8")
    (kb.content / "knowledge" / "leak.md").symlink_to(outside)
    result = kb("read", "knowledge/leak.md")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "kb read: knowledge/leak.md resolves outside the content repository\n"


def test_relative_path_outside_the_content_root_is_refused(kb: Kb) -> None:
    (kb.content.parent / "outside.md").write_text("# Outside\n", encoding="utf-8")
    result = kb("read", "../outside.md")
    assert result.returncode == 1
    assert result.stderr == "kb read: ../outside.md resolves outside the content repository\n"

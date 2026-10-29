"""End-to-end tests for `kb map`."""

import pytest

from .harness import Kb


def file_lines(stdout: str) -> list[str]:
    """The lines that name a file: those not indented under another line."""
    return [line for line in stdout.splitlines() if not line.startswith(" ")]


def test_default_maps_knowledge_at_depth_two(kb: Kb) -> None:
    result = kb("map")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    files = file_lines(result.stdout)
    assert files == sorted(files)
    assert all(line.startswith("knowledge/") for line in files)
    assert "knowledge/infra/nas.md | NAS" in lines
    assert "  knowledge/infra/nas.md#1 | Restart order" in lines
    assert "  knowledge/infra/nas.md#2 | Power loss" in lines


def test_depth_one_counts_articles_per_directory(kb: Kb) -> None:
    result = kb("map", "--depth", "1")
    rules = len(list((kb.content / "knowledge" / "rules").glob("*.md")))
    assert result.returncode == 0
    assert result.stdout == f"knowledge/infra | 6 articles\nknowledge/rules | {rules} articles\n"


def test_depth_three_adds_h3_sections_indented_under_their_h2(kb: Kb) -> None:
    result = kb("map", "--depth", "3", "knowledge/rules/section-metadata.md")
    assert result.returncode == 0
    assert result.stdout == (
        "knowledge/rules/section-metadata.md | Section Metadata\n"
        "  knowledge/rules/section-metadata.md#1 | Valid override\n"
        "    knowledge/rules/section-metadata.md#1.1 | Inherits the parent's verified date\n"
        "  knowledge/rules/section-metadata.md#2 | Blank lines before the comment\n"
        "  knowledge/rules/section-metadata.md#3 | Multi-line comment\n"
        "  knowledge/rules/section-metadata.md#4 | Comment after body text\n"
        "  knowledge/rules/section-metadata.md#5 | Comment with trailing text\n"
        "  knowledge/rules/section-metadata.md#6 | Comment inside a fence\n"
        "  knowledge/rules/section-metadata.md#7 | Unknown keys and bad pairs\n"
    )


@pytest.mark.parametrize("argument", ["knowledge/infra", "infra"])
def test_directory_path_restricts_the_listing(kb: Kb, argument: str) -> None:
    result = kb("map", argument)
    assert result.returncode == 0
    assert file_lines(result.stdout) == [
        "knowledge/infra/backups.md | Backups",
        "knowledge/infra/nas.md | NAS",
        "knowledge/infra/plex.md | Plex",
        "knowledge/infra/shelf-counts.md | Shelf counts",
        "knowledge/infra/shelves.md | Shelves",
        "knowledge/infra/syncthing.md | Syncthing",
    ]


def test_file_path_restricts_the_listing_to_one_file(kb: Kb) -> None:
    result = kb("map", "knowledge/infra/plex.md")
    assert result.stdout == (
        "knowledge/infra/plex.md | Plex\n"
        "  knowledge/infra/plex.md#1 | Library paths\n"
        "  knowledge/infra/plex.md#2 | Transcoding\n"
    )


def test_sources_directory_is_mapped_when_named(kb: Kb) -> None:
    result = kb("map", "--depth", "1", "sources")
    assert result.returncode == 0
    assert result.stdout == "sources | 1 article\n"


def test_missing_path_is_reported(kb: Kb) -> None:
    result = kb("map", "nope")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "kb map: no such path: nope\n"


def test_depth_must_be_one_two_or_three(kb: Kb) -> None:
    result = kb("map", "--depth", "4")
    assert result.returncode == 1
    assert result.stderr == "Option --depth must be 1, 2, or 3\n"


def test_depth_requires_a_value(kb: Kb) -> None:
    result = kb("map", "--depth")
    assert result.returncode == 1
    assert result.stderr == "Option --depth requires an argument\n"


def test_two_paths_is_a_usage_error(kb: Kb) -> None:
    result = kb("map", "infra", "rules")
    assert result.returncode == 1
    assert result.stderr == "Usage: kb map [PATH] [--depth 1|2|3]\n"


def test_help_names_the_command(kb: Kb) -> None:
    result = kb("map", "--help")
    assert result.returncode == 0
    assert result.stdout.startswith("Usage: kb map")

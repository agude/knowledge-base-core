"""Tests for kb map: the listing at each depth, and the command's output and errors."""

import shutil
from pathlib import Path

import pytest

from kb import corpus
from kb.commands import map as map_command
from kb.errors import KbError
from kb.model import parse

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"


@pytest.fixture
def content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    monkeypatch.setenv("KB_CONTENT", str(root))
    monkeypatch.setenv("KB_TODAY", "2026-10-26")
    return root


def test_area_lines_count_articles_per_directory_with_plurals() -> None:
    paths = ["knowledge/infra/a.md", "knowledge/infra/b.md", "sources/x.md"]
    assert map_command.area_lines(paths) == [
        "knowledge/infra | 2 articles",
        "sources | 1 article",
    ]


def test_article_lines_follow_the_depth() -> None:
    document = parse(
        "knowledge/d.md",
        "---\ntitle: D\n---\n# H\n\n## Two\n\n### Three\n\n## Four\n",
    )
    assert map_command.article_lines([document], 2) == [
        "knowledge/d.md | D",
        "  knowledge/d.md#1 | Two",
        "  knowledge/d.md#2 | Four",
    ]
    assert map_command.article_lines([document], 3) == [
        "knowledge/d.md | D",
        "  knowledge/d.md#1 | Two",
        "    knowledge/d.md#1.1 | Three",
        "  knowledge/d.md#2 | Four",
    ]


def test_default_maps_knowledge(content: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert map_command.run([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("knowledge/infra/backups.md | Backups\n")
    assert "  knowledge/infra/nas.md#1 | Restart order\n" in out
    assert "sources/" not in out


def test_depth_one_and_a_directory_path(content: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert map_command.run(["--depth", "1", "infra"]) == 0
    assert capsys.readouterr().out == "knowledge/infra | 4 articles\n"


def test_a_file_path_lists_one_article(content: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert map_command.run(["knowledge/infra/plex.md", "--depth=3"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "knowledge/infra/plex.md | Plex"


def test_an_empty_directory_prints_nothing(
    content: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (content / "empty").mkdir()
    assert map_command.run(["empty"]) == 0
    assert capsys.readouterr().out == ""


def test_a_missing_default_directory_is_reported(content: Path) -> None:
    shutil.rmtree(content / "knowledge")
    with pytest.raises(KbError, match=r"^kb map: no such path: knowledge$"):
        map_command.run([])


def test_a_missing_path_is_reported(content: Path) -> None:
    with pytest.raises(KbError, match=r"^kb map: no such path: nope$"):
        map_command.run(["nope"])


def test_too_many_paths_print_usage(content: Path) -> None:
    with pytest.raises(KbError, match=r"^Usage: kb map \[PATH\]"):
        map_command.run(["infra", "rules"])


@pytest.mark.parametrize("depth", ["0", "4", "x"])
def test_depth_must_be_one_two_or_three(content: Path, depth: str) -> None:
    with pytest.raises(KbError, match=r"^Option --depth must be 1, 2, or 3$"):
        map_command.run(["--depth", depth])


def test_help_prints_the_usage(capsys: pytest.CaptureFixture[str]) -> None:
    assert map_command.run(["-h"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb map [PATH] [--depth 1|2|3]\n")


def test_a_path_that_resolves_outside_the_repository_is_refused(
    content: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (content / "linked").symlink_to(outside)
    with pytest.raises(KbError, match=r"resolves outside the content repository"):
        map_command.run(["linked"])


def test_corpus_listing_is_used_for_depth_one(content: Path) -> None:
    assert corpus.markdown_files(content, "knowledge/infra")[0] == "knowledge/infra/backups.md"

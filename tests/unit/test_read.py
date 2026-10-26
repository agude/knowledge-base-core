"""Tests for kb read: rendering each kind of locator, and the command's output and errors."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from kb.commands import read
from kb.context import Context
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = date(2026, 10, 26)


@pytest.fixture
def context(tmp_path: Path) -> Context:
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    return Context(root=root.resolve(), today=TODAY)


def test_a_section_renders_its_header_and_lines(context: Context) -> None:
    assert read.render(context, "knowledge/infra/nas.md#1", False) == (
        "knowledge/infra/nas.md#1 | Restart order | fresh, verified 2026-08-16 | 1 source\n"
        "## Restart order\n"
        "\n"
        "Traefik first, then Syncthing, then Plex.\n"
    )


def test_a_file_renders_outline_then_top(context: Context) -> None:
    text = read.render(context, "knowledge/infra/nas.md", False)
    assert text.splitlines()[0] == (
        "knowledge/infra/nas.md | NAS | fresh, verified 2026-08-16 | 1 source"
    )
    assert "knowledge/infra/nas.md#2 | Power loss" in text.splitlines()
    assert text.endswith(
        "# NAS\n\nThe NAS runs Traefik, Syncthing, and Plex. Its disks are in one pool.\n"
    )


def test_a_file_without_outline_or_top_prints_only_its_header(context: Context) -> None:
    (context.root / "knowledge" / "empty.md").write_text("", encoding="utf-8")
    assert read.render(context, "knowledge/empty.md", False) == (
        "knowledge/empty.md | empty | unknown | 0 sources\n"
    )


def test_a_file_outside_knowledge_has_no_status_or_sources(context: Context) -> None:
    text = read.render(context, "observations/archived/20260412T101500-a1b2c3d4.md", False)
    assert text.splitlines()[0] == (
        "observations/archived/20260412T101500-a1b2c3d4.md | Traefik first on restart"
    )


def test_a_file_without_outline_but_with_top_has_no_leading_blank_line(context: Context) -> None:
    (context.root / "knowledge" / "bare.md").write_text("Only prose.\n", encoding="utf-8")
    assert read.render(context, "knowledge/bare.md", False) == (
        "knowledge/bare.md | bare | unknown | 0 sources\nOnly prose.\n"
    )


def test_title_and_top_fragments_render_their_text(context: Context) -> None:
    assert read.render(context, "knowledge/infra/nas.md#title", False).splitlines()[-1] == "NAS"
    top = read.render(context, "knowledge/infra/nas.md#top", False)
    assert (
        top.splitlines()[0]
        == "knowledge/infra/nas.md#top | NAS | fresh, verified 2026-08-16 | 1 source"
    )


def test_a_file_without_a_title_uses_its_h1_as_the_heading(context: Context) -> None:
    text = read.render(context, "knowledge/rules/no-front-matter.md#top", False)
    assert text.splitlines()[0].startswith(
        "knowledge/rules/no-front-matter.md#top | Heading Title Only"
    )


def test_a_top_fragment_without_any_heading_uses_the_file_name(context: Context) -> None:
    (context.root / "knowledge" / "plain.md").write_text("Words only.\n", encoding="utf-8")
    assert read.render(context, "knowledge/plain.md#top", False).splitlines()[0] == (
        "knowledge/plain.md#top | plain | unknown | 0 sources"
    )


def test_sources_only_prints_the_section_sources_and_the_article_sources(context: Context) -> None:
    assert read.render(context, "knowledge/infra/plex.md#1", True) == (
        "observations/archived/20260903T120000-c3d4e5f6.md\n"
    )
    assert read.render(context, "knowledge/infra/plex.md", True) == (
        "observations/archived/20260903T120000-c3d4e5f6.md\n"
    )
    assert read.render(context, "knowledge/infra/syncthing.md#1", True) == ""


def test_sources_only_for_a_title_fragment_uses_the_article_sources(context: Context) -> None:
    assert read.render(context, "knowledge/infra/plex.md#title", True) == (
        "observations/archived/20260903T120000-c3d4e5f6.md\n"
    )


def test_a_missing_section_lists_the_outline(context: Context) -> None:
    with pytest.raises(KbError) as error:
        read.render(context, "knowledge/infra/nas.md#9", False)
    assert str(error.value).splitlines()[0] == (
        "kb read: knowledge/infra/nas.md has no section 9. Its locators:"
    )


def test_a_missing_title_is_a_missing_section(context: Context) -> None:
    with pytest.raises(KbError, match=r"has no section title"):
        read.render(context, "knowledge/rules/no-front-matter.md#title", False)


def test_a_directory_is_not_a_file(context: Context) -> None:
    with pytest.raises(KbError, match=r"^kb read: knowledge/infra is a directory$"):
        read.render(context, "knowledge/infra", False)


def test_a_missing_file_is_reported(context: Context) -> None:
    with pytest.raises(KbError, match=r'^kb read: no file matches "knowledge/nope\.md"$'):
        read.render(context, "knowledge/nope.md", False)


def test_run_without_locators_prints_usage(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(KbError, match=r"^Usage: kb read LOCATOR"):
        read.run([])


def test_run_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert read.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb read LOCATOR... [--sources]\n")


def test_run_separates_locators_with_a_blank_line(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    monkeypatch.setenv("KB_TODAY", TODAY.isoformat())
    assert read.run(["knowledge/infra/nas.md#2", "knowledge/infra/plex.md#2"]) == 0
    out = capsys.readouterr().out
    assert "\n\nknowledge/infra/plex.md#2 | Transcoding" in out


def test_run_prints_earlier_output_before_a_failing_locator(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    monkeypatch.setenv("KB_TODAY", TODAY.isoformat())
    with pytest.raises(KbError):
        read.run(["knowledge/infra/nas.md#2", "knowledge/infra/nas.md#9"])
    out = capsys.readouterr().out
    assert out.startswith("knowledge/infra/nas.md#2 | Power loss")
    assert out.endswith("After a power loss, check the disks before starting Plex.\n")


def test_run_sources_mode_prints_no_separators(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    assert read.run(["knowledge/infra/plex.md#1", "knowledge/infra/plex.md#2", "--sources"]) == 0
    out = capsys.readouterr().out
    assert out == "observations/archived/20260903T120000-c3d4e5f6.md\n" * 2

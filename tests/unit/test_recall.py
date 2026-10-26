"""Tests for kb recall over curated knowledge: the answer text, scope, and command output."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from kb.commands import recall
from kb.context import Context
from kb.errors import KbError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = date(2026, 10, 26)


@pytest.fixture
def context(tmp_path: Path) -> Context:
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    return Context(root=root.resolve(), today=TODAY)


def test_no_match_is_one_line(context: Context) -> None:
    assert recall.answer(context, ["quantum", "zebra"], 3, None) == (
        'No curated knowledge matches "quantum zebra".\n'
    )


def test_results_are_printed_in_full_up_to_the_limit(context: Context) -> None:
    text = recall.answer(context, ["nas", "restart", "order"], 1, None)
    assert text.startswith("knowledge/infra/nas.md#1 | Restart order | fresh, verified 2026-08-16")
    assert "knowledge/infra/syncthing.md#2" not in text.split("Also relevant:")[0]
    assert text.endswith(
        "Also relevant:\n  knowledge/infra/syncthing.md#2 | Restart order\n"
        "Read with: kb read <locator>\n"
    )


def test_a_top_result_prints_the_top_lines_with_its_article_status(context: Context) -> None:
    text = recall.answer(context, ["nas", "runs", "traefik"], 3, None)
    assert text.splitlines()[0] == (
        "knowledge/infra/nas.md#top | NAS | fresh, verified 2026-08-16 | 1 source"
    )
    assert "# NAS" in text.splitlines()


def test_scope_limits_results_to_a_file_or_directory(context: Context) -> None:
    text = recall.answer(context, ["nas", "restart", "order"], 3, "knowledge/infra/syncthing.md")
    assert "nas.md" not in text
    assert text.startswith("knowledge/infra/syncthing.md#2")
    directory = recall.answer(context, ["nas", "restart", "order"], 3, "knowledge/infra")
    assert "knowledge/infra/syncthing.md#2" in directory


def test_sources_documents_are_curated_results(context: Context) -> None:
    text = recall.answer(context, ["firmware", "update"], 3, None)
    assert text.splitlines()[0] == (
        "sources/vendor-guide.md#1 | Firmware update | source, synced 2026-09-01 | 0 sources"
    )


def test_the_run_writes_the_answer(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    monkeypatch.setenv("KB_TODAY", TODAY.isoformat())
    assert recall.run(["quantum", "zebra"]) == 0
    assert capsys.readouterr().out == 'No curated knowledge matches "quantum zebra".\n'


def test_run_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert recall.run(["--help"]) == 0
    assert capsys.readouterr().out.startswith("Usage: kb recall QUERY... [--limit N] [--in PATH]")


def test_run_without_a_query_prints_usage() -> None:
    with pytest.raises(KbError, match=r"^Usage: kb recall QUERY"):
        recall.run(["--limit", "2"])


@pytest.mark.parametrize("value", ["0", "many"])
def test_run_validates_the_limit(value: str) -> None:
    with pytest.raises(KbError, match=r"^Option --limit must be a positive integer$"):
        recall.run(["--limit", value, "nas"])


def test_run_reports_a_scope_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, context: Context
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    with pytest.raises(KbError, match=r"^kb recall: no such path: knowledge/nope$"):
        recall.run(["--in", "knowledge/nope", "nas"])


def test_scope_is_resolved_from_the_content_root(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    monkeypatch.setenv("KB_TODAY", TODAY.isoformat())
    assert recall.run(["--in", "infra", "nas", "restart", "order"]) == 0
    assert capsys.readouterr().out.startswith("knowledge/infra/nas.md#1 | Restart order")

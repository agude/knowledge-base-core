"""Tests for kb recall over curated knowledge: the answer text, scope, and command output."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from kb.commands import recall
from kb.context import Context
from kb.errors import KbError
from kb.model import parse

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
        "Uncurated (pending, not yet verified):\n"
        "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 "
        "| NAS restart after the update\n"
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


def test_no_curated_match_lists_the_evidence_under_a_label(context: Context) -> None:
    text = recall.answer(context, ["outage", "start", "services", "order"], 3, None)
    lines = text.splitlines()
    assert lines[0] == 'No curated knowledge matches "outage start services order".'
    assert lines[1] == "Evidence:"
    assert lines[-1] == "Read with: kb read <locator>"


def test_evidence_lines_pad_each_column_to_its_widest_entry() -> None:
    items = [
        recall.Item("a.md", "2026-01-01", "observation", "One"),
        recall.Item("longer/name.md", "2026-01-02", "transcript", "Two"),
    ]
    assert recall._evidence_lines(items) == [
        "  " + "a.md".ljust(14) + " | 2026-01-01 | observation | One",
        "  " + "longer/name.md" + " | 2026-01-02 | " + "transcript".ljust(11) + " | Two",
    ]


def test_uncurated_pending_items_follow_curated_results(context: Context) -> None:
    text = recall.answer(context, ["nas", "restart", "order"], 3, None)
    assert text.endswith(
        "Uncurated (pending, not yet verified):\n"
        "  observations/pending/20261024T094659-8d6fecbe.md | 2026-10-24 "
        "| NAS restart after the update\n"
        "Read with: kb read <locator>\n"
    )


def test_each_kind_of_evidence_is_labelled(context: Context) -> None:
    text = recall.answer(context, ["backup", "disk", "owner"], 3, None)
    assert "questions/open/20261001T090000-bbbb2222.md | 2026-10-01 | open question" in text
    resolved = recall.answer(context, ["transcoding", "caches", "answer"], 3, None)
    assert "resolved question" in resolved


def test_evidence_is_limited_to_the_scope(context: Context) -> None:
    inside = recall.answer(context, ["label", "printer", "driver"], 3, "observations/archived")
    assert "observation | Old label printer note" in inside
    outside = recall.answer(context, ["label", "printer", "driver"], 3, "knowledge")
    assert outside == 'No curated knowledge matches "label printer driver".\n'


def test_ranked_evidence_is_newest_first_among_equal_scores() -> None:
    older = parse(
        "observations/pending/a.md",
        "---\ntitle: alpha beta\ncreated: 2026-01-01T00:00:00Z\n---\nText.\n",
    )
    newer = parse(
        "observations/pending/b.md",
        "---\ntitle: alpha beta\ncreated: 2026-02-01T00:00:00Z\n---\nText.\n",
    )
    items = recall._ranked(
        [("observations/pending/a.md", older), ("observations/pending/b.md", newer)],
        ["alpha", "beta"],
    )
    assert [item.path for item in items] == [
        "observations/pending/b.md",
        "observations/pending/a.md",
    ]


def test_kind_and_date_follow_the_file_and_its_front_matter() -> None:
    transcript = parse(
        "observations/archived/t.md",
        "---\nsource: session-transcript\ncreated: 2026-03-04T05:06:07Z\n---\n",
    )
    assert recall._kind("observations/archived/t.md", transcript) == "transcript"
    assert recall._date(transcript) == "2026-03-04"
    untagged = parse("observations/archived/u.md", "---\ncreated: not a date\n---\n")
    assert recall._kind("observations/archived/u.md", untagged) == "observation"
    assert recall._date(untagged) == ""
    question = parse("questions/resolved/q.md", "")
    assert recall._kind("questions/resolved/q.md", question) == "resolved question"


def test_transcript_text_is_an_excerpt_and_other_text_is_the_title() -> None:
    transcript = parse(
        "observations/archived/t.md", "---\ntitle: Session\n---\nThe outage ended.\n"
    )
    assert recall._text("transcript", transcript, ["outage"]) == "The outage ended."
    note = parse("observations/archived/n.md", "---\ntitle: " + "T" * 100 + "\n---\n")
    assert recall._text("observation", note, []) == "T" * 69 + "..."

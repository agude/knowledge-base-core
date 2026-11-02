"""Tests for the session rows that recall returns: transcript rows, and the From sessions rows
that leave out anything the Uncurated block already shows."""

import shutil
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pytest

from kb import corpus, evidence, search, token_cache
from kb.commands import recall
from kb.context import Context
from kb.entries import Entry

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = date(2026, 10, 31)


@pytest.fixture
def context(tmp_path: Path) -> Context:
    root = tmp_path / "content"
    shutil.copytree(FIXTURE, root)
    return Context(root=root.resolve(), today=TODAY)


def write_transcript(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f'title: "{relative}"\n'
        "source: session-transcript\n"
        "created: 2026-10-20\n"
        "---\n\n"
        "## 1. user, 2026-10-20T10:00:00Z\n\n"
        "~~~~text\n"
        f"{text}\n"
        "~~~~\n",
        encoding="utf-8",
    )


def write_observation(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\ntitle: "{relative}"\ncreated: 2026-10-20\n---\n\n{text}\n', encoding="utf-8"
    )


def paths(rows: Sequence[evidence.Item]) -> list[str]:
    """The file of each row, without its message number."""
    return [row.path.partition("#")[0] for row in rows]


def test_session_rows_are_transcripts_only(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "zebra migration plan")
    write_observation(context.root, "observations/archived/o1.md", "zebra migration note")
    rows = recall.session_rows(context, ["zebra"], None, corpus.Documents(context.root), 5)
    assert paths(rows) == ["observations/archived/t1.md"]


def test_session_rows_come_from_pending_and_archived(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "quokka habitat")
    write_transcript(context.root, "observations/pending/t2.md", "quokka habitat")
    rows = recall.session_rows(context, ["quokka"], None, corpus.Documents(context.root), 5)
    assert sorted(paths(rows)) == ["observations/archived/t1.md", "observations/pending/t2.md"]


def test_session_rows_without_terms_is_empty(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "quokka habitat")
    assert recall.session_rows(context, ["--"], None, corpus.Documents(context.root), 5) == []


def test_the_sessions_selection_leaves_out_rows_that_uncurated_shows(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    write_transcript(context.root, "observations/pending/t2.md", "nas restart order confirmed")
    chosen = recall.select(context, CURATED_QUERY, None, 3)
    assert "observations/pending/t2.md" in paths(chosen.uncurated)
    assert "observations/pending/t2.md" not in paths(chosen.sessions)
    assert "observations/archived/t1.md" in paths(chosen.sessions)


def test_the_sessions_selection_keeps_the_limit_after_leaving_rows_out(context: Context) -> None:
    write_transcript(context.root, "observations/pending/p1.md", "nas restart order confirmed")
    for name in ("a1", "a2", "a3"):
        write_transcript(context.root, f"observations/archived/{name}.md", "nas restart order")
    chosen = recall.select(context, CURATED_QUERY, None, 3)
    assert len(chosen.sessions) == recall.SESSION_ROWS
    assert all(path.startswith("observations/archived/") for path in paths(chosen.sessions))


CURATED_QUERY = ["nas", "restart", "order"]
# The fixture's archived transcript matches CURATED_QUERY, so tests that expect no session row
# remove it first.
FIXTURE_TRANSCRIPT = "observations/archived/20260903T120000-c3d4e5f6.md"
EXCERPT_LIMIT = search.EXCERPT_WIDTH + len("...") * 2


def test_the_session_block_follows_uncurated_and_precedes_the_read_line(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    write_transcript(context.root, "observations/pending/p1.md", "nas restart order pending")
    text = recall.answer(context, CURATED_QUERY, 3, None)
    lines = text.splitlines()
    heading = lines.index(recall.SESSIONS_HEADING)
    assert text.index("Uncurated (pending") < text.index(recall.SESSIONS_HEADING)
    assert lines[-1] == recall.READ_WITH
    assert heading < len(lines) - 1


def test_each_session_row_has_its_locator_date_and_excerpt(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    text = recall.answer(context, CURATED_QUERY, 3, None)
    lines = text.splitlines()
    heading = lines.index(recall.SESSIONS_HEADING)
    assert "may be superseded" in recall.SESSIONS_HEADING
    row = lines[heading + 1]
    locator, date_text, excerpt = (part.strip() for part in row.split(" | "))
    assert locator.startswith("observations/archived/t1.md")
    assert date_text == "2026-10-20"
    assert excerpt == "nas restart order confirmed"


def test_the_session_block_shows_at_most_three_rows_with_short_excerpts(context: Context) -> None:
    for number in range(1, 6):
        write_transcript(
            context.root,
            f"observations/archived/t{number}.md",
            "nas restart order " + "padding words " * 20,
        )
    text = recall.answer(context, CURATED_QUERY, 3, None)
    lines = text.splitlines()
    heading = lines.index(recall.SESSIONS_HEADING)
    rows = lines[heading + 1 : lines.index(recall.READ_WITH)]
    assert len(rows) == recall.SESSION_ROWS
    for row in rows:
        assert len(row.split(" | ", 2)[2]) <= EXCERPT_LIMIT


def test_a_session_row_already_shown_as_uncurated_is_left_out(context: Context) -> None:
    write_transcript(context.root, "observations/pending/p1.md", "nas restart order pending")
    text = recall.answer(context, CURATED_QUERY, 3, None)
    lines = text.splitlines()
    assert any(line.startswith("  observations/pending/p1.md") for line in lines)
    session_rows = lines[lines.index(recall.SESSIONS_HEADING) + 1 : -1]
    assert not any("observations/pending/p1.md" in row for row in session_rows)


def test_no_session_block_when_no_session_row_qualifies(context: Context) -> None:
    (context.root / FIXTURE_TRANSCRIPT).unlink()
    text = recall.answer(context, CURATED_QUERY, 3, None)
    assert text.startswith("knowledge/infra/nas.md#1")
    assert recall.SESSIONS_HEADING not in text


def test_no_session_block_without_a_curated_match(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "zebra migration plan")
    text = recall.answer(context, ["zebra"], 3, None)
    assert text.startswith('No curated knowledge matches "zebra".')
    assert "Evidence:" in text
    assert "observations/archived/t1.md" in text
    assert recall.SESSIONS_HEADING not in text


def test_sessions_false_removes_the_block(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    shown = recall.answer(context, CURATED_QUERY, 3, None)
    hidden = recall.answer(context, CURATED_QUERY, 3, None, sessions=False)
    assert recall.SESSIONS_HEADING in shown
    assert recall.SESSIONS_HEADING not in hidden
    assert hidden == shown.split(recall.SESSIONS_HEADING)[0] + recall.READ_WITH + "\n"


def test_the_no_sessions_switch_removes_the_block_from_the_command(
    monkeypatch: pytest.MonkeyPatch, context: Context, capsys: pytest.CaptureFixture[str]
) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    monkeypatch.setenv("KB_CONTENT", str(context.root))
    monkeypatch.setenv("KB_TODAY", TODAY.isoformat())
    assert recall.run([*CURATED_QUERY, "--no-sessions"]) == 0
    assert recall.SESSIONS_HEADING not in capsys.readouterr().out
    assert recall.run(CURATED_QUERY) == 0
    assert recall.SESSIONS_HEADING in capsys.readouterr().out


def test_an_answer_selects_the_uncurated_rows_once(
    context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "restic backup retention")
    calls: list[Sequence[str]] = []
    original = recall._uncurated

    def counting(
        context: Context,
        words: Sequence[str],
        scope: str | None,
        documents: corpus.Documents,
        loaded: Mapping[str, Entry],
    ) -> list[evidence.Item]:
        calls.append(words)
        return original(context, words, scope, documents, loaded)

    monkeypatch.setattr(recall, "_uncurated", counting)
    recall.answer(context, ["backup"], 3, None)
    assert len(calls) == 1


def test_a_selection_loads_the_cache_once(
    context: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "nas restart order confirmed")
    write_transcript(context.root, "observations/pending/p1.md", "nas restart order pending")
    loads: list[Sequence[str]] = []
    original = token_cache.load

    def counting(
        root: object, paths: Sequence[str], documents: corpus.Documents | None = None
    ) -> Mapping[str, Entry]:
        loads.append(paths)
        return original(root, paths, documents)  # type: ignore[arg-type]

    monkeypatch.setattr(token_cache, "load", counting)
    chosen = recall.select(context, CURATED_QUERY, None, 3)
    assert len(loads) == 1
    assert chosen.sessions and chosen.uncurated


def test_without_a_curated_match_the_selection_is_evidence_only(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "zebra migration plan")
    chosen = recall.select(context, ["zebra"], None, 3)
    assert chosen.results == []
    assert chosen.follow == [] and chosen.uncurated == [] and chosen.sessions == []
    assert paths(chosen.evidence) == ["observations/archived/t1.md"]

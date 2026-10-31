"""Tests for the session rows that recall returns: transcript rows, and the From sessions rows
that leave out anything the Uncurated block already shows."""

import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from kb import corpus, evidence
from kb.commands import recall
from kb.context import Context

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


def test_from_sessions_leaves_out_rows_that_uncurated_shows(context: Context) -> None:
    write_transcript(context.root, "observations/archived/t1.md", "zebra migration plan")
    write_transcript(context.root, "observations/pending/t2.md", "zebra migration plan")
    rows = recall.from_sessions(context, ["zebra"], None, corpus.Documents(context.root), 5)
    assert paths(rows) == ["observations/archived/t1.md"]


def test_from_sessions_keeps_the_limit_after_leaving_rows_out(context: Context) -> None:
    write_transcript(context.root, "observations/pending/p1.md", "okapi forest")
    for name in ("a1", "a2", "a3"):
        write_transcript(context.root, f"observations/archived/{name}.md", "okapi forest")
    rows = recall.from_sessions(context, ["okapi"], None, corpus.Documents(context.root), 2)
    assert len(rows) == 2
    assert all(path.startswith("observations/archived/") for path in paths(rows))

"""Pure selection and message-addressability rules for evidence search."""

import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from kb import corpus, evidence, lock, model, search, token_cache
from kb.commands import evidence as evidence_command
from kb.context import Context
from kb.model import Document, parse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

TRANSCRIPT_FRONT = (
    "title: Transcript fixture\n"
    "source: session-transcript\n"
    'session: "session-1"\n'
    'first_message: "message-1"\n'
    'last_message: "message-2"\n'
    "part: 1\n"
    "started: 2026-10-20T00:00:00Z\n"
    "ended: 2026-10-20T01:00:00Z\n"
    "created: 2026-10-21T00:00:00Z\n"
)
MESSAGE_HEADINGS = (
    "1. user, 2026-10-20T00:10:00Z",
    "2. assistant, 2026-10-20T00:20:00Z",
)


def transcript(
    front: str = TRANSCRIPT_FRONT, headings: tuple[str, ...] = MESSAGE_HEADINGS
) -> Document:
    """A parsed synthetic transcript with the supplied metadata and H2 headings."""
    body = "\n\n".join(
        f"## {heading}\n\nmessage body {index}" for index, heading in enumerate(headings, 1)
    )
    return parse("observations/archived/transcript.md", f"---\n{front}---\n\n{body}\n")


def test_addressable_messages_normalize_timestamps_and_ignore_fenced_headings() -> None:
    document = parse(
        "observations/archived/transcript.md",
        "---\n" + TRANSCRIPT_FRONT + "---\n\n"
        "## 1. user, 2026-10-19T20:10:00-04:00\n\n"
        "~~~~text\n## 99. user, 2026-10-20T00:15:00Z\n~~~~\n\n"
        "## 2. assistant, 2026-10-20T00:20:00Z\n\n"
        "The message body has a matching phrase.\n",
    )
    messages = evidence.addressable_messages(document)
    assert messages is not None
    assert [message.number for message in messages] == [1, 2]
    assert messages[0].timestamp.isoformat() == "2026-10-20T00:10:00+00:00"
    assert "matching phrase" in messages[1].body[0]


@pytest.mark.parametrize(
    ("front", "headings"),
    [
        (TRANSCRIPT_FRONT.replace('session: "session-1"\n', ""), MESSAGE_HEADINGS),
        (TRANSCRIPT_FRONT.replace('first_message: "message-1"\n', ""), MESSAGE_HEADINGS),
        (TRANSCRIPT_FRONT.replace('last_message: "message-2"\n', ""), MESSAGE_HEADINGS),
        (TRANSCRIPT_FRONT.replace("part: 1\n", "part: 0\n"), MESSAGE_HEADINGS),
        (
            TRANSCRIPT_FRONT.replace(
                "started: 2026-10-20T00:00:00Z", "started: 2026-10-20T00:00:00"
            ),
            MESSAGE_HEADINGS,
        ),
        (
            TRANSCRIPT_FRONT.replace("ended: 2026-10-20T01:00:00Z", "ended: 2026-10-19T23:00:00Z"),
            MESSAGE_HEADINGS,
        ),
        (TRANSCRIPT_FRONT, (MESSAGE_HEADINGS[0], "3. assistant, 2026-10-20T00:20:00Z")),
        (TRANSCRIPT_FRONT, (MESSAGE_HEADINGS[0], "2. assistant, no timestamp")),
        (
            TRANSCRIPT_FRONT,
            (MESSAGE_HEADINGS[0], "2. assistant, 2026-10-20T02:00:00Z"),
        ),
        (TRANSCRIPT_FRONT, ("1. user, 2026-10-20T00:10:00", MESSAGE_HEADINGS[1])),
    ],
)
def test_incomplete_or_malformed_transcripts_use_file_level_handling(
    front: str, headings: tuple[str, ...]
) -> None:
    assert evidence.addressable_messages(transcript(front, headings)) is None


def cached(tmp_path: Path, files: dict[str, str]) -> tuple[Path, list[token_cache.Entry]]:
    """Write files under a fresh content root, and return its root and their cache entries."""
    root = tmp_path / "content"
    for relpath, text in files.items():
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    loaded = token_cache.load(root, sorted(files))
    return root, [loaded[relpath] for relpath in sorted(files)]


def test_transcript_source_is_overridden_by_question_storage_kind() -> None:
    document = parse(
        "questions/open/gap.md",
        "---\ntitle: Gap\nsource: session-transcript\n---\n\nQuestion body.\n",
    )
    assert evidence.evidence_kind(document.path, document.scalar("source")) == "open-question"


def test_file_ties_sort_by_path_after_date_and_score(tmp_path: Path) -> None:
    contents = "---\ntitle: Backup disk\ncreated: 2026-10-20\n---\n\nBackup disk inventory.\n"
    root, entries = cached(
        tmp_path,
        {"observations/archived/z.md": contents, "observations/archived/a.md": contents},
    )
    items = evidence.select(
        list(reversed(entries)),
        search.query_terms(("backup", "disk")),
        None,
        None,
        None,
        5,
        corpus.Documents(root).read,
    )
    assert [item.path for item in items] == [
        "observations/archived/a.md",
        "observations/archived/z.md",
    ]


def test_a_file_level_legacy_transcript_shows_the_chunk_with_the_most_terms(
    tmp_path: Path,
) -> None:
    filler = "padding " * 150
    contents = (
        "---\ntitle: Legacy\nsource: session-transcript\ncreated: 2026-10-21\n---\n\n"
        f"### user\n\nalpha here. {filler}\n\n"
        "### assistant\n\nalpha and beta together.\n"
    )
    root, entries = cached(tmp_path, {"observations/archived/l.md": contents})

    items = evidence.select(
        entries,
        search.query_terms(("alpha", "beta")),
        "transcript",
        None,
        None,
        5,
        corpus.Documents(root).read,
    )

    assert [item.path for item in items] == ["observations/archived/l.md"]
    assert items[0].date == date(2026, 10, 21)
    assert "beta" in items[0].text


def test_malformed_transcript_remains_a_file_level_result(tmp_path: Path) -> None:
    text = transcript(TRANSCRIPT_FRONT.replace("part: 1\n", "part: 0\n")).lines
    root, entries = cached(
        tmp_path, {"observations/archived/transcript.md": "\n".join(text) + "\n"}
    )
    items = evidence.select(
        entries,
        search.query_terms(("message", "body")),
        None,
        None,
        None,
        5,
        corpus.Documents(root).read,
    )
    assert len(items) == 1
    assert items[0].path == "observations/archived/transcript.md"
    assert items[0].message_number is None


def unexpected_external_call(*_args: object, **_kwargs: object) -> None:
    """Fail if the read-only evidence command calls Git, locks, or network services."""
    pytest.fail("read-only evidence command made an external call")


def test_command_parses_each_document_once_and_only_when_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cold run parses each stale file once. A warm run parses only the printed files."""
    root = tmp_path / "content"
    shutil.copytree(FIXTURES / "content", root)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    context = Context(root=root, today=date(2026, 10, 26))
    monkeypatch.setattr(evidence_command, "load", lambda *_args: context)
    expected_paths = sorted(
        path
        for directory in evidence_command.ALL_DIRECTORIES
        for path in corpus.markdown_files(root, directory)
    )
    parsed: list[str] = []
    original_parse = model.parse

    def counting_parse(path: str, text: str) -> Document:
        parsed.append(path)
        return original_parse(path, text)

    real_run = subprocess.run

    def git_for_the_cache_only(
        args: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        # The cache asks git where the worktree is. Every other process is refused.
        if list(args[:2]) != ["git", "rev-parse"]:
            pytest.fail("read-only evidence command ran another process")
        return real_run(list(args), **kwargs)

    monkeypatch.setattr(model, "parse", counting_parse)
    monkeypatch.setattr(subprocess, "run", git_for_the_cache_only)
    monkeypatch.setattr(socket, "socket", unexpected_external_call)
    monkeypatch.setattr(lock, "write_lock", unexpected_external_call)
    before = {path: (root / path).read_bytes() for path in expected_paths}

    def run_and_print() -> list[str]:
        output = StringIO()
        monkeypatch.setattr(sys, "stdout", output)
        parsed.clear()
        assert evidence_command.run(("backup", "disk")) == 0
        rows = output.getvalue().splitlines()[1:-1]
        return [row.split(" | ")[0].strip().partition("#")[0] for row in rows]

    run_and_print()
    assert len(parsed) == len(set(parsed))
    assert set(parsed) <= set(expected_paths)

    printed = run_and_print()
    assert printed
    assert sorted(parsed) == sorted(set(printed))
    assert {path: (root / path).read_bytes() for path in expected_paths} == before

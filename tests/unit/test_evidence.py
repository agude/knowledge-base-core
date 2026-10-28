"""Pure selection and message-addressability rules for evidence search."""

import socket
import subprocess
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import pytest

from kb import corpus, evidence, lock, search
from kb.commands import evidence as evidence_command
from kb.context import Context
from kb.model import Document, parse

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


def test_transcript_source_is_overridden_by_question_storage_kind() -> None:
    document = parse(
        "questions/open/gap.md",
        "---\ntitle: Gap\nsource: session-transcript\n---\n\nQuestion body.\n",
    )
    assert evidence.evidence_kind(document.path, document) == "open-question"


def test_file_ties_sort_by_path_after_date_and_score() -> None:
    query = search.query_terms(("backup", "disk"))
    contents = "---\ntitle: Backup disk\ncreated: 2026-10-20\n---\n\nBackup disk inventory.\n"
    later_path = parse("observations/archived/z.md", contents)
    earlier_path = parse("observations/archived/a.md", contents)
    items = evidence.select(
        [(later_path.path, later_path), (earlier_path.path, earlier_path)],
        query,
        None,
        None,
        None,
        5,
    )
    assert [item.path for item in items] == [
        "observations/archived/a.md",
        "observations/archived/z.md",
    ]


def test_malformed_transcript_remains_a_file_level_result() -> None:
    document = transcript(TRANSCRIPT_FRONT.replace("part: 1\n", "part: 0\n"))
    items = evidence.select(
        [(document.path, document)],
        search.query_terms(("message", "body")),
        None,
        None,
        None,
        5,
    )
    assert len(items) == 1
    assert items[0].path == document.path


def unexpected_external_call(*_args: object, **_kwargs: object) -> None:
    """Fail if the read-only evidence command calls Git, locks, or network services."""
    pytest.fail("read-only evidence command made an external call")


def test_command_parses_each_selected_document_once_and_stays_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "content"
    context = Context(root=root, today=date(2026, 10, 26))
    monkeypatch.setattr(evidence_command, "load", lambda *_args: context)
    expected_paths = sorted(
        path
        for directory in evidence_command.ALL_DIRECTORIES
        for path in corpus.markdown_files(root, directory)
    )
    original_read = corpus.read_document
    parsed_paths: list[str] = []

    def track_read(content_root: Path, path: str) -> Document:
        parsed_paths.append(path)
        return original_read(content_root, path)

    monkeypatch.setattr(corpus, "read_document", track_read)
    monkeypatch.setattr(subprocess, "run", unexpected_external_call)
    monkeypatch.setattr(socket, "socket", unexpected_external_call)
    monkeypatch.setattr(lock, "write_lock", unexpected_external_call)
    output = StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    before = {path: (root / path).read_bytes() for path in expected_paths}

    assert evidence_command.run(("backup", "disk")) == 0
    assert parsed_paths == expected_paths
    assert len(parsed_paths) == len(set(parsed_paths))
    assert {path: (root / path).read_bytes() for path in expected_paths} == before

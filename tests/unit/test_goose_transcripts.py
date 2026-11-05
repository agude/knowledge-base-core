"""Tests for Goose session database parsing, visibility filtering, and shell commands."""

import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kb.hosts import goose
from kb.transcripts import synthetic_id

SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts" / "goose" / "sessions.sql"
CREATED = 1792918800  # 2026-10-25T09:00:00Z
HEADER = goose.Header("session", "/fixture/goose-project", None, None)
VISIBLE = '{"userVisible":true,"agentVisible":true}'


def build(root: Path, *statements: str) -> Path:
    """Write sessions.db under root from the fixture script, then run extra statements."""
    root.mkdir(parents=True, exist_ok=True)
    database = root / goose.DATABASE
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript(SCRIPT.read_text(encoding="utf-8"))
        for statement in statements:
            connection.execute(statement)
        connection.commit()
    return database


def row(
    role: object,
    *items: object,
    created: object = CREATED,
    metadata: object = VISIBLE,
    message_id: object = "fixture-id",
) -> goose.Row:
    return goose.Row(role, json.dumps(list(items)), created, metadata, message_id)


def text(value: str) -> dict[str, object]:
    return {"type": "text", "text": value}


def tool_request(name: str, command: object, *, status: str = "success") -> dict[str, object]:
    return {
        "type": "toolRequest",
        "id": "call",
        "toolCall": {"status": status, "value": {"name": name, "arguments": {"command": command}}},
    }


def test_fixture_keeps_visible_text_and_shell_commands_and_drops_the_rest(tmp_path: Path) -> None:
    build(tmp_path)

    snapshots = goose.read(tmp_path)

    assert [snapshot.session.id for snapshot in snapshots] == ["20261025_1", "20261025_2"]
    main = snapshots[0].session
    assert main.app == "goose"
    assert main.project == "/fixture/goose-project"
    assert main.parent_session is None
    assert main.forked_from is None
    assert main.snapshot_complete
    assert main.latest_timestamp == datetime(2026, 10, 25, 9, 0, 4, tzinfo=UTC)
    assert snapshots[0].updated == datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    assert [message.id for message in main.messages] == [
        "goose-user-1",
        "goose-assistant-1",
        "goose-assistant-2",
    ]
    assert main.messages[0].text == "Summarize this Goose fixture."
    assert main.messages[0].timestamp == datetime(2026, 10, 25, 9, tzinfo=UTC)
    assert main.messages[1].text == "The Goose fixture has a main session."
    assert main.messages[1].commands == ("printf 'fixture command'",)
    retained = "\n".join(message.text for message in main.messages)
    assert "turn-context" not in retained
    assert "Private reasoning" not in retained
    assert "Fixture tool output" not in retained
    assert "compaction summary" not in retained
    assert "for the agent alone" not in retained


def test_subagent_session_names_its_parent(tmp_path: Path) -> None:
    build(tmp_path)

    agent = goose.read(tmp_path)[1].session

    assert agent.id == "20261025_2"
    assert agent.parent_session == "20261025_1"
    assert [message.id for message in agent.messages] == ["goose-agent-user", "goose-agent-answer"]


def test_a_missing_database_has_no_sessions(tmp_path: Path) -> None:
    assert goose.read(tmp_path) == ()
    assert goose.read(tmp_path / "absent") == ()


def test_a_python_without_sqlite3_cannot_read_an_existing_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path)
    monkeypatch.setitem(sys.modules, "sqlite3", None)

    with pytest.raises(goose.DatabaseError, match=r"^this Python has no sqlite3 module$"):
        goose.read(tmp_path)


def test_a_file_that_is_not_a_database_cannot_be_read(tmp_path: Path) -> None:
    (tmp_path / goose.DATABASE).write_bytes(b"not a database\n" * 100)

    with pytest.raises(goose.DatabaseError):
        goose.read(tmp_path)


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (PermissionError(13, "Permission denied", "/fixture/path"), "Permission denied"),
        (OSError(), "OSError"),
    ],
)
def test_a_database_path_that_cannot_be_resolved_is_named_without_its_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError, reason: str
) -> None:
    build(tmp_path)

    def refuse(_path: Path, strict: bool = False) -> Path:
        raise error

    monkeypatch.setattr(Path, "resolve", refuse)
    with pytest.raises(goose.DatabaseError, match=f"^{reason}$"):
        goose.read(tmp_path)


def test_reading_leaves_the_database_unchanged(tmp_path: Path) -> None:
    database = build(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    goose.read(tmp_path)

    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [goose.DATABASE]


def test_a_session_from_a_provider_that_keeps_its_own_transcript_is_skipped(
    tmp_path: Path,
) -> None:
    build(tmp_path)

    sessions = [snapshot.session for snapshot in goose.read(tmp_path)]

    assert "20261025_4" not in [session.id for session in sessions]
    for provider in sorted(goose.PROXIED_PROVIDERS):
        assert goose._header(("id", "/work", None, None, provider)) is None
    assert goose._header(("id", "/work", None, None, "gemini-cli")) is not None


def test_rows_without_a_session_and_sessions_without_an_id_are_skipped(tmp_path: Path) -> None:
    build(
        tmp_path,
        "INSERT INTO sessions (id, working_dir) VALUES ('', '/fixture')",
        "INSERT INTO messages (session_id, role, content_json, created_timestamp, message_id) "
        f"VALUES ('', 'user', '[{{\"type\":\"text\",\"text\":\"orphan\"}}]', {CREATED}, 'o')",
        "INSERT INTO messages (session_id, role, content_json, created_timestamp, message_id) "
        f"VALUES ('gone', 'user', '[{{\"type\":\"text\",\"text\":\"orphan\"}}]', {CREATED}, 'p')",
    )

    assert [snapshot.session.id for snapshot in goose.read(tmp_path)] == [
        "20261025_1",
        "20261025_2",
    ]


def test_malformed_rows_are_counted_and_skipped() -> None:
    rows = [
        row("user", text("kept")),
        goose.Row("user", "{not json", CREATED, VISIBLE, "bad-json"),
        goose.Row("user", '{"type":"text"}', CREATED, VISIBLE, "not-a-list"),
        goose.Row("user", None, CREATED, VISIBLE, "no-content"),
        row("user", text("no time"), created="1792918800"),
        row("user", text("boolean time"), created=True),
        row("user", text("far future"), created=10**20),
    ]

    session = goose.parse(HEADER, rows)

    assert [message.text for message in session.messages] == ["kept"]
    assert session.malformed_lines == 6


def test_millisecond_timestamps_are_read_as_goose_reads_them() -> None:
    session = goose.parse(HEADER, [row("user", text("late"), created=CREATED * 1000 + 250)])

    assert session.messages[0].timestamp == datetime(2026, 10, 25, 9, 0, 0, 250000, tzinfo=UTC)


def test_hidden_messages_and_other_roles_are_dropped_and_bad_metadata_is_visible() -> None:
    rows = [
        row("user", text("hidden"), metadata='{"userVisible":false,"agentVisible":true}'),
        row("system", text("not a turn")),
        row("user", text("unreadable metadata"), metadata="{", message_id="a"),
        row("user", text("no metadata"), metadata=None, message_id="b"),
        row("user", text("list metadata"), metadata="[]", message_id="c"),
        row("assistant", text("agent hidden"), metadata='{"agentVisible":false}', message_id="d"),
    ]

    session = goose.parse(HEADER, rows)

    assert [message.text for message in session.messages] == [
        "unreadable metadata",
        "no metadata",
        "list metadata",
        "agent hidden",
    ]
    assert session.malformed_lines == 0


def test_a_text_block_is_kept_only_when_its_audience_includes_the_user() -> None:
    def annotated(value: str, annotations: object) -> dict[str, object]:
        return {**text(value), "annotations": annotations}

    rows = [
        row(
            "user",
            text("plain"),
            annotated("for the user", {"audience": ["user"]}),
            annotated("for both", {"audience": ["user", "assistant"]}),
            annotated("for the agent", {"audience": ["assistant"]}),
            annotated("no audience", {"priority": 0.5}),
            annotated("unreadable audience", {"audience": "assistant"}),
        ),
        row("user", annotated("only for the agent", {"audience": ["assistant"]}), message_id="b"),
    ]

    session = goose.parse(HEADER, rows)

    assert [message.text for message in session.messages] == [
        "plain\nfor the user\nfor both\nno audience\nunreadable audience"
    ]
    assert session.malformed_lines == 0


def test_only_text_and_shell_requests_are_kept_and_empty_messages_are_dropped() -> None:
    rows = [
        row(
            "assistant",
            "not an item",
            {"type": "thinking", "thinking": "drop"},
            {"type": "text", "text": 7},
            text("first"),
            text("second"),
            tool_request("shell", "printf one"),
            tool_request("developer__shell", "printf two"),
            tool_request("write", "printf three"),
            tool_request("shell", "printf seven", status="error"),
            tool_request("shell", ["printf", "eight"]),
            {"type": "toolRequest", "toolCall": "broken"},
            {"type": "toolRequest", "toolCall": {"status": "success", "value": "broken"}},
            message_id="assistant",
        ),
        row("user", tool_request("shell", "printf user"), message_id="user"),
        row("user", text("  \n"), message_id="blank"),
    ]

    session = goose.parse(HEADER, rows)

    assert len(session.messages) == 1
    assert session.messages[0].text == "first\nsecond"
    assert session.messages[0].commands == ("printf one", "printf two")


def test_a_command_without_text_is_kept() -> None:
    session = goose.parse(HEADER, [row("assistant", tool_request("shell", "printf only"))])

    assert session.messages[0].text == ""
    assert session.messages[0].commands == ("printf only",)


def test_a_missing_id_gets_a_stable_synthetic_id_and_a_duplicate_keeps_the_first() -> None:
    rows = [
        row("user", text("no id"), message_id=None),
        row("assistant", text("empty id"), message_id=""),
        row("user", text("first copy"), message_id="same"),
        row("user", text("second copy"), message_id="same"),
    ]

    session = goose.parse(HEADER, rows)

    assert session.messages[0].id == synthetic_id("goose", str(CREATED), "user", "no id")
    assert session.messages[1].id == synthetic_id("goose", str(CREATED), "assistant", "empty id")
    assert [message.text for message in session.messages[2:]] == ["first copy"]
    assert session.duplicate_ids == 1


def test_updated_at_is_read_as_utc_in_each_stored_form() -> None:
    assert goose._updated("2026-10-25 09:05:00") == datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    assert goose._updated("2026-10-25T09:05:00.123456789+00:00") == datetime(
        2026, 10, 25, 9, 5, 0, 123456, tzinfo=UTC
    )
    assert goose._updated("2026-10-25T10:05:00+01:00") == datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    assert goose._updated("2026-10-25T09:05:00Z") == datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    assert goose._updated("yesterday") is None
    assert goose._updated(None) is None


def test_a_header_reads_only_string_fields() -> None:
    assert goose._header((None, "/work", None, None, None)) is None
    assert goose._header(("id", None, "", 3, None)) == goose.Header("id", "", None, None)
    values = ("id", "/work", "parent", "2026-10-25 09:05:00", "openai")
    assert goose._header(values) == goose.Header(
        "id", "/work", "parent", datetime(2026, 10, 25, 9, 5, tzinfo=UTC)
    )


def test_a_snapshot_without_updated_at_uses_its_newest_message_or_the_epoch() -> None:
    newest = goose._snapshot(HEADER, [row("user", text("only"), created=CREATED + 5)])
    assert newest.updated == datetime(2026, 10, 25, 9, 0, 5, tzinfo=UTC)

    unread = goose._snapshot(HEADER, [row("user", text("no time"), created=None)])
    assert unread.updated == goose.EPOCH

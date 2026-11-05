"""Tests for the Goose kb call reader, with small synthetic session rows and databases."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from kb.hosts import goose
from kb.transcripts import Store

CREATED = 1792918800  # 2026-10-25T09:00:00Z
HEADER = goose.Header("session", "/work", None, None)
VISIBLE = '{"userVisible":true,"agentVisible":true}'


def row(role: str, *items: object, created: int = CREATED) -> goose.Row:
    return goose.Row(role, json.dumps(list(items)), created, VISIBLE, f"{role}-{created}")


def request(call_id: str, command: str, *, name: str = "shell") -> goose.Row:
    item = {
        "type": "toolRequest",
        "id": call_id,
        "toolCall": {
            "status": "success",
            "value": {"name": name, "arguments": {"command": command}},
        },
    }
    return row("assistant", item)


def block(text: str, *audience: str) -> dict[str, object]:
    result: dict[str, object] = {"type": "text", "text": text}
    if audience:
        result["annotations"] = {"audience": list(audience)}
    return result


def response(call_id: str, result: object) -> goose.Row:
    item = {"type": "toolResponse", "id": call_id, "toolResult": result}
    return row("user", item, created=CREATED + 5)


def shell_result(*blocks: object, **flags: object) -> dict[str, object]:
    """A developer shell result: its content blocks, and the structured output with flags."""
    structured = {"stdout": "", "stderr": "", "exit_code": 0, **flags}
    value = {"content": list(blocks), "isError": False, "structuredContent": structured}
    return {"status": "success", "value": value}


def test_a_shell_call_pairs_its_output_by_request_id() -> None:
    rows = [
        request("c1", "kb recall alpha"),
        response("c2", shell_result(block("another output"))),
        response("c1", shell_result(block("the recall output"))),
    ]
    calls = goose.kb_calls(HEADER, rows)
    assert [(call.subcommand, call.arguments, call.output, call.excluded) for call in calls] == [
        ("recall", ("alpha",), "the recall output", None)
    ]
    call = calls[0]
    assert (call.app, call.session_id, call.project) == ("goose", "session", "/work")
    assert call.command == "kb recall alpha"
    assert call.timestamp is not None


def test_one_command_with_two_kb_calls_is_shared() -> None:
    rows = [
        request("c1", "kb recall alpha && kb read knowledge/a.md#1"),
        response("c1", shell_result(block("both"))),
    ]
    calls = goose.kb_calls(HEADER, rows)
    assert [(call.subcommand, call.excluded, call.output) for call in calls] == [
        ("recall", "shared", None),
        ("read", "shared", None),
    ]


def test_a_call_without_a_response_is_missing() -> None:
    calls = goose.kb_calls(HEADER, [request("c1", "kb recall alpha")])
    assert [(call.output, call.excluded) for call in calls] == [(None, "missing")]


def test_a_timed_out_or_truncated_run_is_incomplete() -> None:
    for flag in ("timed_out", "output_truncated"):
        rows = [
            request("c1", "kb recall alpha"),
            response("c1", shell_result(block("partial"), **{flag: True})),
        ]
        assert goose.kb_calls(HEADER, rows)[0].excluded == "incomplete"


def test_a_truncation_notice_block_makes_a_developer_shell_output_incomplete() -> None:
    rows = [
        request("c1", "kb recall alpha", name="developer__shell"),
        response("c1", shell_result(block("output"), block("output was cut short"))),
    ]
    assert goose.kb_calls(HEADER, rows)[0].excluded == "incomplete"


def test_an_older_shell_result_keeps_the_block_for_the_assistant() -> None:
    result = {
        "status": "success",
        "value": [block("for the agent", "assistant"), block("for the user", "user")],
    }
    rows = [
        request("c1", "kb read knowledge/a.md#1", name="developer__shell"),
        response("c1", result),
    ]
    assert goose.kb_calls(HEADER, rows)[0].output == "for the agent"


def test_failed_or_unrecognized_results_are_unsupported() -> None:
    results: list[object] = [
        {"status": "error", "error": "the tool failed"},
        "not a result",
        {"status": "success", "value": {"content": "not a list"}},
        {"status": "success", "value": {"content": [block("kb: error")], "isError": True}},
        {"status": "success", "value": [{"type": "image", "data": "", "mimeType": "image/png"}]},
    ]
    for result in results:
        rows = [request("c1", "kb recall alpha"), response("c1", result)]
        assert goose.kb_calls(HEADER, rows)[0].excluded == "unsupported"


def test_other_tools_text_and_unreadable_content_record_no_kb_call() -> None:
    rows = [
        goose.Row("assistant", "not json", CREATED, VISIBLE, "bad"),
        row("assistant", "not an item", {"type": "toolRequest", "id": 7}),
        row("assistant", {"type": "text", "id": "t1", "text": "kb recall alpha"}),
        request("c1", "kb recall alpha", name="read"),
        request("c2", "ls -la"),
        row("user", {"type": "toolRequest", "id": "c3", "toolCall": {}}),
    ]
    assert goose.kb_calls(HEADER, rows) == ()


def test_read_store_reads_every_session_and_counts_the_database(tmp_path: Path) -> None:
    with closing(sqlite3.connect(tmp_path / goose.DATABASE)) as connection:
        connection.executescript(
            "CREATE TABLE sessions (id TEXT, working_dir TEXT, parent_session_id TEXT,"
            " updated_at TEXT, provider_name TEXT);"
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
            " content_json TEXT, created_timestamp INTEGER, metadata_json TEXT, message_id TEXT);"
            "INSERT INTO sessions VALUES ('s1', '/work', NULL, NULL, NULL),"
            " ('s2', '/work', 's1', NULL, NULL), ('s3', '/work', NULL, NULL, 'codex-acp');"
        )
        for session, created, item in (
            ("s1", CREATED, request("c1", "kb recall alpha")),
            ("s1", CREATED + 1, response("c1", shell_result(block("out")))),
            ("s2", CREATED + 60, request("c1", "kb read knowledge/a.md#1")),
            ("s3", CREATED + 120, request("c1", "kb recall proxied")),
        ):
            connection.execute(
                "INSERT INTO messages (session_id, role, content_json, created_timestamp,"
                " metadata_json, message_id) VALUES (?, ?, ?, ?, ?, ?)",
                (session, item.role, item.content, created, item.metadata, item.message_id),
            )
        connection.commit()

    store = goose.read_store(tmp_path)

    assert (store.files, store.unreadable) == (1, 0)
    assert [(call.session_id, call.excluded) for call in store.calls] == [
        ("s1", None),
        ("s2", "missing"),
    ]
    assert store.first is not None and store.last is not None
    assert (store.last - store.first).total_seconds() == 60


def test_a_missing_database_is_an_empty_store_and_a_broken_one_is_unreadable(
    tmp_path: Path,
) -> None:
    assert goose.read_store(tmp_path) == Store((), 0, 0, None, None)
    (tmp_path / goose.DATABASE).write_bytes(b"not a database")
    assert goose.read_store(tmp_path) == Store((), 1, 1, None, None)

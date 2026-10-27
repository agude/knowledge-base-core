"""Tests for Claude Code transcript parsing and filtering."""

import json
from datetime import UTC, datetime
from pathlib import Path

from kb.hosts import claude
from kb.transcripts import synthetic_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts" / "claude"


def record(
    role: str,
    content: object,
    *,
    message_id: str | None = "fixture-id",
    timestamp: str | None = "2026-10-25T08:00:00Z",
    **fields: object,
) -> str:
    value: dict[str, object] = {
        "type": role,
        "message": {"role": role, "content": content},
    }
    if message_id is not None:
        value["uuid"] = message_id
    if timestamp is not None:
        value["timestamp"] = timestamp
    value.update(fields)
    return json.dumps(value, separators=(",", ":"))


def test_main_fixture_extracts_text_bash_commands_and_project() -> None:
    text = (FIXTURES / "projects/demo/main.jsonl").read_text(encoding="utf-8")

    session = claude.parse(text, "main")

    assert session.app == "claude-code"
    assert session.id == "main"
    assert session.project == "/fixture/claude-project"
    assert session.parent_session is None
    assert session.latest_timestamp == datetime(2026, 10, 25, 8, 4, tzinfo=UTC)
    assert [message.id for message in session.messages] == [
        "main-user-1",
        "main-assistant-1",
        "main-assistant-2",
        "main-assistant-3",
    ]
    assert session.messages[1].text == "The fixture has two records."
    assert session.messages[2].commands == ("printf 'fixture command'",)
    assert all("Private reasoning" not in message.text for message in session.messages)
    assert all("Fixture tool output" not in message.text for message in session.messages)


def test_subagent_fixture_retains_sidechain_messages_and_parent() -> None:
    text = (FIXTURES / "projects/demo/subagent-parent/subagents/agent-helper.jsonl").read_text(
        encoding="utf-8"
    )

    session = claude.parse(text, "agent-helper", "subagent-parent")

    assert session.id == "agent-helper"
    assert session.parent_session == "subagent-parent"
    assert [message.text for message in session.messages] == [
        "Inspect the fixture task.",
        "The fixture task is complete.",
    ]


def test_filter_fixture_removes_reminders_meta_tool_output_and_thinking() -> None:
    text = (FIXTURES / "projects/demo/filtered.jsonl").read_text(encoding="utf-8")

    session = claude.parse(text, "filtered")

    assert [message.id for message in session.messages] == [
        "filtered-user",
        "filtered-assistant",
    ]
    assert session.messages[0].text == "Keep this request.  Keep this ending."
    assert session.messages[1].text == "Keep this answer."
    assert "system-reminder" not in session.messages[0].text
    assert session.malformed_lines == 0


def test_heading_fixture_preserves_tilde_fences_inside_message_text() -> None:
    text = (FIXTURES / "projects/demo/heading.jsonl").read_text(encoding="utf-8")
    session = claude.parse(text, "heading")
    assert "## Heading inside a message" in session.messages[1].text
    assert "~~~~sh" in session.messages[1].text


def test_user_string_and_text_blocks_are_kept_but_non_text_blocks_are_skipped() -> None:
    blocks = [
        {"type": "text", "text": "First."},
        3,
        {"type": "tool_result", "content": "Do not keep."},
        {"type": "text", "text": "Second."},
        {"type": "text", "text": 4},
    ]
    text = (
        "\n".join(
            (
                record("user", "Direct user string.", message_id="direct"),
                record("user", blocks, message_id="blocks"),
            )
        )
        + "\n"
    )

    session = claude.parse(text, "blocks")

    assert [message.text for message in session.messages] == [
        "Direct user string.",
        "First.\nSecond.",
    ]


def test_assistant_keeps_text_blocks_and_only_bash_commands() -> None:
    content = [
        {"type": "thinking", "thinking": "Do not keep."},
        {"type": "text", "text": "Answer."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "secret"}},
        {"type": "tool_use", "name": "Bash", "input": {"command": "printf ok"}},
        {"type": "tool_use", "name": "Bash", "input": "bad-shape"},
        {"type": "tool_use", "name": "Bash", "input": {"command": 4}},
    ]

    session = claude.parse(record("assistant", content) + "\n", "commands")

    assert session.messages[0].text == "Answer."
    assert session.messages[0].commands == ("printf ok",)


def test_message_without_text_or_command_is_skipped() -> None:
    text = (
        "\n".join(
            (
                record(
                    "user",
                    "<system-reminder>only reminder</system-reminder>",
                    message_id="reminder",
                ),
                record(
                    "assistant",
                    [{"type": "thinking", "thinking": "private"}],
                    message_id="thinking",
                ),
                record("assistant", "assistant strings are not text blocks", message_id="string"),
            )
        )
        + "\n"
    )
    assert claude.parse(text, "empty").messages == ()


def test_meta_and_unknown_records_are_ignored_without_needing_message_fields() -> None:
    text = (
        "\n".join(
            (
                json.dumps({"type": "user", "isMeta": True}),
                json.dumps({"type": "system", "cwd": 2}),
                json.dumps({"type": "mode", "cwd": ""}),
                json.dumps({"type": "attachment", "cwd": "/fixture/claude-project"}),
                json.dumps({"type": "system", "cwd": "/later/project"}),
            )
        )
        + "\n"
    )

    session = claude.parse(text, "meta")

    assert session.messages == ()
    assert session.project == "/fixture/claude-project"
    assert session.malformed_lines == 0


def test_latest_timestamp_includes_unkept_records_and_keeps_the_maximum() -> None:
    text = (
        "\n".join(
            (
                record("user", "Keep.", message_id="kept", timestamp="2026-10-25T08:00:00Z"),
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2026-10-25T11:30:00Z",
                        "message": {"content": []},
                    }
                ),
                json.dumps({"type": "tool_result", "timestamp": "2026-10-25T10:00:00Z"}),
            )
        )
        + "\n"
    )
    session = claude.parse(text, "activity")
    assert len(session.messages) == 1
    assert session.latest_timestamp == datetime(2026, 10, 25, 11, 30, tzinfo=UTC)


def test_invalid_message_records_are_counted_as_malformed() -> None:
    text = (
        "\n".join(
            (
                json.dumps({"type": "user", "timestamp": "2026-10-25T08:00:00Z"}),
                record("assistant", "Answer.", timestamp="not-a-time"),
                "[]",
                record("user", "Missing timestamp.", timestamp=None),
            )
        )
        + "\n"
    )

    session = claude.parse(text, "malformed")

    assert session.messages == ()
    assert session.malformed_lines == 4


def test_interior_bad_json_is_counted_but_final_bad_json_makes_snapshot_incomplete() -> None:
    good = record("user", "Kept.", message_id="good")
    assistant = record("assistant", [{"type": "text", "text": "Also kept."}])
    interior = claude.parse(f"{good}\nnot-json\n{assistant}\n", "interior")
    assert interior.snapshot_complete
    assert interior.malformed_lines == 1
    assert len(interior.messages) == 2

    final = claude.parse(f"{good}\nnot-json\n", "final")
    assert not final.snapshot_complete
    assert final.malformed_lines == 0
    assert len(final.messages) == 1


def test_partial_final_line_is_excluded_and_marks_snapshot_incomplete() -> None:
    good = record("user", "Kept.", message_id="good")

    session = claude.parse(f"{good}\n{record('assistant', 'Still being written.')}", "partial")

    assert not session.snapshot_complete
    assert [message.id for message in session.messages] == ["good"]


def test_missing_id_uses_a_stable_synthetic_id() -> None:
    timestamp = "2026-10-25T08:00:00Z"
    session = claude.parse(
        record("user", "Synthetic.", message_id=None, timestamp=timestamp) + "\n", "s"
    )
    expected = synthetic_id("claude-code", timestamp, "user", "Synthetic.")
    assert session.messages[0].id == expected
    assert session.messages[0].timestamp == datetime(2026, 10, 25, 8, tzinfo=UTC)


def test_duplicate_ids_keep_the_first_message_and_report_the_duplicate() -> None:
    text = (
        "\n".join(
            (
                record("user", "First.", message_id="same"),
                record("assistant", [{"type": "text", "text": "Later."}], message_id="same"),
            )
        )
        + "\n"
    )

    session = claude.parse(text, "duplicate")

    assert [message.text for message in session.messages] == ["First."]
    assert session.duplicate_ids == 1

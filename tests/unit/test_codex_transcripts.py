"""Tests for Codex rollout parsing, injected-context removal, and shell calls."""

import json
from datetime import UTC, datetime
from pathlib import Path

from kb.hosts import codex
from kb.transcripts import synthetic_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "transcripts" / "codex"
TIMESTAMP = "2026-10-25T14:00:00Z"


def item(item_type: str, payload: dict[str, object], *, timestamp: str = TIMESTAMP) -> str:
    return json.dumps(
        {
            "type": "response_item",
            "timestamp": timestamp,
            "payload": {"type": item_type, **payload},
        },
        separators=(",", ":"),
    )


def message(
    role: str,
    content: object,
    *,
    message_id: str | None = "fixture-id",
    timestamp: str = TIMESTAMP,
) -> str:
    payload: dict[str, object] = {"type": "message", "role": role, "content": content}
    if message_id is not None:
        payload["id"] = message_id
    return json.dumps(
        {"type": "response_item", "timestamp": timestamp, "payload": payload},
        separators=(",", ":"),
    )


def metadata(session: str, **fields: object) -> str:
    return json.dumps(
        {"type": "session_meta", "payload": {"id": session, **fields}},
        separators=(",", ":"),
    )


def test_main_fixture_uses_filename_matching_metadata_and_filters_user_context() -> None:
    text = (FIXTURES / "sessions/2026/10/25/rollout-codex-main.jsonl").read_text(encoding="utf-8")

    session = codex.parse(text, "rollout-codex-main.jsonl")

    assert session.app == "codex"
    assert session.id == "codex-main"
    assert session.project == "/fixture/project"
    assert session.parent_session is None
    assert session.latest_timestamp == datetime(2026, 10, 25, 14, 0, 4, tzinfo=UTC)
    assert [message.id for message in session.messages] == [
        "codex-user-1",
        "codex-assistant-1",
        "codex-exec-1",
    ]
    assert session.messages[0].text == "Summarize this Codex fixture."
    assert session.messages[1].text == "The Codex fixture has a main thread."
    assert session.messages[2].commands == ("printf 'fixture command'",)
    assert all("environment_context" not in message.text for message in session.messages)


def test_timestamped_rollout_matches_the_session_id_suffix() -> None:
    fixture_path = (
        FIXTURES
        / "sessions/2026/08/17/rollout-2026-08-17T11-46-46-01a0110c-31c3-7180-98fd-9924acb7a487.jsonl"
    )

    session = codex.parse(fixture_path.read_text(encoding="utf-8"), fixture_path.name)

    assert session.id == "01a0110c-31c3-7180-98fd-9924acb7a487"
    assert session.project == "/fixture/project"
    assert [message.id for message in session.messages] == ["timestamped-user"]


def test_subagent_fixture_uses_parent_thread_id() -> None:
    text = (FIXTURES / "sessions/2026/10/25/rollout-codex-agent.jsonl").read_text(encoding="utf-8")
    session = codex.parse(text, "rollout-codex-agent.jsonl")
    assert session.id == "codex-agent"
    assert session.parent_session == "codex-main"
    assert [message.id for message in session.messages] == [
        "codex-agent-user",
        "codex-agent-answer",
    ]


def test_matching_metadata_wins_over_other_and_later_metadata_ids() -> None:
    text = (
        "\n".join(
            (
                metadata("other", cwd="/wrong", parent_thread_id="wrong-parent"),
                metadata(
                    "main",
                    cwd="/right",
                    parent_thread_id="parent",
                    forked_from_id="fork-owner",
                ),
                metadata("main", cwd="/later"),
            )
        )
        + "\n"
    )

    session = codex.parse(text, "rollout-main.jsonl")

    assert session.id == "main"
    assert session.project == "/right"
    assert session.parent_session == "parent"
    assert session.forked_from == "fork-owner"


def test_metadata_with_non_string_relationships_leaves_them_unset() -> None:
    text = metadata("main", cwd=4, parent_thread_id=2, forked_from_id=3) + "\n"
    session = codex.parse(text, "rollout-main.jsonl")
    assert session.id == "main"
    assert session.project == ""
    assert session.parent_session is None
    assert session.forked_from is None


def test_missing_matching_session_metadata_produces_no_session_id() -> None:
    text = metadata("different", cwd="/wrong") + "\n"
    session = codex.parse(text, "rollout-main.jsonl")
    assert session.id is None
    assert session.project == ""
    assert session.parent_session is None


def test_non_rollout_filename_cannot_match_metadata() -> None:
    assert codex.parse(metadata("main") + "\n", "main.jsonl").id is None
    assert codex.parse(metadata("main") + "\n", "rollout-.jsonl").id is None


def test_user_injected_context_blocks_are_removed_and_other_text_is_kept() -> None:
    text = message(
        "user",
        [
            {
                "type": "input_text",
                "text": (
                    "<environment_context>Drop environment.</environment_context>\n"
                    "<codex_internal_context>Drop internal.</codex_internal_context>\n"
                    "<AGENTS.md instructions>Drop instructions.</AGENTS.md instructions>\n"
                    "Keep this request."
                ),
            },
            {"type": "input_text", "text": "Second block."},
        ],
    )

    session = codex.parse(text + "\n", "rollout-main.jsonl")

    assert session.messages[0].text == "Keep this request.\nSecond block."
    assert "Drop environment" not in session.messages[0].text
    assert "Drop internal" not in session.messages[0].text
    assert "Drop instructions" not in session.messages[0].text


def test_message_with_only_injected_context_is_skipped() -> None:
    text = message(
        "user",
        [
            {
                "type": "input_text",
                "text": "<environment_context>Only injected.</environment_context>",
            }
        ],
    )
    assert codex.parse(text + "\n", "rollout-main.jsonl").messages == ()


def test_user_and_assistant_text_blocks_use_their_roles() -> None:
    records = (
        "\n".join(
            (
                message(
                    "user",
                    [
                        {"type": "output_text", "text": "Wrong block."},
                        {"type": "text", "text": "User."},
                    ],
                    message_id="user",
                ),
                message(
                    "assistant",
                    [
                        {"type": "input_text", "text": "Wrong block."},
                        {"type": "output_text", "text": "Assistant."},
                    ],
                    message_id="assistant",
                ),
                message("developer", "Do not keep.", message_id="developer"),
            )
        )
        + "\n"
    )

    session = codex.parse(records, "rollout-main.jsonl")

    assert [(value.role, value.text) for value in session.messages] == [
        ("user", "User."),
        ("assistant", "Assistant."),
    ]


def test_plain_string_content_and_empty_content() -> None:
    records = (
        "\n".join(
            (
                message("user", "Plain user text.", message_id="plain"),
                message("assistant", 4, message_id="empty"),
            )
        )
        + "\n"
    )
    session = codex.parse(records, "rollout-main.jsonl")
    assert [value.text for value in session.messages] == ["Plain user text."]


def test_text_blocks_ignore_invalid_and_non_text_blocks() -> None:
    content = [
        3,
        {"type": "input_text", "text": 4},
        {"type": "reasoning", "text": "Do not keep."},
        {"type": "input_text", "text": "Keep."},
    ]
    session = codex.parse(message("user", content) + "\n", "rollout-main.jsonl")
    assert session.messages[0].text == "Keep."


def test_exec_custom_tool_call_and_supported_function_call_variants() -> None:
    records = (
        "\n".join(
            (
                item("custom_tool_call", {"id": "exec-1", "name": "exec", "input": "printf one"}),
                item(
                    "function_call",
                    {
                        "id": "exec-2",
                        "name": "functions.exec_command",
                        "arguments": {"cmd": "printf two"},
                    },
                ),
                item("function_call", {"id": "exec-3", "name": "shell", "input": "printf three"}),
            )
        )
        + "\n"
    )

    session = codex.parse(records, "rollout-main.jsonl")

    assert [message.commands for message in session.messages] == [
        ("printf one",),
        ("printf two",),
        ("printf three",),
    ]


def test_commands_accept_json_arguments_and_ignore_other_tool_calls() -> None:
    records = (
        "\n".join(
            (
                item(
                    "custom_tool_call",
                    {"id": "exec-json", "name": "exec", "input": '{"command":"printf json"}'},
                ),
                item("custom_tool_call", {"name": "Read", "input": "not a shell call"}),
                item(
                    "function_call", {"name": "send_message", "arguments": {"command": "not shell"}}
                ),
                item("custom_tool_call_output", {"name": "exec", "output": "never keep output"}),
            )
        )
        + "\n"
    )
    session = codex.parse(records, "rollout-main.jsonl")
    assert [message.commands for message in session.messages] == [("printf json",)]


def test_missing_command_id_is_synthetic_and_timestamp_is_normalized() -> None:
    timestamp = "2026-10-25T07:00:00-07:00"
    raw = json.dumps(
        {
            "type": "response_item",
            "timestamp": timestamp,
            "payload": {"type": "custom_tool_call", "name": "exec", "input": "printf stable"},
        }
    )

    session = codex.parse(raw + "\n", "rollout-main.jsonl")

    assert session.messages[0].id == synthetic_id("codex", timestamp, "assistant", "")
    assert session.messages[0].timestamp == datetime(2026, 10, 25, 14, tzinfo=UTC)


def test_invalid_tool_arguments_are_ignored() -> None:
    records = (
        "\n".join(
            (
                item("custom_tool_call", {"name": "exec", "input": None}),
                item("custom_tool_call", {"name": 4, "input": "not a call"}),
                item("function_call", {"name": "exec", "arguments": '{"other": 4}'}),
            )
        )
        + "\n"
    )
    assert codex.parse(records, "rollout-main.jsonl").messages == ()


def test_json_primitive_tool_input_is_treated_as_raw_command_text() -> None:
    record = item("custom_tool_call", {"name": "exec", "input": "123"})
    session = codex.parse(record + "\n", "rollout-main.jsonl")
    assert session.messages[0].commands == ("123",)


def test_interior_malformed_json_and_bad_response_items_are_counted() -> None:
    text = (
        "\n".join(
            (
                "not-json",
                json.dumps({"type": "response_item", "payload": 4}),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {"type": "message", "role": "user", "content": "x"},
                    }
                ),
                "[]",
                json.dumps({"type": "event_msg", "payload": {"type": "user_message"}}),
            )
        )
        + "\n"
    )
    session = codex.parse(text, "rollout-main.jsonl")
    assert session.malformed_lines == 4
    assert session.messages == ()


def test_final_bad_json_and_partial_line_make_snapshot_incomplete() -> None:
    final_bad = codex.parse(
        f"{message('user', 'Keep.', message_id='keep')}\nnot-json\n", "rollout-main.jsonl"
    )
    assert not final_bad.snapshot_complete
    assert final_bad.malformed_lines == 0
    assert len(final_bad.messages) == 1

    partial = codex.parse(
        f'{message("user", "Keep.", message_id="keep")}\n{{"type":', "rollout-main.jsonl"
    )
    assert not partial.snapshot_complete
    assert len(partial.messages) == 1


def test_duplicate_message_ids_keep_first_occurrence() -> None:
    text = (
        "\n".join(
            (
                message("user", "First.", message_id="same"),
                message("assistant", "Later.", message_id="same"),
            )
        )
        + "\n"
    )
    session = codex.parse(text, "rollout-main.jsonl")
    assert [value.text for value in session.messages] == ["First."]
    assert session.duplicate_ids == 1

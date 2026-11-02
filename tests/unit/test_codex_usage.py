"""Tests for the Codex kb call reader, with small synthetic rollouts."""

import json
from collections.abc import Mapping
from pathlib import Path

from kb.hosts import codex

FILENAME = "rollout-2026-10-20T10-00-00-abc123.jsonl"
WHEN = "2026-10-20T10:00:00Z"


def lines(*records: Mapping[str, object]) -> str:
    return "\n".join(json.dumps(record) for record in records) + "\n"


def meta() -> dict[str, object]:
    return {"timestamp": WHEN, "type": "session_meta", "payload": {"id": "abc123", "cwd": "/work"}}


def exec_call(call_id: str, source: str) -> dict[str, object]:
    return {
        "timestamp": WHEN,
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": call_id,
            "name": "exec",
            "input": source,
        },
    }


def exec_output(call_id: str, text: str) -> dict[str, object]:
    return {
        "timestamp": "2026-10-20T10:00:05Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": [{"type": "input_text", "text": text}],
        },
    }


def shell_call(call_id: str, command: str) -> dict[str, object]:
    arguments = json.dumps({"command": command})
    return {
        "timestamp": WHEN,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "call_id": call_id,
            "name": "shell",
            "arguments": arguments,
        },
    }


def shell_output(call_id: str, text: str) -> dict[str, object]:
    return {
        "timestamp": "2026-10-20T10:00:05Z",
        "type": "response_item",
        "payload": {"type": "function_call_output", "call_id": call_id, "output": text},
    }


def test_each_exec_command_is_a_call_and_all_share_the_script_output() -> None:
    source = (
        'const a = await tools.exec_command({cmd:"kb recall alpha",workdir:"/w"});\n'
        'const b = await tools.exec_command({cmd:"kb read knowledge/a.md#1"});'
    )
    text = lines(meta(), exec_call("c1", source), exec_output("c1", "script output"))
    calls = codex.kb_calls(text, FILENAME)
    assert [(call.subcommand, call.arguments, call.shared) for call in calls] == [
        ("recall", ("alpha",), True),
        ("read", ("knowledge/a.md#1",), True),
    ]
    assert {call.output for call in calls} == {"script output"}
    assert calls[0].command == "kb recall alpha"


def test_a_shell_function_call_pairs_its_output_by_call_id() -> None:
    text = lines(
        meta(),
        shell_call("c1", "kb gap --title t --body b"),
        shell_output("c1", "Gap recorded"),
    )
    calls = codex.kb_calls(text, FILENAME)
    assert len(calls) == 1
    assert calls[0].subcommand == "gap"
    assert calls[0].output == "Gap recorded"
    assert calls[0].shared is False


def test_a_call_without_an_output_has_none() -> None:
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb recall alpha"})'))
    calls = codex.kb_calls(text, FILENAME)
    assert calls[0].output is None


def test_non_kb_exec_scripts_are_ignored() -> None:
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"ls -la"})'),
        exec_output("c1", "listing"),
        exec_call("c2", 'tools.exec_command({cmd:"kb sync --status"})'),
        exec_output("c2", "status"),
    )
    assert codex.kb_calls(text, FILENAME) == ()


def test_session_id_comes_from_the_filename_and_project_from_session_meta() -> None:
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb recall a"})'))
    call = codex.kb_calls(text, FILENAME)[0]
    assert call.session_id == "abc123"
    assert call.project == "/work"
    assert call.timestamp is not None
    assert call.timestamp.isoformat() == "2026-10-20T10:00:00+00:00"


def test_a_template_literal_is_not_read_as_a_command() -> None:
    source = "tools.exec_command({cmd:`kb recall alpha`})"
    assert codex.kb_calls(lines(meta(), exec_call("c1", source)), FILENAME) == ()


def test_read_store_walks_rollouts_and_counts_unreadable(tmp_path: Path) -> None:
    day = tmp_path / "2026" / "10" / "20"
    day.mkdir(parents=True)
    (day / FILENAME).write_text(
        lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb recall a"})')),
        encoding="utf-8",
    )
    (day / "rollout-2026-10-20T11-00-00-bad.jsonl").write_bytes(b"\xff\xfe")
    (day / "other.jsonl").write_text("{}\n", encoding="utf-8")
    store = codex.read_store(tmp_path)
    assert store.files == 2
    assert store.unreadable == 1
    assert len(store.calls) == 1

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


HEADER = "Script completed\nWall time 0.5 seconds\nOutput:\n"


def script_output(call_id: str, *blocks: str) -> dict[str, object]:
    """An exec output record: the exec header block, then the given output blocks."""
    texts = [HEADER, *blocks]
    return {
        "timestamp": "2026-10-20T10:00:05Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": [{"type": "input_text", "text": text} for text in texts],
        },
    }


def test_a_script_with_two_kb_commands_shares_its_output_and_excludes_both() -> None:
    source = (
        'const a = await tools.exec_command({cmd:"kb recall alpha",workdir:"/w"});\n'
        'const b = await tools.exec_command({cmd:"kb read knowledge/a.md#1"});'
    )
    text = lines(meta(), exec_call("c1", source), script_output("c1", "script output"))
    calls = codex.kb_calls(text, FILENAME)
    assert [(call.subcommand, call.arguments, call.excluded) for call in calls] == [
        ("recall", ("alpha",), "shared"),
        ("read", ("knowledge/a.md#1",), "shared"),
    ]
    assert {call.output for call in calls} == {None}
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
    assert calls[0].excluded is None


def test_a_single_command_script_gives_its_output_when_it_runs_one_kb_call() -> None:
    source = 'tools.exec_command({cmd:"kb recall alpha"})'
    text = lines(meta(), exec_call("c1", source), script_output("c1", "the recall text"))
    call = codex.kb_calls(text, FILENAME)[0]
    assert call.output == "the recall text"
    assert call.excluded is None


def test_one_command_with_two_kb_calls_is_shared() -> None:
    text = lines(
        meta(),
        shell_call("c1", "kb recall alpha && kb read knowledge/a.md#1"),
        shell_output("c1", "both"),
    )
    assert [call.excluded for call in codex.kb_calls(text, FILENAME)] == ["shared", "shared"]


def test_a_call_without_an_output_is_missing() -> None:
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb recall alpha"})'))
    calls = codex.kb_calls(text, FILENAME)
    assert calls[0].output is None
    assert calls[0].excluded == "missing"


def test_a_plain_string_shell_output_is_used() -> None:
    text = lines(meta(), shell_call("c1", "kb read knowledge/a.md#1"), shell_output("c1", "body"))
    assert codex.kb_calls(text, FILENAME)[0].output == "body"


def test_a_shell_output_that_is_not_a_string_is_unsupported() -> None:
    record = shell_output("c1", "unused")
    record["payload"]["output"] = [{"type": "input_text", "text": "body"}]  # type: ignore[index]
    text = lines(meta(), shell_call("c1", "kb read knowledge/a.md#1"), record)
    assert codex.kb_calls(text, FILENAME)[0].excluded == "unsupported"


def test_a_result_object_gives_its_output_field() -> None:
    result = json.dumps(
        {
            "output": "result text",
            "chunk_id": "a1",
            "wall_time_seconds": 0.2,
            "exit_code": 0,
            "original_token_count": 4,
        }
    )
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
        script_output("c1", result),
    )
    assert codex.kb_calls(text, FILENAME)[0].output == "result text"


def test_a_running_process_is_incomplete() -> None:
    running = json.dumps(
        {
            "output": "partial",
            "chunk_id": "a1",
            "wall_time_seconds": 1.0,
            "session_id": 7,
            "original_token_count": 4,
        }
    )
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
        script_output("c1", running),
    )
    assert codex.kb_calls(text, FILENAME)[0].excluded == "incomplete"


def test_a_truncation_warning_is_incomplete() -> None:
    warning = "Warning: truncated output (original token count: 9000)\nTotal output lines: 3"
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
        script_output("c1", warning),
    )
    assert codex.kb_calls(text, FILENAME)[0].excluded == "incomplete"


def result_envelope(output: str) -> str:
    return json.dumps(
        {
            "chunk_id": "a1",
            "exit_code": 0,
            "original_token_count": 40,
            "output": output,
            "wall_time_seconds": 0.2,
        }
    )


def test_a_result_object_whose_output_is_a_truncation_warning_is_incomplete() -> None:
    warning = "Warning: truncated output (original token count: 9000)\nTotal output lines: 3"
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
        script_output("c1", result_envelope(warning + "\nsynthetic recall text")),
    )
    call = codex.kb_calls(text, FILENAME)[0]
    assert call.excluded == "incomplete"
    assert call.output is None


def test_a_normal_result_object_is_still_usable() -> None:
    text = lines(
        meta(),
        exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
        script_output("c1", result_envelope("synthetic recall text")),
    )
    call = codex.kb_calls(text, FILENAME)[0]
    assert call.excluded is None
    assert call.output == "synthetic recall text"


def test_a_batch_of_results_is_a_batch() -> None:
    batch = json.dumps([{"i": 0, "status": "fulfilled", "value": "x"}])
    batch_object = json.dumps({"i": 0, "status": "fulfilled", "value": "x"})
    for block in (
        batch_object,
        json.dumps({"status": "fulfilled", "value": "x"}),
        json.dumps({"i": 0, "result": "x"}),
    ):
        text = lines(
            meta(),
            exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'),
            script_output("c1", block),
        )
        assert codex.kb_calls(text, FILENAME)[0].excluded == "batch", block
    text = lines(
        meta(), exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'), script_output("c1", batch)
    )
    assert codex.kb_calls(text, FILENAME)[0].excluded == "unsupported"


def test_an_unrecognized_json_object_is_unsupported() -> None:
    other = json.dumps({"file": "a", "section": "b"})
    text = lines(
        meta(), exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'), script_output("c1", other)
    )
    assert codex.kb_calls(text, FILENAME)[0].excluded == "unsupported"


def test_an_unknown_script_header_is_unsupported() -> None:
    record = script_output("c1", "body")
    record["payload"]["output"][0]["text"] = "Something else\n"  # type: ignore[index]
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'), record)
    assert codex.kb_calls(text, FILENAME)[0].excluded == "unsupported"


def test_a_failed_script_keeps_its_output() -> None:
    record = script_output("c1", "error text")
    record["payload"]["output"][0]["text"] = "Script failed\nWall time 0.1 seconds\nOutput:\n"  # type: ignore[index]
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'), record)
    assert codex.kb_calls(text, FILENAME)[0].output == "error text"


def test_an_image_block_is_unsupported() -> None:
    record = script_output("c1", "body")
    record["payload"]["output"].append({"type": "input_image", "image_url": "data:"})  # type: ignore[index]
    text = lines(meta(), exec_call("c1", 'tools.exec_command({cmd:"kb read a"})'), record)
    assert codex.kb_calls(text, FILENAME)[0].excluded == "unsupported"


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
    assert store.calls[0].excluded == "missing"

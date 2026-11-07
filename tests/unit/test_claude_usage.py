"""Tests for the Claude Code kb call reader, with small synthetic transcripts."""

import json
from collections.abc import Mapping
from pathlib import Path

from kb.hosts import claude

SESSION = "s1"
WHEN = "2026-10-20T10:00:00Z"


def lines(*records: Mapping[str, object]) -> str:
    return "\n".join(json.dumps(record) for record in records) + "\n"


def bash_use(use_id: str, command: str, when: str = WHEN, tool: str = "Bash") -> dict[str, object]:
    return {
        "type": "assistant",
        "timestamp": when,
        "cwd": "/work",
        "message": {
            "content": [
                {"type": "tool_use", "id": use_id, "name": tool, "input": {"command": command}}
            ]
        },
    }


def result(use_id: str, content: object) -> dict[str, object]:
    return {
        "type": "user",
        "timestamp": "2026-10-20T10:00:05Z",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": use_id, "content": content}]
        },
    }


def test_each_result_pairs_with_its_tool_use_by_id_not_by_order() -> None:
    text = lines(
        bash_use("t1", "kb recall alpha"),
        bash_use("t2", "kb read knowledge/a.md#1"),
        result("t2", "the read output"),
        result("t1", "the recall output"),
    )
    calls = claude.kb_calls(text, SESSION)
    outputs = {call.subcommand: call.output for call in calls}
    assert outputs == {"recall": "the recall output", "read": "the read output"}


def test_several_kb_calls_in_one_command_share_its_output_and_exclude_it() -> None:
    text = lines(
        bash_use("t1", "kb recall alpha && kb read knowledge/a.md#1"),
        result("t1", "shared output"),
    )
    calls = claude.kb_calls(text, SESSION)
    assert [(call.subcommand, call.excluded, call.output) for call in calls] == [
        ("recall", "shared", None),
        ("read", "shared", None),
    ]


def test_a_single_kb_call_keeps_its_output() -> None:
    calls = claude.kb_calls(lines(bash_use("t1", "kb recall alpha"), result("t1", "out")), SESSION)
    assert (calls[0].excluded, calls[0].output) == (None, "out")


def test_a_call_without_a_result_is_missing() -> None:
    calls = claude.kb_calls(lines(bash_use("t1", "kb recall alpha")), SESSION)
    assert len(calls) == 1
    assert calls[0].output is None
    assert calls[0].excluded == "missing"


def test_an_error_result_keeps_its_text() -> None:
    record = result("t1", "kb: no such path")
    record["message"]["content"][0]["is_error"] = True  # type: ignore[index]
    calls = claude.kb_calls(lines(bash_use("t1", "kb read a"), record), SESSION)
    assert (calls[0].excluded, calls[0].output) == (None, "kb: no such path")


def test_a_result_with_a_non_text_block_is_unsupported() -> None:
    content = [{"type": "text", "text": "words"}, {"type": "image", "source": {}}]
    calls = claude.kb_calls(lines(bash_use("t1", "kb read a"), result("t1", content)), SESSION)
    assert calls[0].excluded == "unsupported"


def test_non_kb_commands_and_other_tools_are_ignored() -> None:
    other_tool = {
        "type": "assistant",
        "timestamp": WHEN,
        "message": {"content": [{"type": "tool_use", "id": "r1", "name": "Read", "input": {}}]},
    }
    text = lines(
        bash_use("t1", "ls -la"),
        result("t1", "listing"),
        bash_use("t2", "kb sync --status"),
        result("t2", "status"),
        other_tool,
    )
    assert claude.kb_calls(text, SESSION) == ()


def test_the_record_carries_session_project_time_and_full_command() -> None:
    calls = claude.kb_calls(
        lines(bash_use("t1", "cd /x && kb evidence backup disk"), result("t1", "rows")),
        "abc",
    )
    call = calls[0]
    assert call.session_id == "abc"
    assert call.project == "/work"
    assert call.timestamp is not None
    assert call.timestamp.isoformat() == "2026-10-20T10:00:00+00:00"
    assert call.command == "cd /x && kb evidence backup disk"
    assert call.arguments == ("backup", "disk")


def test_list_content_joins_its_text_blocks() -> None:
    content = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
    calls = claude.kb_calls(
        lines(bash_use("t1", "kb gap --title t"), result("t1", content)), SESSION
    )
    assert calls[0].output == "first\nsecond"
    assert calls[0].excluded is None


def test_malformed_lines_are_skipped() -> None:
    text = "not json\n" + lines(bash_use("t1", "kb recall alpha"), result("t1", "out"))
    assert len(claude.kb_calls(text, SESSION)) == 1


def test_read_store_reads_main_and_subagent_transcripts_and_counts_unreadable(
    tmp_path: Path,
) -> None:
    project = tmp_path / "-work"
    (project / "main-1").mkdir(parents=True)
    (project / "main-1" / "subagents").mkdir()
    (project / "main-1.jsonl").write_text(
        lines(bash_use("t1", "kb recall alpha"), result("t1", "out")), encoding="utf-8"
    )
    (project / "main-1" / "subagents" / "agent-a.jsonl").write_text(
        lines(bash_use("t2", "kb read x#1"), result("t2", "read out")), encoding="utf-8"
    )
    (project / "broken.jsonl").write_bytes(b"\xff\xfe not utf-8")
    store = claude.read_store(tmp_path)
    assert store.files == 3
    assert store.unreadable == 1
    assert [call.session_id for call in store.calls] == ["main-1", "agent-a"]
    assert [call.excluded for call in store.calls] == [None, None]
    assert store.first is not None and store.last is not None
    assert store.first <= store.last


def test_a_powershell_kb_call_is_read_like_a_bash_call() -> None:
    text = lines(
        bash_use("t1", "kb recall alpha", tool="PowerShell"),
        result("t1", "the recall output"),
    )
    calls = claude.kb_calls(text, SESSION)
    assert [(call.subcommand, call.arguments, call.output) for call in calls] == [
        ("recall", ("alpha",), "the recall output")
    ]


def test_a_tool_that_is_not_a_shell_records_no_kb_call() -> None:
    text = lines(bash_use("t1", "kb recall alpha", tool="Read"), result("t1", "output"))
    assert claude.kb_calls(text, SESSION) == ()

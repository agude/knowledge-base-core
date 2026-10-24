"""Host adapters: Claude and Codex protocol translation over the session core."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.impl import REPO
from kbtest.runner import KB, Result

BOTH = {"prompt": "durable evidence", "last_assistant_message": "durable evidence"}


def _hook(kb: KB, client: str, event: str, payload: dict[str, str], **env: str | None) -> Result:
    return kb.run(f"adapters/{client}/session-{event}", stdin=json.dumps(payload) + "\n", env=env)


def _pending(kb: KB) -> list[Path]:
    return sorted((kb.layout.content / "observations" / "pending").glob("*.md"))


def _summary(kb: KB, *results: Result) -> str:
    lines = [
        f"{r.script}: exit {r.returncode} stdout={r.out!r} stderr={kb.norm_err(r.err)!r}"
        for r in results
    ]
    return kb.norm("\n".join(lines) + "\n").replace(kb.session_prefix, "<SESSION>-")


def _buffer(kb: KB, session_id: str) -> str:
    path = kb.layout.sessions / f"session-{session_id}.jsonl"
    if not path.exists():
        return "absent\n"
    return kb.norm(path.read_text(encoding="utf-8"))


@pytest.mark.bats("adapters.bats", "Claude prompt and stop report enabled buffer creation failures")
@pytest.mark.bats(
    "adapters.bats",
    "Codex prompt and stop retain protocol JSON on enabled buffer creation failures",
)
@pytest.mark.audit("A-021")
@pytest.mark.parametrize("client", ["claude", "codex"])
def test_buffer_creation_failure(kb: KB, golden: Golden, client: str) -> None:
    blocked = kb.layout.root / "blocked"
    blocked.write_text("retain this file\n", encoding="utf-8")
    results = [
        _hook(
            kb,
            client,
            event,
            {"session_id": kb.session_id(), **BOTH},
            KNOWLEDGE_OBSERVE="1",
            SESSION_DIR=str(blocked),
        )
        for event in ("prompt", "stop")
    ]
    golden.check("results", _summary(kb, *results).replace(str(blocked), "<BLOCKED>"))
    assert blocked.read_text(encoding="utf-8") == "retain this file\n"


@pytest.mark.bats(
    "adapters.bats", "repeated Claude hook delivery is retained as a duplicate record"
)
def test_claude_repeated_delivery(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    target = kb.layout.root / "claude-duplicate.jsonl"
    target.touch()
    env = {"KNOWLEDGE_SESSION_FILE": str(target)}
    payload = {
        "session_id": session_id,
        "prompt": "Repeated prompt",
        "last_assistant_message": "Repeated reply",
    }
    results = [
        _hook(kb, "claude", event, payload, **env) for event in ("prompt", "prompt", "stop", "stop")
    ]
    golden.check("results", _summary(kb, *results))
    golden.check("buffer", kb.norm(target.read_text(encoding="utf-8")))


@pytest.mark.bats("adapters.bats", "repeated Codex hook delivery is retained as a duplicate record")
def test_codex_repeated_delivery(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    payload = {
        "session_id": session_id,
        "prompt": "Repeated prompt",
        "last_assistant_message": "Repeated reply",
    }
    _hook(kb, "codex", "start", {"session_id": session_id})
    results = [_hook(kb, "codex", event, payload) for event in ("prompt", "prompt", "stop", "stop")]
    golden.check("results", _summary(kb, *results))
    golden.check("buffer", _buffer(kb, session_id))


@pytest.mark.bats(
    "adapters.bats", "Codex SessionStart returns protocol JSON and initializes capture"
)
def test_codex_session_start(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    result = _hook(kb, "codex", "start", {"session_id": session_id}, KNOWLEDGE_OBSERVE="1")
    assert result.returncode == 0
    output = json.loads(result.out)
    context = output["hookSpecificOutput"]["additionalContext"]
    output["hookSpecificOutput"]["additionalContext"] = kb.norm(
        kb.placeholder_instructions(context)
    )
    golden.check("stdout", json.dumps(output, indent=2) + "\n")
    golden.check("raw-shape", f"lines {len(result.out.splitlines())}\n")
    names = sorted(p.name.replace(session_id, "<ID>") for p in kb.layout.sessions.iterdir())
    golden.check("sessions", "\n".join(names) + "\n")


@pytest.mark.parametrize("observe", ["0"], ids=["disabled"])
def test_codex_session_start_disabled(kb: KB, golden: Golden, observe: str) -> None:
    session_id = kb.session_id()
    result = _hook(kb, "codex", "start", {"session_id": session_id}, KNOWLEDGE_OBSERVE=observe)
    assert result.returncode == 0
    assert "additionalContext" in json.loads(result.out)["hookSpecificOutput"]
    golden.check("buffer", _buffer(kb, session_id))


@pytest.mark.bats("adapters.bats", "Codex adapters capture and flush a multi-turn transcript")
@pytest.mark.bats("adapters.bats", "Codex capture is enabled when KNOWLEDGE_OBSERVE is unset")
@pytest.mark.parametrize("observe", ["1", None], ids=["enabled", "unset"])
def test_codex_multi_turn(kb: KB, golden: Golden, observe: str | None) -> None:
    session_id = kb.session_id()
    env = {"KNOWLEDGE_OBSERVE": observe}
    _hook(kb, "codex", "start", {"session_id": session_id}, **env)
    turns = [
        ("prompt", "prompt", "First"),
        ("stop", "last_assistant_message", "Answer"),
        ("prompt", "prompt", "Second"),
        ("stop", "last_assistant_message", "Reply"),
    ]
    results = [
        _hook(kb, "codex", event, {"session_id": session_id, key: text}, **env)
        for event, key, text in turns
    ]
    results.append(_hook(kb, "codex", "end", {"session_id": session_id}, **env))
    golden.check("results", _summary(kb, *results))
    golden.check("buffer", _buffer(kb, session_id))
    pending = _pending(kb)
    assert len(pending) == 1
    golden.check("observation", kb.norm(pending[0].read_text(encoding="utf-8")))
    golden.check(
        "sessions",
        "\n".join(sorted(p.name.replace(session_id, "<ID>") for p in kb.layout.sessions.iterdir()))
        + "\n",
    )


@pytest.mark.bats("adapters.bats", "Codex capture stays off when SessionStart never ran")
def test_codex_off_without_start(kb: KB) -> None:
    session_id = kb.session_id()
    env = {"KNOWLEDGE_MIN_MESSAGES": "0"}
    results = [
        _hook(kb, "codex", "prompt", {"session_id": session_id, "prompt": "First"}, **env),
        _hook(
            kb, "codex", "stop", {"session_id": session_id, "last_assistant_message": "A"}, **env
        ),
        _hook(kb, "codex", "end", {"session_id": session_id}, **env),
    ]
    # The Codex protocol requires a JSON object on stdout from every hook.
    for result in results:
        assert (result.returncode, result.out, result.err) == (0, "{}\n", "")
    assert not (kb.layout.sessions / f"session-{session_id}.jsonl").exists()
    assert _pending(kb) == []


@pytest.mark.bats(
    "adapters.bats", "Codex capture survives a swept buffer when observation is unset"
)
def test_codex_swept_buffer(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    env = {"KNOWLEDGE_MIN_MESSAGES": "0"}
    _hook(kb, "codex", "start", {"session_id": session_id}, **env)
    (kb.layout.sessions / f"session-{session_id}.jsonl").unlink()
    _hook(kb, "codex", "prompt", {"session_id": session_id, "prompt": "After sweep"}, **env)
    golden.check("buffer", _buffer(kb, session_id))
    _hook(
        kb,
        "codex",
        "stop",
        {"session_id": session_id, "last_assistant_message": "Recovered"},
        **env,
    )
    _hook(kb, "codex", "end", {"session_id": session_id}, **env)
    pending = _pending(kb)
    assert len(pending) == 1
    golden.check("observation", kb.norm(pending[0].read_text(encoding="utf-8")))


@pytest.mark.bats(
    "adapters.bats", "Codex SessionEnd clears a marker after the orphan sweep removes its buffer"
)
def test_codex_end_clears_orphaned_marker(kb: KB, golden: Golden) -> None:
    old_id = kb.session_id()
    _hook(kb, "codex", "start", {"session_id": old_id})
    old_file = kb.layout.sessions / f"session-{old_id}.jsonl"
    old_marker = kb.layout.sessions / f"session-{old_id}.initialized"
    two_hours_ago = time.time() - 7200
    os.utime(old_file, (two_hours_ago, two_hours_ago))

    _hook(kb, "codex", "start", {"session_id": kb.session_id()})
    assert not old_file.exists()
    assert old_marker.exists()

    result = _hook(kb, "codex", "end", {"session_id": old_id})
    golden.check("results", _summary(kb, result))
    assert not old_marker.exists()


@pytest.mark.bats(
    "adapters.bats", "Codex SessionEnd reports a failed flush and recovers on a later lifecycle"
)
def test_codex_failed_flush_recovers(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    env = {"KNOWLEDGE_OBSERVE": "1", "KNOWLEDGE_MIN_MESSAGES": "0"}
    _hook(kb, "codex", "start", {"session_id": session_id}, **env)
    _hook(kb, "codex", "prompt", {"session_id": session_id, "prompt": "Question"}, **env)
    _hook(
        kb, "codex", "stop", {"session_id": session_id, "last_assistant_message": "Answer"}, **env
    )
    pending_dir = kb.layout.content / "observations" / "pending"
    pending_dir.chmod(0o555)
    try:
        failed = _hook(kb, "codex", "end", {"session_id": session_id}, **env)
    finally:
        pending_dir.chmod(0o755)
    assert (kb.layout.sessions / f"session-{session_id}.jsonl").is_file()
    assert _pending(kb) == []
    recovered = _hook(kb, "codex", "end", {"session_id": session_id}, **env)
    golden.check("results", _summary(kb, failed, recovered))
    assert not (kb.layout.sessions / f"session-{session_id}.jsonl").exists()
    assert len(_pending(kb)) == 1


@pytest.mark.bats(
    "adapters.bats", "Codex SessionEnd fails inside its time budget when the lock is held"
)
def test_codex_end_time_budget(kb: KB, golden: Golden) -> None:
    session_id = kb.session_id()
    env = {"KNOWLEDGE_OBSERVE": "1", "KNOWLEDGE_MIN_MESSAGES": "0"}
    _hook(kb, "codex", "start", {"session_id": session_id}, **env)
    _hook(kb, "codex", "prompt", {"session_id": session_id, "prompt": "Question"}, **env)
    with kb.hold_lock():
        start = time.monotonic()
        blocked = _hook(kb, "codex", "end", {"session_id": session_id}, **env)
        elapsed = time.monotonic() - start
    assert elapsed < 3, elapsed
    assert (kb.layout.sessions / f"session-{session_id}.jsonl").is_file()
    assert _pending(kb) == []
    after = _hook(kb, "codex", "end", {"session_id": session_id}, **env)
    golden.check("results", _summary(kb, blocked, after))
    assert len(_pending(kb)) == 1


@pytest.mark.data
@pytest.mark.bats("adapters.bats", "portable instruction file is the canonical source")
def test_agents_md_is_canonical() -> None:
    assert (REPO / "AGENTS.md").is_file()
    assert not (REPO / "CLAUDE.md").exists()

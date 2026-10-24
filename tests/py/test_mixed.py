"""Mixed-implementation and differential tests (plan 1c.5).

During the port, Bash and Python share session buffers, markers, and the
lock. Each test runs a writer from one implementation and a reader from
another. Pairings are built from the selected implementation ("self") and
the other real one; a pairing appears only when both trees exist, so until
python/ holds the executables only self/self runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kbtest import impl as implmod
from kbtest.runner import KB

TWO_HOURS = 7200


def _pairings() -> list[object]:
    selected = implmod.selected_name()
    pairs = [("self", "self")]
    if selected in ("bash", "python"):
        other = "python" if selected == "bash" else "bash"
        if implmod.PYTHON_SCRIPTS.is_dir():
            pairs += [("self", other), (other, "self"), (other, other)]
    return [pytest.param(w, r, id=f"{w}-writes-{r}-reads") for w, r in pairs]


def _name(kb: KB, which: str) -> str:
    return kb.default_impl if which == "self" else which


def _orphan(kb: KB, writer: str) -> tuple[str, Path]:
    session_id = kb.session_id()
    impl = _name(kb, writer)
    kb.run("session-init", "--session-id", session_id, "--persist-initialization", impl=impl)
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    for role, message in (("user", b"Q1 \x7f bad\xff"), ("assistant", b"A1"), ("user", b"Q2\n\n")):
        result = kb.run(
            "session-append",
            "--file",
            str(buffer),
            "--role",
            role,
            "--message",
            "-",
            stdin=message,
            impl=impl,
        )
        assert result.returncode == 0, result.err
    then = time.time() - TWO_HOURS
    os.utime(buffer, (then, then))
    return session_id, buffer


@pytest.mark.parametrize(("writer", "reader"), _pairings())
def test_orphan_written_by_one_is_swept_by_the_other(kb: KB, writer: str, reader: str) -> None:
    _, buffer = _orphan(kb, writer)
    result = kb.run("session-init", "--session-id", kb.session_id(), impl=_name(kb, reader))
    assert result.returncode == 0, result.err
    assert not buffer.exists()
    pending = list((kb.layout.content / "observations" / "pending").glob("*.md"))
    assert len(pending) == 1
    assert "### user" in pending[0].read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize(("writer", "reader"), _pairings())
def test_jq_free_buffer_is_flushed_intact(kb: KB, without_tools, writer: str, reader: str) -> None:
    without_tools("jq")
    _, buffer = _orphan(kb, writer)
    kb.restore_tools()
    result = kb.run(
        "session-flush", str(buffer), env={"KNOWLEDGE_MIN_MESSAGES": "0"}, impl=_name(kb, reader)
    )
    assert result.returncode == 0, result.err
    (observation,) = (kb.layout.content / "observations" / "pending").glob("*.md")
    body = observation.read_bytes()
    for message in (b"Q1 \x7f bad", b"A1", b"Q2"):
        assert message in body


@pytest.mark.parametrize(("holder", "waiter"), _pairings())
def test_lock_held_by_one_blocks_the_other(kb: KB, holder: str, waiter: str) -> None:
    started = kb.layout.root / "hook-started"
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\n: > '{started}'\nsleep 20\n", encoding="utf-8")
    hook.chmod(0o755)
    tree = kb.resolve_impl(_name(kb, holder))
    process = subprocess.Popen(
        [str(kb.executable("observe", _name(kb, holder))), "--title", "Holder", "--body", "Body"],
        env=kb.env(tree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists()
        blocked = kb.run(
            "observe",
            "--title",
            "Waiter",
            "--body",
            "Body",
            env={"KNOWLEDGE_LOCK_WAIT": "1"},
            impl=_name(kb, waiter),
        )
    finally:
        process.kill()
        process.wait()
    assert blocked.returncode != 0 and blocked.err.strip()


def _approved(kb: KB, which: str, command: str) -> bool:
    tree = kb.resolve_impl(_name(kb, which))
    result = kb.run(
        "adapters/claude/pretool-allow",
        stdin=json.dumps(
            {"tool_input": {"command": command.replace("{s}", str(tree.scripts_dir))}}
        ),
        impl=_name(kb, which),
    )
    assert result.returncode == 0
    return bool(result.out.strip())


FRAGMENTS = st.sampled_from(
    [
        "{s}/status",
        "{s}/search",
        "{s}/observe",
        " ",
        "--title",
        "'a b'",
        '"c d"',
        ";",
        "&&",
        "|",
        "&",
        ">",
        "<",
        "$(id)",
        "`id`",
        "\n",
        "(",
        ")",
        "\\",
        "'",
        '"',
        "x",
        "--",
        "../",
        "/bin/sh",
    ]
)


@pytest.mark.parametrize(("first", "second"), _pairings())
def test_pretool_allow_differential(kb: KB, first: str, second: str) -> None:
    """No implementation approves a command the other rejects (fail closed)."""
    assert _approved(kb, first, "{s}/status"), "control: a bare invocation is approved"
    assert _approved(kb, second, "{s}/status"), "control: a bare invocation is approved"

    @settings(
        max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
    )
    @given(st.lists(FRAGMENTS, min_size=1, max_size=6).map("".join))
    def check(command: str) -> None:
        if _approved(kb, second, command):
            assert _approved(kb, first, command), command

    check()

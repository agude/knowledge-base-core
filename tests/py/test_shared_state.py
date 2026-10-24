"""State that Bash and Python both read and write, pinned byte for byte.

During the port and across an upgrade, a buffer, marker, or lock written by
one implementation is read by the other. These formats are contract.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB

# A message with every awkward byte: controls, DEL, invalid UTF-8, a quote,
# a backslash, non-ASCII text, and trailing newlines.
AWKWARD = bytes(range(1, 32)) + b'\x7f bad\xff end "q" \\ caf\xc3\xa9\n\n'


def _record_lock(kb: KB) -> tuple[Path, Path]:
    """Install a pre-commit hook that records the lock while observe commits."""
    seen = kb.layout.root / "lock-seen"
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        f"lock='{kb.layout.content}/.observe.lock'\n"
        f'{{ [ -d "$lock" ] && echo dir; ls -A "$lock"; cat "$lock/pid"; }} > \'{seen}\'\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return seen, hook


def test_lock_layout_while_held(kb: KB, golden: Golden) -> None:
    seen, _ = _record_lock(kb)
    result = kb.run("observe", "--title", "Locked commit", "--body", "Body")
    assert result.returncode == 0, result.err
    dir_line, entries, pid = seen.read_text(encoding="utf-8").splitlines()
    assert pid.isdigit()
    golden.contract("lock", f"{dir_line}\nentries {entries}\npid digits\n")
    assert not (kb.layout.content / ".observe.lock").exists(), "released on exit"


def test_lock_released_on_signal(kb: KB) -> None:
    started = kb.layout.root / "hook-started"
    hook = kb.layout.content / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\n: > '{started}'\nsleep 30\n", encoding="utf-8")
    hook.chmod(0o755)
    tree = kb.resolve_impl(kb.default_impl)
    process = subprocess.Popen(
        [str(tree.executable("observe")), "--title", "Interrupted", "--body", "Body"],
        env=kb.env(tree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert started.exists(), "observe never reached the commit"
        assert (kb.layout.content / ".observe.lock" / "pid").is_file()
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=30)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    assert process.returncode != 0
    assert not (kb.layout.content / ".observe.lock").exists(), "released on signal"


@pytest.mark.audit("A-002")
@pytest.mark.parametrize("configuration", ["jq", "no-jq"])
def test_buffer_bytes(kb: KB, without_tools, golden: Golden, configuration: str) -> None:
    if configuration == "no-jq":
        without_tools("jq")
    session_id = kb.session_id()
    init = kb.run("session-init", "--session-id", session_id)
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    assert init.out.strip() == str(buffer)
    for role, message in (("user", AWKWARD), ("assistant", b"plain reply")):
        result = kb.run(
            "session-append", "--file", str(buffer), "--role", role, "--message", "-", stdin=message
        )
        assert result.returncode == 0, result.err
    raw = buffer.read_bytes()
    lines = raw.split(b"\n")
    assert lines[-1] == b"" and len(lines) == 3, "one record per line, newline-terminated"
    timestamps = [line.rsplit(b'"timestamp":', 1)[1].rstrip(b"}") for line in lines[:2]]
    for stamp in timestamps:
        assert stamp.replace(b".", b"", 1).isdigit(), stamp
    canonical = (
        b"\n".join(
            line.rsplit(b'"timestamp":', 1)[0] + b'"timestamp":<EPOCH>}' for line in lines[:2]
        )
        + b"\n"
    )
    golden.contract("buffer", repr(canonical)[2:-1] + "\n")
    golden.contract(
        "modes",
        f"dir {kb.layout.sessions.stat().st_mode & 0o777:o}\nbuffer {buffer.stat().st_mode & 0o777:o}\n",
    )
    golden.contract(
        "timestamps", "".join(f"{'float' if b'.' in s else 'integer'}\n" for s in timestamps)
    )


@pytest.mark.parametrize("configuration", ["jq", "no-jq"])
def test_buffer_round_trips_through_flush(
    kb: KB, without_tools, golden: Golden, configuration: str
) -> None:
    """Whatever the encoder wrote, the flush reads back without losing the message."""
    if configuration == "no-jq":
        without_tools("jq")
    session_id = kb.session_id()
    kb.run("session-init", "--session-id", session_id)
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    for role in ("user", "assistant", "user"):
        kb.run(
            "session-append", "--file", str(buffer), "--role", role, "--message", "-", stdin=AWKWARD
        )
    if configuration == "no-jq":
        # The flush needs jq; it returns, as on a later session of the host.
        kb.restore_tools()
    result = kb.run("session-flush", str(buffer))
    golden.contract("result", f"exit {result.returncode}\n")
    pending = sorted((kb.layout.content / "observations" / "pending").glob("*.md"))
    golden.contract("observations", f"{len(pending)}\n")
    golden.contract("buffer", "kept\n" if buffer.exists() else "removed\n")
    if pending:
        body = pending[0].read_bytes().split(b"---\n", 2)[2]
        golden.contract("body", repr(body)[2:-1] + "\n")

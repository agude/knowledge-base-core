"""The setup capture switch refuses old hooks, writes the cutoff once, and enables harvesting."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from .harness import Kb

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed hook is a shell script"
)
ENABLED = "2026-10-26T12:00:00Z"


def kb_executable(kb: Kb) -> Path:
    """Create a runner shim at the path setup records in the Git hook."""
    path = kb.home / "bin" / "kb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def setup_content(kb: Kb) -> subprocess.CompletedProcess[str]:
    """Set the isolated content path and install its Git hook."""
    return kb("setup", "--content", str(kb.content), "--kb", str(kb_executable(kb)))


def enable_capture(kb: Kb) -> subprocess.CompletedProcess[str]:
    """Run setup's capture switch with the isolated kb executable."""
    return kb("setup", "--enable-capture", "--kb", str(kb_executable(kb)))


def test_enable_and_second_enable_report_the_same_cutoff(git_kb: Kb) -> None:
    prepared = setup_content(git_kb)
    assert prepared.returncode == 0, prepared.stderr

    first = enable_capture(git_kb)
    second = enable_capture(git_kb)

    assert first.returncode == 0, first.stderr
    assert first.stdout.endswith(f"Capture: enabled {ENABLED}\n")
    assert second.returncode == 0, second.stderr
    assert second.stdout.endswith(f"Capture: unchanged {ENABLED}\n")
    assert f"harvest_since = {ENABLED}" in git_kb.config_file.read_text(encoding="utf-8")


def test_sync_uses_the_enabled_cutoff_to_harvest_newer_messages_only(remote_git_kb: Kb) -> None:
    prepared = setup_content(remote_git_kb)
    assert prepared.returncode == 0, prepared.stderr
    enabled = enable_capture(remote_git_kb)
    assert enabled.returncode == 0, enabled.stderr

    install_session(remote_git_kb, "older-session", "2026-10-26T11:55:00Z")
    install_session(remote_git_kb, "newer-session", "2026-10-26T12:05:00Z")
    result = remote_git_kb("sync", env={"KB_NOW": "2026-10-26T14:00:00Z"})

    assert result.returncode == 0, result.stderr
    pending = list((remote_git_kb.content / "observations" / "pending").glob("*.md"))
    texts = [path.read_text(encoding="utf-8") for path in pending]
    assert any("newer-session" in text and "Message from newer-session" in text for text in texts)
    assert not any("older-session" in text for text in texts)


def install_session(kb: Kb, session: str, timestamp: str) -> None:
    """Write a complete Claude transcript with one user and one assistant message."""
    destination = kb.claude_config_dir / "projects" / "demo" / f"{session}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for role, message_id, content in (
        ("user", f"{session}-user", f"Message from {session}"),
        ("assistant", f"{session}-assistant", f"Reply from {session}"),
    ):
        value = content if role == "user" else [{"type": "text", "text": content}]
        records.append(
            json.dumps(
                {
                    "type": role,
                    "uuid": message_id,
                    "sessionId": session,
                    "cwd": "/fixture/project",
                    "timestamp": timestamp,
                    "message": {"role": role, "content": value},
                }
            )
        )
    destination.write_text("\n".join(records) + "\n", encoding="utf-8")
    modified = datetime.fromisoformat("2026-10-26T13:00:00+00:00").timestamp()
    os.utime(destination, (modified, modified))

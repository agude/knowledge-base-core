"""End-to-end checks of `kb doctor`: a configured machine passes, each removed fact is named, and
doctor writes nothing.

The installed hook and the Git checks are POSIX-only in these fixtures, as the hook tests are.
"""

import hashlib
import json
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

import pytest

from .harness import FIXTURE_TRANSCRIPTS, Kb, run_git

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="the installed hook and the Git checks run on POSIX here"
)
SINCE = "2026-10-24T00:00:00Z"
CHECKS = (
    "version",
    "config",
    "content",
    "gitattributes",
    "hook",
    "curation",
    "sync",
    "scheduler",
    "capture",
    "instructions",
    "allow-rules",
    "legacy",
)


def set_mtime(path: Path, timestamp: str) -> None:
    """Set a file's modification time to a fixed UTC instant."""
    moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    os.utime(path, (moment, moment))


def shim(kb: Kb) -> Path:
    path = kb.home / "bin" / "kb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m kb "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def write_config(kb: Kb, harvest: bool = True) -> None:
    kb.config_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'content = "{kb.content.as_posix()}"']
    if harvest:
        lines.append(f"harvest_since = {SINCE}")
    kb.config_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def systemctl(kb: Kb, enabled: str = "enabled", active: str = "active") -> dict[str, str | None]:
    """A fake systemctl first on PATH, answering the two questions that doctor asks."""
    directory = kb.home / "bin"
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / "systemctl"
    tool.write_text(
        f'#!/bin/sh\ncase "$2" in\n  is-enabled) echo {enabled} ;;\n  is-active) echo {active} ;;\nesac\n',
        encoding="utf-8",
    )
    tool.chmod(0o755)
    return {"PATH": f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"}


def configured(kb: Kb) -> dict[str, str | None]:
    """Make a fixture repository a fully configured machine, and return the doctor environment."""
    write_config(kb)
    (kb.content / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
    run_git(kb.content, "add", ".gitattributes")
    run_git(kb.content, "commit", "-q", "-m", "Add attributes")
    run_git(kb.content, "push", "-q", "origin", "main")
    assert kb("setup", "--content", str(kb.content), "--kb", str(shim(kb))).returncode == 0
    assert kb("sync").returncode == 0
    instructions = kb("setup", "--print", "instructions").stdout
    (kb.claude_config_dir / "CLAUDE.md").write_text(instructions, encoding="utf-8")
    (kb.codex_home / "AGENTS.md").write_text(instructions, encoding="utf-8")
    (kb.claude_config_dir / "settings.json").write_text(
        kb("setup", "--print", "allow-claude").stdout, encoding="utf-8"
    )
    (kb.codex_home / "rules").mkdir(parents=True)
    (kb.codex_home / "rules" / "kb.rules").write_text(
        kb("setup", "--print", "allow-codex").stdout, encoding="utf-8"
    )
    return systemctl(kb)


def doctor(kb: Kb, env: Mapping[str, str | None]) -> tuple[int, list[str]]:
    result = kb("doctor", env=env)
    return result.returncode, result.stdout.splitlines()


def digests(root: Path) -> dict[str, str]:
    """A SHA-256 for every file under root, including Git's metadata."""
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def test_a_configured_machine_passes_every_check(remote_git_kb: Kb) -> None:
    env = configured(remote_git_kb)

    code, lines = doctor(remote_git_kb, env)

    assert code == 0, lines
    assert [line.split(":", 1)[0] for line in lines] == [f"PASS {name}" for name in CHECKS]


def test_a_doctor_run_leaves_every_file_and_the_index_unchanged(remote_git_kb: Kb) -> None:
    env = configured(remote_git_kb)
    before = digests(remote_git_kb.home) | digests(remote_git_kb.content)

    doctor(remote_git_kb, env)

    assert (digests(remote_git_kb.home) | digests(remote_git_kb.content)) == before
    assert not (remote_git_kb.content / ".git" / "index.lock").exists()


def _no_config(kb: Kb) -> dict[str, str | None]:
    kb.config_file.unlink()
    return {"KB_CONTENT": None}


def _no_hook(kb: Kb) -> dict[str, str | None]:
    (kb.content / ".git" / "hooks" / "pre-commit").unlink()
    return {}


def _no_record(kb: Kb) -> dict[str, str | None]:
    (kb.content / ".git" / "kb" / "sync-state.json").unlink()
    return {}


def _attributes(kb: Kb) -> dict[str, str | None]:
    (kb.content / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    return {}


def _no_origin(kb: Kb) -> dict[str, str | None]:
    run_git(kb.content, "remote", "remove", "origin")
    return {}


def _dirty(kb: Kb) -> dict[str, str | None]:
    (kb.content / "scratch.txt").write_text("local\n", encoding="utf-8")
    return {}


def _old_hook_link(kb: Kb) -> dict[str, str | None]:
    hook = kb.content / ".git" / "hooks" / "pre-commit"
    old = kb.home / "Knowledge" / "scripts" / "hooks" / "pre-commit"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("#!/bin/sh\n", encoding="utf-8")
    hook.unlink()
    hook.symlink_to(old)
    return {}


def _timer_off(kb: Kb) -> dict[str, str | None]:
    return systemctl(kb, enabled="disabled", active="inactive")


def _capture_off(kb: Kb) -> dict[str, str | None]:
    write_config(kb, harvest=False)
    return {}


def _instructions_missing(kb: Kb) -> dict[str, str | None]:
    (kb.claude_config_dir / "CLAUDE.md").write_text("Other notes.\n", encoding="utf-8")
    return {}


def _allow_missing(kb: Kb) -> dict[str, str | None]:
    (kb.claude_config_dir / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(kb recall *)"]}}), encoding="utf-8"
    )
    return {}


def _allow_broader(kb: Kb) -> dict[str, str | None]:
    settings = json.loads((kb.claude_config_dir / "settings.json").read_text(encoding="utf-8"))
    settings["permissions"]["allow"].append("Bash(kb *)")
    (kb.claude_config_dir / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    return {}


def _sync_failed(kb: Kb) -> dict[str, str | None]:
    record = kb.content / ".git" / "kb" / "sync-state.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data.update(last_outcome="error", message="sync: push origin/main failed: rejected")
    record.write_text(json.dumps(data), encoding="utf-8")
    return {}


def _legacy_link(kb: Kb) -> dict[str, str | None]:
    hooks = kb.home / "xdg" / "coat-tree" / "hooks.d" / "Stop"
    hooks.mkdir(parents=True)
    (hooks / "010.knowledge.sh").symlink_to(kb.home / "legacy-hook.sh")
    return {}


def _old_transcript(kb: Kb) -> dict[str, str | None]:
    destination = kb.claude_config_dir / "projects" / "demo" / "main.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        FIXTURE_TRANSCRIPTS / "claude" / "projects" / "demo" / "main.jsonl", destination
    )
    set_mtime(destination, "2026-09-01T00:00:00Z")
    return {}


Mutation = Callable[[Kb], dict[str, str | None]]
REMOVALS: list[tuple[str, Mutation, str, int]] = [
    ("no content setting", _no_config, "FAIL config: knowledge base: no content repository", 1),
    ("hook absent", _no_hook, "FAIL hook: absent", 1),
    ("no sync record", _no_record, "FAIL sync: No record", 1),
    ("attributes differ", _attributes, "WARN gitattributes: text=auto, eol=unspecified", 0),
    ("no origin", _no_origin, "FAIL content: no origin remote", 1),
    ("worktree dirty", _dirty, "WARN content: 1 changed path(s) in the worktree", 0),
    ("old hook link", _old_hook_link, "WARN hook: a symbolic link to the old tooling's hook", 0),
    ("timer disabled", _timer_off, "WARN scheduler: kb-sync.timer is disabled and inactive", 0),
    ("capture off", _capture_off, "WARN capture: Capture disabled (harvest_since unset)", 0),
    ("no instruction block", _instructions_missing, "WARN instructions: claude: no kb block", 0),
    (
        "allow rules missing",
        _allow_missing,
        "WARN allow-rules: claude: missing Bash(kb evidence *)",
        0,
    ),
    ("broader allow rule", _allow_broader, "broader Bash(kb *)", 0),
    (
        "last sync failed",
        _sync_failed,
        "WARN sync: last run ended error: sync: push origin/main",
        0,
    ),
    ("legacy coat-tree link", _legacy_link, "coat-tree Stop/010.knowledge.sh", 0),
    (
        "ready transcript older than 20 days",
        _old_transcript,
        "1 ready transcript(s) older than 20 days",
        0,
    ),
]


@pytest.mark.parametrize(
    ("label", "mutate", "expected", "code"), REMOVALS, ids=[r[0] for r in REMOVALS]
)
def test_each_removed_fact_is_named_with_its_fix_and_the_right_exit_status(
    remote_git_kb: Kb,
    label: str,
    mutate: Mutation,
    expected: str,
    code: int,
) -> None:
    env: dict[str, str | None] = dict(configured(remote_git_kb))
    env.update(mutate(remote_git_kb))

    result = remote_git_kb("doctor", env=env)

    assert result.returncode == code, (label, result.stdout)
    lines = result.stdout.splitlines()
    named = [index for index, line in enumerate(lines) if expected in line]
    assert named, (label, result.stdout)
    assert lines[named[0] + 1].startswith("  fix: "), (label, result.stdout)


def test_a_ready_transcript_is_counted_with_the_retention_it_is_facing(remote_git_kb: Kb) -> None:
    env = configured(remote_git_kb)
    _old_transcript(remote_git_kb)

    result = remote_git_kb("doctor", env=env)

    assert result.returncode == 0, result.stdout
    assert (
        "WARN capture: 1 ready transcript(s) older than 20 days; Claude Code keeps transcripts "
        "for 30 days (default); Codex retention is unknown"
    ) in result.stdout

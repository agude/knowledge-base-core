"""Find legacy capture registrations in the host hook stores."""

import json
import re
from pathlib import Path

from kb.errors import KbError

CAPTURE_EVENTS = frozenset({"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"})


def coat_tree_findings(config_home: Path, *, capture_only: bool = False) -> list[str]:
    """Name old coat-tree entries, optionally limited to transcript capture events."""
    hooks = config_home / "coat-tree" / "hooks.d"
    findings = []
    for entry in sorted(hooks.glob("*/010.knowledge*")):
        if capture_only and entry.parent.name not in CAPTURE_EVENTS:
            continue
        target = str(entry.readlink()) if entry.is_symlink() else "a regular file"
        findings.append(f"coat-tree {entry.parent.name}/{entry.name} -> {target}")
    return findings


def codex_hook_findings(hooks_file: Path) -> list[str]:
    """Name Codex hook scripts whose text identifies them as knowledge-base shims."""
    data = _json_object(hooks_file)
    findings = []
    for event, command in hook_commands(data.get("hooks", {})):
        words = command.split()
        script = Path(words[-1]).expanduser() if words else None
        if script is not None and script.is_file():
            text = script.read_text(encoding="utf-8", errors="replace")
            if re.search("knowledge", text, re.IGNORECASE):
                findings.append(f"Codex {event} hook: {command}")
    return findings


def capture_findings(config_home: Path, codex_home: Path) -> list[str]:
    """Name only the old coat-tree and Codex registrations that capture transcripts."""
    return [
        *coat_tree_findings(config_home, capture_only=True),
        *codex_hook_findings(codex_home / "hooks.json"),
    ]


def hook_commands(hooks: object) -> list[tuple[str, str]]:
    """Each (event, command) pair in a host hook mapping, tolerating unexpected shapes."""
    pairs: list[tuple[str, str]] = []
    if not isinstance(hooks, dict):
        return pairs
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            for hook in group.get("hooks", []) if isinstance(group, dict) else []:
                command = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(command, str):
                    pairs.append((str(event), command))
    return pairs


def _json_object(path: Path) -> dict[str, object]:
    """A JSON object from a file, or an empty object when the file is absent."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise KbError(f"cannot read {path}: {error}") from error
    return data if isinstance(data, dict) else {}

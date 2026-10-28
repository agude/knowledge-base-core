"""Legacy capture registrations are limited to the installed lifecycle hooks."""

import json
import sys
from pathlib import Path

import pytest

from kb import registrations

SKIP_LINKS = pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need privilege")


@SKIP_LINKS
def test_capture_findings_include_lifecycle_links_but_not_pretooluse(tmp_path: Path) -> None:
    config_home = tmp_path / "config"
    hooks = config_home / "coat-tree" / "hooks.d"
    target = tmp_path / "old-hook"
    target.write_text("old hook\n", encoding="utf-8")
    for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd", "PreToolUse"):
        directory = hooks / event
        directory.mkdir(parents=True)
        (directory / "010.knowledge").symlink_to(target)

    findings = registrations.capture_findings(config_home, tmp_path / "codex")

    assert findings == [
        f"coat-tree {event}/010.knowledge -> {target}"
        for event in ("SessionEnd", "SessionStart", "Stop", "UserPromptSubmit")
    ]


def test_capture_findings_include_codex_hooks_that_call_knowledge_shims(tmp_path: Path) -> None:
    script = tmp_path / "knowledge-shim.sh"
    script.write_text("#!/bin/sh\nexec knowledge capture\n", encoding="utf-8")
    hooks = tmp_path / "codex" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": f"bash {script}"}]}]}}),
        encoding="utf-8",
    )

    assert registrations.capture_findings(tmp_path / "config", hooks.parent) == [
        f"Codex SessionStart hook: bash {script}"
    ]

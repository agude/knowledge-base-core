"""install: legacy hook migration, skill links, and the content-repo hook."""

from __future__ import annotations

import os

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB

LEGACY = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "session-prompt",
    "Stop": "session-stop",
    "SessionEnd": "session-end",
    "PreToolUse": "pretool-allow",
}


def _links(kb: KB) -> str:
    """List every symlink install manages, with its target, normalized."""
    roots = [
        kb.layout.config / "coat-tree" / "hooks.d",
        kb.layout.home / ".agents" / "skills",
        kb.layout.content / ".git" / "hooks",
    ]
    lines = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                # Path.readlink() drops a trailing slash, which A-007 pins.
                target = os.readlink(path)  # noqa: PTH115
                lines.append(f"{path} -> {target}")
    return kb.norm("\n".join(lines) + "\n")


@pytest.mark.bats("install.bats", "install migrates legacy Claude hooks to adapters")
def test_install_migrates_legacy_claude_hooks(kb: KB, golden: Golden) -> None:
    tree = kb.resolve_impl(kb.default_impl)
    hooks = kb.layout.config / "coat-tree" / "hooks.d"
    for event, script in LEGACY.items():
        (hooks / event).mkdir(parents=True)
        (hooks / event / "010.knowledge").symlink_to(tree.scripts_dir / script)

    result = kb.run("install")

    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    golden.check("links", _links(kb))


@pytest.mark.audit("A-007")
def test_install_fresh(kb: KB, golden: Golden) -> None:
    result = kb.run("install")
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))
    golden.check("stderr", kb.norm_err(result.err))
    golden.check("links", _links(kb))


@pytest.mark.audit("A-006")
def test_install_is_idempotent(kb: KB, golden: Golden) -> None:
    kb.run("install")
    result = kb.run("install")
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))
    golden.check("links", _links(kb))


def test_install_leaves_unrelated_hooks(kb: KB, golden: Golden) -> None:
    hooks = kb.layout.config / "coat-tree" / "hooks.d" / "SessionStart"
    hooks.mkdir(parents=True)
    (hooks / "010.knowledge").symlink_to("/elsewhere/session-start")
    (hooks / "020.other").symlink_to("/elsewhere/other")

    result = kb.run("install")

    assert result.returncode == 0
    golden.check("links", _links(kb))


def test_install_without_knowledge_base_prints_reminder(kb: KB, golden: Golden) -> None:
    result = kb.run("install", env={"KNOWLEDGE_BASE": None})
    assert result.returncode == 0
    golden.check("stdout", kb.norm(result.out))

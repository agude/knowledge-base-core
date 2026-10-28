"""The host text that the dotfiles install: the instruction block and the allow rules.

These are pure functions. `kb setup --print` writes them to stdout, and doctor compares the
installed copies with them.
"""

import json
from importlib import resources
from pathlib import Path

from kb.errors import KbError

BEGIN_MARKER = "<!-- kb:begin -->"
END_MARKER = "<!-- kb:end -->"
POLICY_PLACEHOLDER = "{content_policy}"
MAX_BLOCK_LINES = 12
WORKING_COMMANDS = ("recall", "read", "map", "questions", "evidence", "observe", "gap")
ITEMS = ("instructions", "allow-claude", "allow-codex")
CODEX_RULES_HEADER = "# kb working-agent commands. Install under $CODEX_HOME/rules/."


def instruction_block(content_root: str) -> str:
    """The canonical block, with its content policy line rendered from content_root."""
    template = resources.files("kb").joinpath("data/instructions.md").read_text(encoding="utf-8")
    return template.replace(POLICY_PLACEHOLDER, policy_import(content_root))


def policy_import(content_root: str) -> str:
    """An import of the content AGENTS.md, which Claude Code loads and other hosts read as a path.

    Claude Code takes a backslash before each space in an import path, so spaces are escaped.
    """
    if any(character in content_root for character in "\r\n\0"):
        raise KbError("setup: the content path must not contain a line break or NUL")
    policy = Path(content_root).joinpath("AGENTS.md").as_posix()
    return "@" + policy.replace(" ", "\\ ")


def allow_claude() -> str:
    """The Claude Code settings fragment that allows the working-agent commands."""
    rules = [f"Bash(kb {command} *)" for command in WORKING_COMMANDS]
    return json.dumps({"permissions": {"allow": rules}}, indent=2) + "\n"


def allow_codex() -> str:
    """The Codex rules file that allows the working-agent commands."""
    lines = [CODEX_RULES_HEADER]
    lines.extend(
        f'prefix_rule(pattern = ["kb", "{command}"], decision = "allow")'
        for command in WORKING_COMMANDS
    )
    return "\n".join(lines) + "\n"

"""The host text that the dotfiles install, and the edits that setup makes to its targets.

These are pure functions. `kb setup --print` writes the text to stdout, doctor compares the
installed copies with it, and setup applies the edits to the config file and the hook. Skill
package data and installation are handled by kb.skills.
"""

import json
import re
import tomllib
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from kb.errors import KbError

BEGIN_MARKER = "<!-- kb:begin -->"
END_MARKER = "<!-- kb:end -->"
POLICY_PLACEHOLDER = "{content_policy}"
MAX_BLOCK_LINES = 12
WORKING_COMMANDS = ("recall", "read", "map", "questions", "evidence", "observe", "gap")
ITEMS = ("instructions", "allow-claude", "allow-codex")
CODEX_RULES_HEADER = (
    "# kb working-agent commands. Install as a regular file under $CODEX_HOME/rules/;"
    " Codex skips symbolic links."
)
HOOK_MARKER = "# Installed by kb setup. Do not edit; run kb setup again to update."
OLD_HOOK_SUFFIX = ("scripts", "hooks", "pre-commit")
UNQUOTABLE = ("'", "\r", "\n", "\0")
VERSION_OUTPUT = re.compile(r"kb [0-9][0-9A-Za-z.+-]*\n?")
CONTENT_LINE = re.compile(r'[ \t]*content[ \t]*=[ \t]*"(?:[^"\\\r\n]|\\.)*"[ \t]*(?:#[^\r\n]*)?')
TABLE_HEADER = re.compile(r"[ \t]*\[")


class HookAction(Enum):
    """What setup does with the hook path, by the table in section 5.2 of the plan."""

    INSTALL = "install"
    UNCHANGED = "unchanged"
    UPDATE = "update"
    REPLACE_OLD_LINK = "replace-old-link"
    REFUSE_OLD_LINK = "refuse-old-link"
    REFUSE_FOREIGN = "refuse-foreign"


@dataclass(frozen=True)
class ExistingHook:
    """What occupies the hook path: nothing, a symbolic link, a regular file, or another kind."""

    kind: Literal["absent", "link", "file", "other"]
    link_target: str = ""
    data: bytes = b""


def instruction_block(content_root: str) -> str:
    """The canonical block, with its content policy line rendered from content_root."""
    template = resources.files("kb").joinpath("data/instructions.md").read_text(encoding="utf-8")
    return template.replace(POLICY_PLACEHOLDER, policy_import(content_root))


def policy_import(content_root: str) -> str:
    """An import of the content AGENTS.md, which Claude Code loads and other hosts read as a path.

    Claude Code takes a backslash before each space in an import path, so spaces are escaped.
    """
    if any(character in content_root for character in "\r\n\0"):
        raise KbError("the content path must not contain a line break or NUL")
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


def check_hook_path(kb_path: str) -> None:
    """Refuse a kb path that the hook script cannot quote."""
    if any(character in kb_path for character in UNQUOTABLE):
        raise KbError("the kb path must not contain a single quote, a line break, or NUL")


def version_line_ok(output: str) -> bool:
    """Whether a kb executable's --version output is `kb` followed by a version."""
    return VERSION_OUTPUT.fullmatch(output) is not None


def hook_script(kb_path: str) -> str:
    """The pre-commit script that calls kb by its absolute path."""
    check_hook_path(kb_path)
    return f"#!/bin/sh\n{HOOK_MARKER}\nexec '{kb_path}' hook pre-commit \"$@\"\n"


def is_old_hook_target(target: str) -> bool:
    """Whether a symbolic link's target is the old tooling's pre-commit hook."""
    return Path(target).parts[-3:] == OLD_HOOK_SUFFIX


def is_managed(data: bytes) -> bool:
    """Whether a hook file was installed by kb setup: its second line is the marker."""
    lines = data.decode("utf-8", errors="replace").splitlines()
    return len(lines) >= 2 and lines[1] == HOOK_MARKER


def hook_action(existing: ExistingHook, script: str, replace_old: bool) -> HookAction:
    """The action for the hook path, given what occupies it and the wanted script."""
    if existing.kind == "absent":
        return HookAction.INSTALL
    if existing.kind == "link":
        if not is_old_hook_target(existing.link_target):
            return HookAction.REFUSE_FOREIGN
        return HookAction.REPLACE_OLD_LINK if replace_old else HookAction.REFUSE_OLD_LINK
    if existing.kind == "file" and is_managed(existing.data):
        same = existing.data == script.encode("utf-8")
        return HookAction.UNCHANGED if same else HookAction.UPDATE
    return HookAction.REFUSE_FOREIGN


def toml_string(value: str) -> str:
    """A TOML basic string for value, with backslashes and quotes escaped."""
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise KbError("the content path must not contain a control character")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_content(text: str, value: str) -> str:
    """The config text with its top-level content key set to value, and no other byte changed.

    The old and new text must parse as TOML, and they must differ only in the content key.
    Raises KbError for text that cannot be edited that way.
    """
    before = _parse(text)
    lines = text.splitlines(keepends=True)
    assignment = f"content = {toml_string(value)}"
    first_table = next(
        (
            index
            for index, line in enumerate(lines)
            if TABLE_HEADER.match(line.removeprefix("\ufeff"))
        ),
        len(lines),
    )
    index = _top_level_content_line(lines, first_table)
    if index is not None:
        line = lines[index]
        body = line.rstrip("\r\n")
        bom = "\ufeff" if body.startswith("\ufeff") else ""
        lines[index] = bom + assignment + line[len(body) :]
    else:
        if "content" in before:
            raise KbError("the content key must be a single-line basic string")
        newline = "\r\n" if "\r\n" in text else "\n"
        if first_table == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        line = assignment + newline
        if first_table == 0 and lines and lines[0].startswith("\ufeff"):
            lines[0] = lines[0].removeprefix("\ufeff")
            line = "\ufeff" + line
        lines.insert(first_table, line)
    result = "".join(lines)
    _verify(before, _parse(result), value)
    return result


def _top_level_content_line(lines: list[str], limit: int) -> int | None:
    """The index of a single-line content assignment before the first table header, if any."""
    for index in range(limit):
        candidate = lines[index].removeprefix("\ufeff")
        if CONTENT_LINE.fullmatch(candidate.rstrip("\r\n")):
            return index
    return None


def _parse(text: str) -> dict[str, Any]:
    """The config text as TOML data, or KbError."""
    try:
        return tomllib.loads(text.removeprefix("\ufeff"))
    except tomllib.TOMLDecodeError as error:
        raise KbError(f"the file is not valid TOML: {error}") from None


def _verify(before: dict[str, Any], after: dict[str, Any], value: str) -> None:
    """Require the edit to set the content key and to change nothing else."""
    if after.get("content") != value:
        raise KbError("the content key did not take the new value")
    if _other_keys(before) != _other_keys(after):
        raise KbError("the edit would change keys other than content")


def _other_keys(data: dict[str, Any]) -> dict[str, Any]:
    """The top-level keys other than content."""
    return {key: value for key, value in data.items() if key != "content"}

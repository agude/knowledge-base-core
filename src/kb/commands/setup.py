"""kb setup: print the host text that the dotfiles install. Later steps add the setup forms."""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from kb import args, config, setup_rules
from kb.args import Spec
from kb.errors import KbError
from kb.platform import config_file

SPEC = Spec(
    usage="setup --print {instructions|allow-claude|allow-codex}",
    summary=(
        "Print the instruction block or the allow rules that the dotfiles install. Writes nothing."
    ),
    valued=frozenset({"--print"}),
)


def run(words: Sequence[str]) -> int:
    """Print the item that --print names, and return the exit status."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    item = parsed.values.get("--print")
    if item is None or parsed.words:
        raise SPEC.usage_error()
    sys.stdout.write(_render(item, os.environ))
    return 0


def _render(item: str, environ: Mapping[str, str]) -> str:
    """The text for one --print item."""
    if item == "instructions":
        return setup_rules.instruction_block(_content_root(environ))
    if item == "allow-claude":
        return setup_rules.allow_claude()
    if item == "allow-codex":
        return setup_rules.allow_codex()
    raise KbError(f"setup: --print takes {', '.join(setup_rules.ITEMS)}; not {item}")


def _content_root(environ: Mapping[str, str]) -> str:
    """The configured content path as an absolute path. The directory need not exist."""
    override = environ.get("KB_CONTENT", "")
    if override:
        return str(Path(override).expanduser().absolute())
    configured = config.read_content_setting(config_file(environ, sys.platform, Path.home()))
    if configured is None:
        raise KbError(
            'setup: no content path; set KB_CONTENT or add content = "PATH" to the config file'
        )
    return str(configured.absolute())

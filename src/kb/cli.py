"""Command-line entry point: the global options, dispatch by command word, and usage errors."""

import sys
from collections.abc import Sequence

from kb import __version__, registry
from kb.args import HELP_FLAGS
from kb.errors import KbError


def top_help() -> str:
    """The help that `kb` prints with no command, listing each registered command."""
    lines = ["Usage: kb COMMAND [ARGS...]", "", "Read and search the knowledge base.", ""]
    if registry.COMMANDS:
        width = max(len(command.name) for command in registry.COMMANDS)
        lines.append("Commands:")
        lines.extend(
            f"  {command.name.ljust(width)}  {command.summary}" for command in registry.COMMANDS
        )
        lines.append("")
    lines.append("Run `kb COMMAND --help` for one command's options.")
    return "\n".join(lines) + "\n"


def run(args: Sequence[str]) -> int:
    """Run the command that args name, or print the help or the version.

    Raises KbError for an unknown command or option.
    """
    if not args or args[0] in HELP_FLAGS:
        sys.stdout.write(top_help())
        return 0
    if args[0] == "--version":
        sys.stdout.write(f"kb {__version__}\n")
        return 0
    if args[0].startswith("-"):
        raise KbError(f"Unknown option: {args[0]}")
    return registry.find(args[0]).run(args[1:])


def main(argv: Sequence[str] | None = None) -> int:
    """Run kb on argv, or on sys.argv[1:] when argv is None, and return the exit status."""
    words = sys.argv[1:] if argv is None else argv
    try:
        return run(words)
    except KbError as error:
        sys.stderr.write(f"{error}\n")
        return 1

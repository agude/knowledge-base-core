"""The agent-facing commands: each one's name, one-line summary, and entry point."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kb.errors import KbError


@dataclass(frozen=True)
class Command:
    """One command word. run takes the words after it and returns the exit status."""

    name: str
    summary: str
    run: Callable[[Sequence[str]], int]


COMMANDS: tuple[Command, ...] = ()


def find(name: str) -> Command:
    """The command registered under name, or KbError."""
    for command in COMMANDS:
        if command.name == name:
            return command
    raise KbError(f"Unknown command: {name}")

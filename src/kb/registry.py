"""The agent-facing commands: each one's name, one-line summary, and entry point."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kb.commands import map as map_command
from kb.commands import read as read_command
from kb.errors import KbError


@dataclass(frozen=True)
class Command:
    """One command word. run takes the words after it and returns the exit status."""

    name: str
    summary: str
    run: Callable[[Sequence[str]], int]


COMMANDS: tuple[Command, ...] = (
    Command(name="read", summary="Print the text that LOCATORs name.", run=read_command.run),
    Command(name="map", summary="List articles and their sections.", run=map_command.run),
)


def find(name: str) -> Command:
    """The command registered under name, or KbError."""
    for command in COMMANDS:
        if command.name == name:
            return command
    raise KbError(f"Unknown command: {name}")

"""The agent-facing commands: each one's name, one-line summary, and entry point."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from kb.commands import curate as curate_command
from kb.commands import evidence as evidence_command
from kb.commands import gap as gap_command
from kb.commands import lint as lint_command
from kb.commands import map as map_command
from kb.commands import observe as observe_command
from kb.commands import questions as questions_command
from kb.commands import read as read_command
from kb.commands import recall as recall_command
from kb.commands import resolve as resolve_command
from kb.commands import sync as sync_command
from kb.commands import verify as verify_command
from kb.errors import KbError


@dataclass(frozen=True)
class Command:
    """One command word. run takes the words after it and returns the exit status."""

    name: str
    summary: str
    run: Callable[[Sequence[str]], int]


COMMANDS: tuple[Command, ...] = (
    Command(
        name="recall",
        summary="Find curated sections that answer a query.",
        run=recall_command.run,
    ),
    Command(name="read", summary="Print the text that LOCATORs name.", run=read_command.run),
    Command(name="map", summary="List articles and their sections.", run=map_command.run),
    Command(
        name="lint",
        summary="Check article structure and metadata.",
        run=lint_command.run,
    ),
    Command(
        name="observe",
        summary="Record one observation and commit it.",
        run=observe_command.run,
    ),
    Command(
        name="gap",
        summary="Record one attributed question and commit it.",
        run=gap_command.run,
    ),
    Command(
        name="verify",
        summary="Set an article's verified date and a required TTL.",
        run=verify_command.run,
    ),
    Command(
        name="resolve",
        summary="Resolve an open question to a curated answer or mark it obsolete.",
        run=resolve_command.run,
    ),
    Command(
        name="curate",
        summary="Select and track local curation batches.",
        run=curate_command.run,
    ),
    Command(
        name="questions",
        summary="List open questions by context.",
        run=questions_command.run,
    ),
    Command(
        name="sync",
        summary="Harvest transcripts and sync the content repository.",
        run=sync_command.run,
    ),
    Command(
        name="evidence",
        summary="Search observations, transcripts, and questions by text, kind, and date.",
        run=evidence_command.run,
    ),
)


def find(name: str) -> Command:
    """The command registered under name, or KbError."""
    for command in COMMANDS:
        if command.name == name:
            return command
    raise KbError(f"Unknown command: {name}")

"""Find the recorded kb calls in one shell command line. Text only: no file or store I/O.

A kb call is a simple command whose program is named kb and whose subcommand is one of
RECORDED. Commands are separated by ;, &&, ||, |, &, and newlines. A redirection is dropped
with its target. Text inside $(...), backticks, or a nested shell string is not split, so a
kb call there is not found.
"""

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

RECORDED = ("recall", "read", "evidence", "gap", "observe")
OPERATORS = frozenset({";", ";;", "&&", "||", "|", "|&", "&"})
REDIRECTS = frozenset({">", ">>", ">|", "<", "<<", "<<<", "<&", ">&", "&>", "&>>"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


@dataclass(frozen=True)
class Invocation:
    """One recorded kb call: its subcommand and the words after it."""

    subcommand: str
    arguments: tuple[str, ...]


def invocations(command: str) -> tuple[Invocation, ...]:
    """The recorded kb calls in a command line, in order. Unbalanced quotes give none."""
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return ()
    found: list[Invocation] = []
    for words in _segments(tokens):
        invocation = _invocation(words)
        if invocation is not None:
            found.append(invocation)
    return tuple(found)


def _segments(tokens: list[str]) -> list[list[str]]:
    """The words of each simple command. A redirection and its target are dropped."""
    segments: list[list[str]] = [[]]
    skip_target = False
    for token in tokens:
        if token in OPERATORS:
            segments.append([])
            skip_target = False
        elif skip_target:
            skip_target = False
        elif token in REDIRECTS:
            if segments[-1] and segments[-1][-1].isdigit():
                segments[-1].pop()
            skip_target = True
        else:
            segments[-1].append(token)
    return segments


def _invocation(words: list[str]) -> Invocation | None:
    """The recorded kb call of one simple command, or None."""
    start = 0
    while start < len(words) and ASSIGNMENT.match(words[start]):
        start += 1
    words = words[start:]
    if len(words) < 2 or _program(words[0]) != "kb" or words[1] not in RECORDED:
        return None
    return Invocation(words[1], tuple(words[2:]))


def _program(word: str) -> str:
    """The program name of a command word, with any directory removed."""
    return PureWindowsPath(PurePosixPath(word).name).name

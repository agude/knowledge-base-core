"""Find the recorded kb calls in one shell command line. Text only: no file or store I/O.

A kb call is a simple command whose program is named kb and whose subcommand is one of
RECORDED. Commands are separated by ;, &&, ||, |, &, and newlines. A redirection is dropped
with its target. Text inside $(...), backticks, or a nested shell string is not split, so a
kb call there is not found.

The line is lexed without posix quoting, so a quoted operator stays a word, and a quoted newline
stays in its argument. A backslash escape is read as the character it escapes. Each word is
unquoted afterwards. A line that does not lex or unquote gives no calls.
"""

import re
import shlex
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

RECORDED = ("recall", "read", "evidence", "gap", "observe")
OPERATORS = frozenset({";", ";;", "&&", "||", "|", "|&", "&", "\n"})
SEPARATOR_CHARACTERS = frozenset(";&|\n")
REDIRECTS = frozenset({">", ">>", ">|", "<", "<<", "<<<", "<&", ">&", "&>", "&>>"})
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
BLANK = " \t\r"
# A backslash escapes one of these characters outside single quotes. Inside double quotes, only
# a quote and a backslash are escaped. Shlex in non-posix mode reads no escapes, so each escape is
# lexed as one character from the private-use range. The character is restored before unquoting.
ESCAPABLE = "\"'\\ \t;&|()<>\n"
ESCAPE_CODES = {char: chr(0xE000 + index) for index, char in enumerate(ESCAPABLE)}
ESCAPE_CHARS = {code: "\\" + char for char, code in ESCAPE_CODES.items()}


@dataclass(frozen=True)
class Invocation:
    """One recorded kb call: its subcommand and the words after it."""

    subcommand: str
    arguments: tuple[str, ...]


def invocations(command: str) -> tuple[Invocation, ...]:
    """The recorded kb calls in a command line, in order. A line that does not lex gives none."""
    segments = _segments(command)
    if segments is None:
        return ()
    found: list[Invocation] = []
    for words in segments:
        invocation = _invocation(words)
        if invocation is not None:
            found.append(invocation)
    return tuple(found)


def sole_invocation(command: str) -> Invocation | None:
    """The recorded kb call, when the whole line is exactly one simple command that is one.

    Assignments and redirections of that command are allowed. A second command, a pipeline, or
    a list (;, &&, ||, |, &, or a newline between commands) gives None.
    """
    segments = _segments(command)
    if segments is None:
        return None
    filled = [words for words in segments if words]
    if len(filled) != 1:
        return None
    return _invocation(filled[0])


def _segments(command: str) -> list[list[str]] | None:
    """The unquoted words of each simple command, or None when the line does not lex or unquote.

    A redirection and its target are dropped. Each separator starts a new segment.
    """
    raw = _raw_segments(command)
    if raw is None:
        return None
    segments: list[list[str]] = []
    for words in raw:
        values: list[str] = []
        for word in words:
            try:
                unquoted = shlex.split(
                    "".join(ESCAPE_CHARS.get(char, char) for char in word), posix=True
                )
            except ValueError:
                return None
            if len(unquoted) != 1:
                return None
            values.append(unquoted[0])
        segments.append(values)
    return segments


def _raw_segments(command: str) -> list[list[str]] | None:
    """The still-quoted words of each simple command, or None when the line does not lex.

    Adjacent word pieces are joined back into one word, because shlex splits a word at each
    closing quote. A piece is joined to the one before it when no blank separates them.
    """
    masked = _mask_escapes(command)
    lexer = shlex.shlex(masked, posix=False, punctuation_chars=";&|()<>\n")
    lexer.whitespace = BLANK
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    position = 0
    skip_target = False
    previous_is_word = False
    for token in tokens:
        start = position
        while start < len(masked) and masked[start] in BLANK:
            start += 1
        if not masked.startswith(token, start):
            return None
        gap = masked[position:start]
        position = start + len(token)
        if _is_operator(token):
            segments.append([])
            skip_target = previous_is_word = False
        elif skip_target:
            skip_target = previous_is_word = False
        elif token in REDIRECTS:
            if segments[-1] and segments[-1][-1].isdigit():
                segments[-1].pop()
            skip_target, previous_is_word = True, False
        else:
            words = segments[-1]
            if previous_is_word and not gap:
                words[-1] += gap + token
            else:
                words.append(token)
            previous_is_word = True
    return segments


def _is_operator(token: str) -> bool:
    """Whether a token separates commands: a known operator, or a run of separator characters."""
    return token in OPERATORS or (bool(token) and set(token) <= SEPARATOR_CHARACTERS)


def _mask_escapes(command: str) -> str:
    """The command with each escape replaced by its one-character code, found by a quote scan."""
    out: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        following = command[index + 1] if index + 1 < len(command) else ""
        if char == "\\" and quote != "'" and following:
            if following == "\n":
                # A backslash before a newline continues the line, so both are removed.
                index += 2
                continue
            escaped = (quote is None and following in ESCAPABLE) or (
                quote == '"' and following in '"\\'
            )
            if escaped:
                out.append(ESCAPE_CODES[following])
                index += 2
                continue
        if quote is None and char in "'\"":
            quote = char
        elif quote == char:
            quote = None
        out.append(char)
        index += 1
    return "".join(out)


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

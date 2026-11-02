"""Find the recorded kb calls in one shell command line. Text only: no file or store I/O.

A kb call is a simple command whose program is named kb and whose subcommand is one of
RECORDED. Commands are separated by ;, &&, ||, |, &, and newlines. A redirection is dropped
with its target. A comment and a heredoc body are dropped before lexing. Text inside $(...),
backticks, or a nested shell string is not split, so a kb call there is not found.

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
# A word ends at one of these characters. A # that begins a word after one of them is a comment.
WORD_BREAKS = frozenset(" \t\r\n;&|()<>")


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
    masked = _drop_inert(_mask_escapes(command))
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
            # Only a digit that touches the operator is a file descriptor, as in 2>&1.
            if previous_is_word and not gap and segments[-1][-1].isdigit():
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


def _drop_inert(text: str) -> str:
    """The command text without comments and heredoc bodies. Quoted text is kept as it is.

    A # that begins a word starts a comment, which runs to the end of its line. A << (not <<<)
    starts a heredoc. Its command text stays, and the lines after the line that holds it are
    dropped through the terminator line. The bodies of several heredocs on one line follow in order.
    """
    out: list[str] = []
    pending: list[tuple[str, bool]] = []
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "\\":
            out.append(text[index : index + 2])
            index += 2
            continue
        elif char == "#" and (index == 0 or text[index - 1] in WORD_BREAKS):
            index = _line_end(text, index)
            continue
        elif text.startswith("<<<", index):
            out.append("<<<")
            index += 3
            continue
        elif text.startswith("<<", index):
            heredoc = _heredoc(text, index)
            if heredoc is None:
                out.append("<<")
                index += 2
                continue
            delimiter, strip_tabs, end = heredoc
            pending.append((delimiter, strip_tabs))
            out.append(text[index:end])
            index = end
            continue
        elif char == "\n" and pending:
            out.append(char)
            index = _skip_bodies(text, index + 1, pending)
            pending = []
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _line_end(text: str, index: int) -> int:
    """The index of the newline that ends the line at index, or the end of the text."""
    end = text.find("\n", index)
    return len(text) if end == -1 else end


def _heredoc(text: str, operator: int) -> tuple[str, bool, int] | None:
    """The delimiter of a heredoc whose << is at operator, its strip-tabs flag, and the index after it.

    The delimiter is read without its quotes. A delimiter with an unclosed quote is not a heredoc.
    """
    position = operator + 2
    strip_tabs = text.startswith("-", position)
    if strip_tabs:
        position += 1
    while position < len(text) and text[position] in " \t":
        position += 1
    word: list[str] = []
    while position < len(text) and text[position] not in WORD_BREAKS:
        char = text[position]
        if char in "'\"":
            close = text.find(char, position + 1)
            if close == -1:
                return None
            word.append(text[position + 1 : close])
            position = close + 1
        elif char == "\\" and position + 1 < len(text):
            word.append(text[position + 1])
            position += 2
        else:
            word.append(char)
            position += 1
    if not word:
        return None
    return "".join(word), strip_tabs, position


def _skip_bodies(text: str, start: int, pending: list[tuple[str, bool]]) -> int:
    """The index after the bodies of the pending heredocs, which begin at start."""
    index = start
    for delimiter, strip_tabs in pending:
        while index < len(text):
            line_end = _line_end(text, index)
            line = text[index:line_end]
            index = min(line_end + 1, len(text))
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return index


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

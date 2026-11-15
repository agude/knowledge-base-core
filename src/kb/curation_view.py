"""The curation view of a transcript observation: its text, with shell blocks as stubs.

The stored observation keeps every command. The view replaces the shell blocks of each run of
messages with one stub that counts the commands, names their programs, and gives the locator
that prints them in full. A message with text keeps its text, and its commands start the next
stub. Any other observation is shown unchanged.
"""

import re
from collections import Counter
from collections.abc import Sequence

from kb import shellcalls
from kb.hosts import codex

HEADING = re.compile(r"^## ([1-9][0-9]*)\. (?:user|assistant), \S+$", re.MULTILINE)
FENCE = re.compile(r"^(~{4,})(text|sh)\n(.*?)\n\1$", re.MULTILINE | re.DOTALL)
TRANSCRIPT = re.compile(r"^source: session-transcript$", re.MULTILINE)
APP = re.compile(r"^app: (\S+)$", re.MULTILINE)
SHOWN_PROGRAMS = 5


def render(text: str, locator: str) -> str:
    """The view of an observation whose path is locator."""
    front, separator, body = _split(text)
    if not separator or TRANSCRIPT.search(front) is None:
        return text
    app_match = APP.search(front)
    app = app_match.group(1) if app_match else ""
    headings = list(HEADING.finditer(body))
    if not headings:
        return text
    parts = [(front + separator + body[: headings[0].start()]).rstrip("\n")]
    run: list[tuple[int, str]] = []

    def flush() -> None:
        if run:
            parts.append(_stub(run, locator, app))
            run.clear()

    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        segment = body[heading.end() : end]
        fences = list(FENCE.finditer(segment))
        if FENCE.sub("", segment).strip():
            flush()
            parts.append((heading.group(0) + segment).rstrip("\n"))
            continue
        texts = [fence.group(0) for fence in fences if fence.group(2) == "text"]
        if texts:
            flush()
            parts.append(heading.group(0))
            parts.extend(texts)
        number = int(heading.group(1))
        run.extend((number, fence.group(3)) for fence in fences if fence.group(2) == "sh")
    flush()
    return "\n\n".join(part for part in parts if part) + "\n"


def _split(text: str) -> tuple[str, str, str]:
    """Front matter through its opening line and fields, the closing delimiter, and the body."""
    if not text.startswith("---\n"):
        return text, "", ""
    end = text.find("\n---\n", 3)
    if end < 0:
        return text, "", ""
    return text[: end + 1], "---\n", text[end + 5 :]


def _stub(run: Sequence[tuple[int, str]], locator: str, app: str) -> str:
    """One line that stands for a run of commands."""
    first, last = run[0][0], run[-1][0]
    counts = Counter(name for _, command in run for name in _programs(command, app))
    names = [name if count == 1 else f"{name} x{count}" for name, count in counts.most_common()]
    if len(names) > SHOWN_PROGRAMS:
        names = [*names[:SHOWN_PROGRAMS], f"{len(names) - SHOWN_PROGRAMS} more"]
    size = sum(len(command.encode("utf-8")) for _, command in run)
    where = f"message {first}" if first == last else f"messages {first}-{last}"
    read = (
        f"kb read {locator}#{first}" if first == last else f"kb read {locator}#N, N {first}-{last}"
    )
    listed = f": {', '.join(names)}" if names else ""
    return f"[{len(run)} command(s) in {where}, {_size(size)}{listed}. Read with: {read}]"


def _programs(command: str, app: str) -> tuple[str, ...]:
    return codex.programs(command) if app == "codex" else shellcalls.programs(command)


def _size(count: int) -> str:
    return f"{count} bytes" if count < 1024 else f"{(count + 1023) // 1024} KB"

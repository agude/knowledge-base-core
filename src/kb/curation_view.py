"""The curation view of a transcript observation: its text, with shell blocks as stubs.

The stored observation keeps every command. Message boundaries come from kb.model, so a
heading quoted inside a fence is not one. The view replaces the shell blocks of each run of
messages with one stub that counts the commands, names their programs, and gives the locator
that prints them in full. A message with text keeps its text, and its commands start the next
stub. Any other observation is shown unchanged.
"""

import re
from collections import Counter
from collections.abc import Sequence

from kb import model, shellcalls
from kb.hosts import codex

MESSAGE = re.compile(r"[1-9][0-9]*\. (?:user|assistant), \S+")
OPENING = re.compile(r"(~{4,})(text|sh)")
SHOWN_PROGRAMS = 5


def render(text: str, locator: str) -> str:
    """The view of an observation whose path is locator."""
    document = model.parse(locator, text)
    if (
        document.scalar("source") != "session-transcript"
        or document.unclosed_fence_start is not None
    ):
        return text
    starts = [
        section.start
        for section in document.sections
        if section.level == 2 and MESSAGE.fullmatch(section.heading)
    ]
    if not starts:
        return text
    lines = document.lines
    app = document.scalar("app") or ""
    parts = ["\n".join(lines[: starts[0]]).rstrip("\n")]
    run: list[tuple[int, str]] = []

    def flush() -> None:
        if run:
            parts.append(_stub(run, locator, app))
            run.clear()

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(lines)
        heading = lines[start]
        blocks = _blocks(lines[start + 1 : end])
        if blocks is None:
            flush()
            parts.append("\n".join(lines[start:end]).rstrip("\n"))
            continue
        texts = ["\n".join(block) for info, block in blocks if info == "text"]
        if texts:
            flush()
            parts.append(heading)
            parts.extend(texts)
        number = int(heading.removeprefix("## ").split(".", 1)[0])
        run.extend((number, "\n".join(block[1:-1])) for info, block in blocks if info == "sh")
    flush()
    return "\n\n".join(part for part in parts if part) + "\n"


def _blocks(lines: Sequence[str]) -> list[tuple[str, list[str]]] | None:
    """The text and sh fences of one message, or None when it holds anything else.

    A fence closes only on a line that repeats its opening marker. Harvest makes the marker
    longer than any tilde run inside the content, so no content line can close it.
    """
    blocks: list[tuple[str, list[str]]] = []
    block: list[str] | None = None
    marker = info = ""
    for line in lines:
        if block is not None:
            block.append(line)
            if line == marker:
                blocks.append((info, block))
                block = None
        elif (opening := OPENING.fullmatch(line)) is not None:
            marker, info = opening.groups()
            block = [line]
        elif line.strip():
            return None
    return None if block is not None else blocks


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

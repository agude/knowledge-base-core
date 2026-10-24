"""questions - List or read open questions in the knowledge base.

Shows questions that the curator or other sessions have flagged as gaps.
Questions may optionally have a context field linking them to a knowledge
area.

Usage:
  questions [--path DIR_OR_FILE] [--full] [--all]
  questions --file FILENAME

Options:
  --path PATH      Only show questions whose context falls under PATH
  --file FILENAME  Read a single question file from questions/open/
  --full           Show full question content (default: title + context only)
  --all            Include resolved questions too

Examples:
  questions                                  # all open questions
  questions --path knowledge/ach/            # open questions about ACH
  questions --full                           # full content
  questions --file 20260324T220000-0a1b2c3d.md   # read one question
"""

from __future__ import annotations

import contextlib

from kb import cli, frontmatter, paths, platform
from kb.content import content_dir


def _matches(context: str, prefix: str) -> bool:
    """Whether context is prefix or lies under it: whole segments (audit A-013)."""
    base = prefix.rstrip("/")
    return context == base or context.startswith(f"{base}/")


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--path": "path", "--file": "file"},
        flags={"--full": "full", "--all": "all"},
    )
    content = content_dir()
    single = args.get("file")
    if single:
        if "/" in single:
            cli.fail(f"Not a question filename: {single}")
        for area in ("open", "resolved"):
            target = content / "questions" / area / single
            if target.is_file():
                print(platform.read_text(target), end="")
                return 0
        cli.fail(f"Not found: {single} (checked open/ and resolved/)")
    prefix = args.get("path")
    if prefix:
        # A filter over recorded context strings, which may name moved or
        # deleted articles; resolution only helps with bare file names.
        with contextlib.suppress(paths.PathError):
            prefix = paths.resolve(content, prefix) or prefix
    areas = ["open", "resolved"] if "all" in args.flags else ["open"]
    count = 0
    for area in areas:
        directory = content / "questions" / area
        if not directory.is_dir():
            continue
        for path in sorted((p for p in directory.rglob("*.md") if p.is_file()), key=bytes):
            text = platform.read_text(path)
            title = frontmatter.field(text, "title") or ""
            context = frontmatter.field(text, "context") or ""
            if prefix and not (context and _matches(context, prefix)):
                continue
            count += 1
            if "full" in args.flags:
                print(f"--- {path.name} ---")
                print(text, end="")
                print()
                continue
            status = " [resolved]" if "all" in args.flags and path.parent.name == "resolved" else ""
            print(f"- {title}{status} ({context})" if context else f"- {title}{status}")
    if count == 0:
        print(f"No open questions for {prefix}" if prefix else "No open questions.")
    return 0

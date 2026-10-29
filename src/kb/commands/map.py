"""kb map: list the articles under a path, with their H2 and H3 sections."""

import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from kb import args, corpus
from kb.args import Spec
from kb.context import load
from kb.errors import KbError
from kb.locators import display_title
from kb.model import Document

WHO = "kb map"
DEFAULT_PATH = "knowledge"
SPEC = Spec(
    usage="map [PATH] [--depth 1|2|3]",
    summary=(
        "List the articles under PATH (default knowledge/). Depth 1 counts articles per\n"
        "directory. Depth 2 lists each article with its H2 sections. Depth 3 adds H3 sections."
    ),
    valued=frozenset({"--depth"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb map and print its listing."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if len(parsed.words) > 1:
        raise SPEC.usage_error()
    depth = args.choice_int(parsed.values.get("--depth", "2"), "--depth", (1, 2, 3))
    context = load(os.environ, sys.platform, Path.home())
    path = parsed.words[0] if parsed.words else DEFAULT_PATH
    relpath = corpus.resolve_path(context.root, path, WHO)
    if relpath is None:
        raise KbError(f"{WHO}: no such path: {path}")
    paths = corpus.markdown_files(context.root, relpath)
    if depth == 1:
        lines = area_lines(paths)
    else:
        documents = [corpus.read_document(context.root, found) for found in paths]
        lines = article_lines(documents, depth)
    sys.stdout.write("".join(f"{line}\n" for line in lines))
    return 0


def area_lines(paths: Sequence[str]) -> list[str]:
    """One line per directory that holds articles, with the number of articles in it."""
    counts = Counter(PurePosixPath(found).parent.as_posix() for found in paths)
    return [
        f"{area} | {count} article" + ("" if count == 1 else "s")
        for area, count in sorted(counts.items())
    ]


def article_lines(documents: Sequence[Document], depth: int) -> list[str]:
    """Each article's path and title, then its H2 sections, and H3 sections at depth 3."""
    lines: list[str] = []
    for document in documents:
        lines.append(f"{document.path} | {display_title(document)}")
        for section in document.sections:
            if section.level == 2:
                lines.append(f"  {document.path}#{section.key} | {section.heading}")
            elif depth == 3:
                lines.append(f"    {document.path}#{section.key} | {section.heading}")
    return lines

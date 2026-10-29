"""kb read: print the text that each locator names, after a header line."""

import os
import sys
from collections.abc import Sequence
from pathlib import Path

from kb import args, corpus, freshness, locators
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError
from kb.model import Document, Section

WHO = "kb read"
SPEC = Spec(
    usage="read LOCATOR... [--sources]",
    summary=(
        "Print the text each LOCATOR names, with a header line for each: locator, heading,\n"
        "freshness, and sources. PATH alone prints the file's outline and its top prose.\n"
        "--sources prints the sources of each locator instead."
    ),
    switches=frozenset({"--sources"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb read. Output for locators before a failing one is still printed."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if not parsed.words:
        raise SPEC.usage_error()
    context = load(os.environ, sys.platform, Path.home())
    sources_only = "--sources" in parsed.switches
    for index, word in enumerate(parsed.words):
        text = render(context, word, sources_only)
        if index and not sources_only:
            sys.stdout.write("\n")
        sys.stdout.write(text)
    return 0


def render(context: Context, word: str, sources_only: bool) -> str:
    """The output for one locator. Raises KbError when it names nothing."""
    locator = locators.parse_locator(word)
    relpath = _file(context, locator.path)
    document = corpus.read_document(context.root, relpath)
    if locator.fragment is None:
        return _whole_file(context, document, relpath, sources_only)
    selection = locators.select(document, locator.fragment)
    if selection is None:
        raise KbError(_missing(document, relpath, locator.fragment))
    if sources_only:
        return _lines(document.items("sources", selection.section))
    name = f"{relpath}#{locator.fragment}"
    heading = selection.heading or locators.display_title(document)
    head = _header(context, document, name, heading, selection.section)
    return locators.block(head, selection.lines)


def _file(context: Context, path: str) -> str:
    relpath = corpus.resolve_path(context.root, path, WHO)
    if relpath is None:
        raise KbError(f'{WHO}: no file matches "{path}"')
    if (context.root / relpath).is_dir():
        raise KbError(f"{WHO}: {path} is a directory")
    return relpath


def _whole_file(context: Context, document: Document, relpath: str, sources_only: bool) -> str:
    if sources_only:
        return _lines(document.items("sources"))
    head = _header(context, document, relpath, locators.display_title(document), None)
    body = locators.outline(document)
    top = document.top_lines()
    if body and top:
        body.append("")
    body.extend(top)
    return locators.block(head, body)


def _header(
    context: Context,
    document: Document,
    name: str,
    heading: str,
    section: Section | None,
) -> str:
    if not corpus.is_curated(document.path):
        return locators.header(name, heading, None, None)
    status = freshness.status(document, section, context.today)
    return locators.header(name, heading, status, len(document.items("sources", section)))


def _lines(items: Sequence[str]) -> str:
    return "".join(f"{item}\n" for item in items)


def _missing(document: Document, relpath: str, fragment: str) -> str:
    listing = [f"  {line}" for line in locators.outline(document)]
    return "\n".join([f"{WHO}: {relpath} has no section {fragment}. Its locators:", *listing])

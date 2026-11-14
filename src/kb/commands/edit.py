"""kb edit: place writer-supplied section text in an article, or set its TTL.

The writer supplies whole sections, or paragraphs to append, on stdin. kb edit decides
where the text lands, keeps the section metadata that a rewrite omits, checks the result,
and replaces the file atomically under the write lock. It never commits; curate finish
publishes the edits with the batch.
"""

import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast

from kb import args, articles, corpus, lint, lock, model, scratch, secrets, sections
from kb.args import Spec
from kb.context import load
from kb.errors import KbError
from kb.locators import NUMBERED, parse_locator

WHO = "edit"
PLACEMENT = frozenset({"--after", "--before"})
REPLACE_SPEC = Spec(
    usage="edit replace LOCATOR",
    summary=(
        "Replace section LOCATOR (ARTICLE#N or ARTICLE#N.M) with the sections on stdin. "
        "The text starts with a heading of the same level and may hold several sections, "
        "which splits one. A rewritten section without a metadata comment keeps the "
        "comment of the replaced section with the same heading."
    ),
)
APPEND_SPEC = Spec(
    usage="edit append LOCATOR",
    summary=(
        "Append the paragraphs on stdin to the end of section LOCATOR's own text, before "
        "any H3 it holds. The text must not contain H2 or H3 headings."
    ),
)
INSERT_SPEC = Spec(
    usage="edit insert ARTICLE (--after FRAGMENT | --before FRAGMENT)",
    summary=(
        "Insert the sections on stdin after or before section FRAGMENT (N or N.M), or "
        "--after top for a new first H2. An H3 goes --after an H2 as its last H3."
    ),
    valued=PLACEMENT,
)
MOVE_SPEC = Spec(
    usage="edit move LOCATOR (--after FRAGMENT | --before FRAGMENT)",
    summary="Move section LOCATOR after or before section FRAGMENT, or --after top.",
    valued=PLACEMENT,
)
REMOVE_SPEC = Spec(usage="edit remove LOCATOR", summary="Delete section LOCATOR.")
TTL_SPEC = Spec(
    usage="edit ttl ARTICLE TTL",
    summary=(
        "Set the article's ttl (people, status, process, domain, or a day count) without "
        "changing verified. Use kb verify to record a verification."
    ),
)
SPECS = {
    "replace": REPLACE_SPEC,
    "append": APPEND_SPEC,
    "insert": INSERT_SPEC,
    "move": MOVE_SPEC,
    "remove": REMOVE_SPEC,
    "ttl": TTL_SPEC,
}
SPEC = Spec(
    usage="edit {replace,append,insert,move,remove,ttl} ...",
    summary=(
        "Place section text from stdin in a knowledge article and report the resulting "
        "locators. Each edit is checked and written atomically; nothing is committed."
    ),
)


def run(words: Sequence[str]) -> int:
    """Dispatch one edit subcommand."""
    if not words or words[0] in args.HELP_FLAGS:
        sys.stdout.write(SPEC.help_text())
        return 0
    action, *rest = words
    spec = SPECS.get(action)
    if spec is None:
        raise KbError(f"Usage: kb {SPEC.usage}")
    parsed = args.parse(spec, rest)
    if parsed.help:
        sys.stdout.write(spec.help_text())
        return 0
    expected = 2 if action == "ttl" else 1
    if len(parsed.words) != expected:
        raise spec.usage_error()
    placement = _placement(action, spec, parsed.values)
    try:
        wait = lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise spec.usage_error() from None

    try:
        context = load(os.environ, sys.platform, Path.home())
        root = context.root
        relpath, fragment = _target(root, action, parsed.words[0])
        supplied = None
        if action in {"replace", "append", "insert"}:
            supplied = sys.stdin.read()
        git_directory = lock.git_dir(root, WHO)
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, wait, backend):
            if supplied is not None:
                _scan(git_directory, supplied)
            article = articles.read(root, relpath, WHO)
            edit = _operation(action, fragment, placement, supplied, parsed.words)
            try:
                edited = edit(article.text)
            except sections.EditError as error:
                raise KbError(_refusal(relpath, article.text, str(error))) from error
            report = _check(root, relpath, article.text, edited)
            articles.write(root, git_directory, article, edited.text, WHO)
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(report)
    return 0


def _placement(action: str, spec: Spec, values: dict[str, str]) -> tuple[str, str] | None:
    """The one --after or --before value that insert and move require."""
    if action not in {"insert", "move"}:
        return None
    given = [
        (name.removeprefix("--"), value) for name, value in values.items() if name in PLACEMENT
    ]
    if len(given) != 1:
        raise spec.usage_error()
    placement, anchor = given[0]
    if anchor != "top":
        anchor = parse_locator(f"x#{anchor}").fragment or ""
        if NUMBERED.fullmatch(anchor) is None:
            raise KbError(f"{WHO}: --{placement} must name a section number (N or N.M) or top")
    return placement, anchor


def _target(root: Path, action: str, word: str) -> tuple[str, str | None]:
    """The article under knowledge/ and the numbered section the action needs."""
    locator = parse_locator(word)
    relpath = corpus.resolve_path(root, locator.path, WHO)
    if relpath is None:
        raise KbError(f'{WHO}: no article matches "{locator.path}"')
    if not relpath.startswith("knowledge/") or not relpath.endswith(".md"):
        raise KbError(f"{WHO}: the article must be a Markdown file under knowledge/: {relpath}")
    if not (root / relpath).is_file():
        raise KbError(f"{WHO}: no such article: {relpath}")
    takes_section = action in {"replace", "append", "move", "remove"}
    fragment = locator.fragment
    if takes_section and (fragment is None or NUMBERED.fullmatch(fragment) is None):
        raise KbError(f"{WHO}: {action} needs a numbered section locator: ARTICLE#N or #N.M")
    if not takes_section and fragment is not None:
        raise KbError(f"{WHO}: {action} takes an article without a fragment: {word}")
    return relpath, fragment


def _operation(
    action: str,
    fragment: str | None,
    placement: tuple[str, str] | None,
    supplied: str | None,
    words: Sequence[str],
) -> Callable[[str], sections.Edited]:
    """The pure edit for one action, bound to its arguments."""
    key = fragment or ""
    text = supplied or ""
    if action == "replace":
        return lambda article: sections.replace(article, key, text)
    if action == "append":
        return lambda article: sections.append(article, key, text)
    if action == "remove":
        return lambda article: sections.remove(article, key)
    if action == "ttl":
        ttl = words[1]
        if not lint.valid_ttl(ttl):
            raise KbError(f"{WHO}: invalid TTL: {ttl}")
        return lambda article: sections.Edited(sections.set_ttl(article, ttl), None)
    assert placement is not None
    where, anchor = cast(tuple[sections.Placement, str], placement)
    if action == "insert":
        return lambda article: sections.insert(article, anchor, where, text)
    return lambda article: sections.move(article, key, anchor, where)


def _scan(git_directory: Path, text: str) -> None:
    """Refuse writer text that matches a secret check before anything is written."""
    found = secrets.findings(scratch.shared_directory(git_directory, WHO), text)
    if found:
        lines = sorted({line for _, line in found})
        kinds = ", ".join(sorted({kind for kind, _ in found}))
        listing = ", ".join(str(line) for line in lines)
        raise KbError(f"{WHO}: possible secret in the text on stdin ({kinds}) at line {listing}")


def _check(root: Path, relpath: str, before: str, edited: sections.Edited) -> str:
    """Refuse new lint errors, then report written sections, renumbering, and new warnings."""
    old = model.parse(relpath, before)
    new = model.parse(relpath, edited.text)
    old_findings = lint.check_document(old) + lint.reference_findings(root, old, {relpath: old})
    new_findings = lint.check_document(new) + lint.reference_findings(root, new, {relpath: new})
    errors = _added(old_findings, new_findings, "error")
    if errors:
        details = "\n".join(f"  {item.path}:{item.line}: {item.message}" for item in errors)
        raise KbError(f"{WHO}: the edit would add lint errors; nothing was written:\n{details}")

    lines = [f"Edited: {relpath}"]
    lines.extend(f"  {relpath}#{item.key} | {item.heading}" for item in _written(new, edited))
    lines.extend(_renumbered(relpath, old, new))
    lines.extend(
        f"Warning: {item.path}:{item.line}: {item.message}"
        for item in _added(old_findings, new_findings, "warning")
    )
    if "ttl" not in new.front:
        lines.append(
            f"Note: {relpath} has no ttl; curate finish requires one. "
            f"Set it with: kb edit ttl {relpath} TTL"
        )
    return "\n".join(lines) + "\n"


def _added(
    old: Sequence[lint.Finding], new: Sequence[lint.Finding], severity: str
) -> list[lint.Finding]:
    """Findings of a severity that the edit added, matched by message, not by line."""
    known = Counter(item.message for item in old if item.severity == severity)
    added: list[lint.Finding] = []
    for item in new:
        if item.severity != severity:
            continue
        if known[item.message]:
            known[item.message] -= 1
        else:
            added.append(item)
    return added


def _written(document: model.Document, edited: sections.Edited) -> list[model.Section]:
    """Sections that start in the written lines, else the innermost one holding them."""
    span = edited.written
    if span is None:
        return []
    started = [item for item in document.sections if span.start <= item.start < span.end]
    if started:
        return started
    holders = [item for item in document.sections if item.start < span.start < item.end]
    return holders[-1:]


def _renumbered(relpath: str, old: model.Document, new: model.Document) -> list[str]:
    """Sections whose number changed, matched by a level and heading unique in both."""

    def unique(document: model.Document) -> dict[tuple[int, str], str]:
        counts = Counter((item.level, item.heading) for item in document.sections)
        return {
            (item.level, item.heading): item.key
            for item in document.sections
            if counts[(item.level, item.heading)] == 1
        }

    before = unique(old)
    after = unique(new)
    return [
        f"Renumbered: {relpath}#{before[name]} -> #{after[name]} | {name[1]}"
        for name in before
        if name in after and before[name] != after[name]
    ]


def _refusal(relpath: str, text: str, reason: str) -> str:
    """A refusal that lists the article's locators when a section was not found."""
    message = f"{WHO}: {reason}"
    if reason.startswith("no section"):
        document = model.parse(relpath, text)
        listing = [f"  {relpath}#{item.key} | {item.heading}" for item in document.sections]
        message = "\n".join([f"{message}. Its sections:", *listing])
    return message

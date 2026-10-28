"""kb resolve: move one open question into resolved with its answer and destination."""

import os
import stat
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from kb import args, corpus, locators, lock, model, observation, question, secrets
from kb.args import Spec
from kb.context import Context, load
from kb.errors import KbError
from kb.locators import parse_locator

WHO = "resolve"
OPEN = "questions/open"
RESOLVED = "questions/resolved"
SPEC = Spec(
    usage="resolve QUESTION --answer TEXT [--destination LOCATOR | --obsolete]",
    summary=(
        "Resolve one open question to an existing knowledge locator, or mark it obsolete. "
        "Use --answer - to read the answer from standard input."
    ),
    valued=frozenset({"--answer", "--destination"}),
    switches=frozenset({"--obsolete"}),
)


def run(words: Sequence[str]) -> int:
    """Resolve one question and print its open-to-resolved path transition."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if len(parsed.words) != 1:
        raise SPEC.usage_error()

    answer = _answer(parsed.values)
    destination = parsed.values.get("--destination")
    obsolete = "--obsolete" in parsed.switches
    if (destination is None) != obsolete:
        raise KbError(f"{WHO}: exactly one of --destination and --obsolete is required")
    wait = _wait()

    try:
        context = load(os.environ, sys.platform, Path.home())
        source_relpath = _resolve(
            context,
            parsed.words[0],
            answer,
            destination,
            obsolete,
            wait,
        )
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except KbError as error:
        if str(error).startswith((WHO + ":", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error

    destination_relpath = source_relpath.replace(f"{OPEN}/", f"{RESOLVED}/", 1)
    sys.stdout.write(f"Resolved: {source_relpath} -> {destination_relpath}\n")
    return 0


def _answer(values: dict[str, str]) -> str:
    """The required answer, read as UTF-8 stdin when its option value is a dash."""
    supplied = values.get("--answer")
    if supplied is None:
        raise SPEC.usage_error()
    try:
        answer = sys.stdin.buffer.read().decode("utf-8") if supplied == "-" else supplied
    except UnicodeDecodeError as error:
        raise KbError(f"{WHO}: standard input is not UTF-8: {error.reason}") from error
    try:
        observation.check_body(answer)
    except observation.InvalidArgument:
        raise SPEC.usage_error() from None
    return answer


def _wait() -> int:
    """The lock wait from KB_LOCK_WAIT. An invalid value is a usage error."""
    try:
        return lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None


def _resolve(
    context: Context,
    question_word: str,
    answer: str,
    destination_word: str | None,
    obsolete: bool,
    wait: int,
) -> str:
    """Validate, scan, and publish a resolved copy while holding both writer locks."""
    root = context.root
    git = lock.git_dir_path(root, WHO)
    backend = lock.default_backend(sys.platform)
    with lock.write_lock(git, root, wait, backend):
        source_relpath = _question_path(root, question_word)
        source = root / source_relpath
        try:
            original_bytes = source.read_bytes()
            original_text = original_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KbError(f"{WHO}: question is not valid UTF-8: {error.reason}") from error

        canonical_destination = (
            None if obsolete else _destination_locator(root, destination_word or "")
        )
        resolution: Literal["answered", "obsolete"] = "obsolete" if obsolete else "answered"
        try:
            rendered = question.render_resolution(
                original_text,
                resolution,
                answer,
                canonical_destination,
                context.today,
            )
        except model.FrontMatterEditError as error:
            raise KbError(f"{WHO}: unsafe question front matter: {error}") from error

        target_relpath = source_relpath.replace(f"{OPEN}/", f"{RESOLVED}/", 1)
        target = root / target_relpath
        if target.exists():
            raise KbError(f"{WHO}: resolved copy already exists: {target_relpath}")

        found = secrets.findings(
            Path(tempfile.gettempdir()),
            question.resolution_scan_text(answer, canonical_destination),
        )
        if found:
            raise KbError("\n".join(question.resolution_refusal_lines(found)))

        return _publish(
            root,
            git,
            source,
            target,
            original_bytes,
            rendered.encode("utf-8"),
            stat.S_IMODE(source.stat().st_mode),
        )


def _question_path(root: Path, word: str) -> str:
    """Resolve QUESTION to one Markdown file directly under questions/open/."""
    locator = parse_locator(word)
    if locator.fragment is not None:
        raise KbError(f"{WHO}: QUESTION must not include a fragment: {word}")
    relpath = corpus.resolve_path(root, locator.path, WHO)
    if relpath is None:
        raise KbError(f'{WHO}: no question matches "{locator.path}"')
    if not relpath.startswith(f"{OPEN}/") or not relpath.endswith(".md"):
        raise KbError(f"{WHO}: QUESTION must name a file under {OPEN}/: {relpath}")
    if not (root / relpath).is_file():
        raise KbError(f"{WHO}: QUESTION must name a file under {OPEN}/: {relpath}")
    return relpath


def _destination_locator(root: Path, word: str) -> str:
    """Resolve DESTINATION as a current kb read locator under knowledge/."""
    locator = parse_locator(word)
    relpath = corpus.resolve_path(root, locator.path, WHO)
    if relpath is None:
        raise KbError(f'{WHO}: no file matches "{locator.path}"')
    if not relpath.startswith("knowledge/"):
        raise KbError(f"{WHO}: destination must resolve under knowledge/: {relpath}")
    path = root / relpath
    if path.is_dir():
        raise KbError(f"{WHO}: destination must name a file: {relpath}")
    if not path.is_file():
        raise KbError(f'{WHO}: no file matches "{locator.path}"')
    document = corpus.read_document(root, relpath)
    if locator.fragment is None:
        return relpath
    if locators.select(document, locator.fragment) is None:
        listing = [f"  {line}" for line in locators.outline(document)]
        detail = "\n".join(
            [f"{WHO}: {relpath} has no section {locator.fragment}. Its locators:", *listing]
        )
        raise KbError(detail)
    return f"{relpath}#{locator.fragment}"


def _publish(
    root: Path,
    git: Path,
    source: Path,
    target: Path,
    original: bytes,
    rendered: bytes,
    mode: int,
) -> str:
    """Atomically publish the resolved file and restore the open file on failure."""
    scratch = git / "kb-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    root_resolved = root.resolve()
    if not target.parent.resolve().is_relative_to(root_resolved):
        raise KbError(f"{WHO}: resolved question path escapes the content repository")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(root_resolved):
        raise KbError(f"{WHO}: resolved question path escapes the content repository")
    if target.exists():
        raise KbError(f"{WHO}: resolved copy already exists: {target.relative_to(root).as_posix()}")

    temporary = scratch / f"resolve-{os.urandom(4).hex()}.md"
    restore = scratch / f"resolve-restore-{os.urandom(4).hex()}.md"
    published = False
    publication_attempted = False
    try:
        with temporary.open("xb") as handle:
            handle.write(rendered)
        temporary.chmod(mode)
        publication_attempted = True
        temporary.replace(target)
        published = True
        source.unlink()
    except BaseException:
        ours = published or (
            publication_attempted and target.is_file() and target.read_bytes() == rendered
        )
        if ours:
            try:
                if not source.is_file() or source.read_bytes() != original:
                    with restore.open("xb") as handle:
                        handle.write(original)
                    restore.chmod(mode)
                    restore.replace(source)
                target.unlink(missing_ok=True)
            except BaseException as rollback_error:
                raise KbError(
                    f"{WHO}: rollback failed; inspect both question files and {scratch}"
                ) from rollback_error
        raise
    finally:
        temporary.unlink(missing_ok=True)
        restore.unlink(missing_ok=True)

    return source.relative_to(root).as_posix()

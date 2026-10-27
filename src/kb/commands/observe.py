"""kb observe: record one observation in observations/pending/, and commit only that file.

The write path follows section 3 of the observe plan: validate, render, scan, write to a
temporary file, take the lock, publish, commit, unlock, and report.
"""

import os
import socket
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from kb import args, lock, observation, secrets
from kb.args import Spec
from kb.context import load
from kb.errors import KbError

PENDING = "observations/pending"
MAX_NAME_TRIES = 5
SPEC = Spec(
    usage="observe --title TITLE --body TEXT",
    summary=(
        "Record one observation in observations/pending/ and commit it. The body is TEXT, or the\n"
        "standard input when TEXT is -. A body that holds a possible secret is refused."
    ),
    valued=frozenset({"--title", "--body"}),
)


def run(words: Sequence[str]) -> int:
    """Run kb observe. On success, print the Wrote line and return 0."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    title, body = _arguments(parsed.values)
    wait = _wait()
    root = _content_root()
    try:
        name = _record(root, title, body, wait)
    except lock.LockBusy as busy:
        raise KbError(
            f"observe: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except (OSError, UnicodeError) as error:
        raise KbError(f"observe: {error}") from error
    sys.stdout.write(f"Wrote: {PENDING}/{name}\n")
    return 0


def _arguments(values: Mapping[str, str]) -> tuple[str, str]:
    """The title and the body, both validated. A body of - is read from standard input."""
    title = values.get("--title")
    text = values.get("--body")
    if title is None or text is None:
        raise SPEC.usage_error()
    body = _read_stdin() if text == "-" else text
    try:
        observation.check_title(title)
        observation.check_body(body)
    except observation.InvalidArgument:
        raise SPEC.usage_error() from None
    return title, body


def _read_stdin() -> str:
    """Standard input, read to the end of the file and decoded as UTF-8."""
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"observe: standard input is not UTF-8: {error.reason}") from error


def _wait() -> int:
    """The lock wait from KB_LOCK_WAIT. An invalid value is a usage error."""
    try:
        return lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None


def _content_root() -> Path:
    """The content repository, resolved as the read commands resolve it."""
    try:
        return load(os.environ, sys.platform, Path.home()).root
    except KbError as error:
        raise KbError(f"observe: {error}") from error


def _record(root: Path, title: str, body: str, wait: int) -> str:
    """Write the observation, commit it, and return its file name."""
    git_directory = lock.git_dir(root)
    when = datetime.now(UTC)
    host = observation.short_host(socket.gethostname())
    text = observation.render(title, body, _project(), host, when)
    scratch = git_directory / "kb-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    found = secrets.findings(scratch, observation.scan_text(title, body))
    if found:
        raise KbError("\n".join(observation.refusal_lines(found)))
    temporary = scratch / observation.temporary_name(os.urandom(4).hex())
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, root, wait, backend):
            name = _publish(root, temporary, when)
            _commit(root, name, title)
    finally:
        temporary.unlink(missing_ok=True)
    return name


def _publish(root: Path, temporary: Path, when: datetime) -> str:
    """Rename the temporary file to a free name in observations/pending, and return the name."""
    pending = root / PENDING
    pending.mkdir(parents=True, exist_ok=True)
    for _ in range(MAX_NAME_TRIES):
        name = observation.file_name(when, os.urandom(4).hex())
        if not (pending / name).exists():
            temporary.rename(pending / name)
            return name
    raise KbError(f"observe: no free file name in {PENDING}")


def _commit(root: Path, name: str, title: str) -> None:
    """Commit the one new file. On failure, unstage it, delete it, and raise."""
    path = f"{PENDING}/{name}"
    result = _git(root, "add", "--", path)
    if result.returncode == 0:
        result = _git(root, "commit", "-q", "-m", f"Observe: {title}", "--", path)
    if result.returncode == 0:
        return
    # The result is ignored: when staging failed, the path was never in the index.
    _git(root, "rm", "-q", "--cached", "--", path)
    (root / path).unlink(missing_ok=True)
    detail = result.stderr.rstrip("\n")
    raise KbError(f"observe: commit failed: {detail}" if detail else "observe: commit failed:")


def _project() -> str:
    """The top of the git repository that the process runs in, or its directory outside one."""
    here = Path.cwd()
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=here,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if top.returncode == 0:
        return top.stdout.removesuffix("\n")
    return str(here)


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run git in the content repository and capture its output."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

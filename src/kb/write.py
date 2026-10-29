"""The shared protected file publication and single-path Git commit operation."""

import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from kb import lock, observation, secrets
from kb.errors import KbError

MAX_NAME_TRIES = 5
RefusalLines = Callable[[Sequence[tuple[str, int]]], list[str]]


def publish_and_commit(
    root: Path,
    directory: str,
    text: str,
    scan_text: str,
    when: datetime,
    subject: str,
    command: str,
    wait: int,
    platform: str,
    refusal_lines: RefusalLines,
) -> str:
    """Scan, publish, and commit one new file under the shared writer protections."""
    git_directory = lock.git_dir(root, command)
    scratch = git_directory / "kb-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    found = secrets.findings(scratch, scan_text)
    if found:
        raise KbError("\n".join(refusal_lines(found)))

    temporary = scratch / f"record-{os.urandom(4).hex()}.md"
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
        backend = lock.default_backend(platform)
        with lock.write_lock(git_directory, wait, backend):
            name = _publish(root, directory, temporary, when, command)
            _commit(root, f"{directory}/{name}", subject, command)
    finally:
        temporary.unlink(missing_ok=True)
    return name


def project() -> str:
    """The top of the process's Git repository, or its working directory outside one."""
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


def _publish(root: Path, directory: str, temporary: Path, when: datetime, command: str) -> str:
    """Rename the temporary file to a free timestamped name in directory."""
    destination = root / directory
    destination.mkdir(parents=True, exist_ok=True)
    for _ in range(MAX_NAME_TRIES):
        name = observation.file_name(when, os.urandom(4).hex())
        if not (destination / name).exists():
            temporary.rename(destination / name)
            return name
    raise KbError(f"{command}: no free file name in {directory}")


def _commit(root: Path, path: str, subject: str, command: str) -> None:
    """Commit one new file, removing only its staging and publication on failure."""
    try:
        result = _git(root, "add", "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
        result = _git(root, "commit", "-q", "-m", subject, "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
    except BaseException:
        _rollback(root, path, command)
        raise


def _rollback(root: Path, path: str, command: str) -> None:
    """Unstage the new file before deleting it; retain it if index cleanup fails."""
    # An interrupted add may have staged the file before returning to Python.
    result = _git(root, "ls-files", "-z", "--", path)
    if result.returncode == 0 and result.stdout:
        # A rejecting hook may have changed the file after it was staged.
        result = _git(root, "rm", "-q", "-f", "--cached", "--", path)
    if result.returncode != 0:
        detail = result.stderr.rstrip("\n")
        message = f"{command}: rollback failed for {path}; inspect Git status before retrying"
        raise KbError(f"{message}: {detail}" if detail else message)
    (root / path).unlink(missing_ok=True)


def _commit_error(command: str, stderr: str) -> KbError:
    """Format a staging or commit failure with the command's error prefix."""
    detail = stderr.rstrip("\n")
    return KbError(
        f"{command}: commit failed: {detail}" if detail else f"{command}: commit failed:"
    )


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run Git in the content repository and capture its output."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

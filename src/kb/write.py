"""The shared protected file publication and single-path Git commit operation."""

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kb import commit, git, lock, observation, scratch, secrets
from kb.content_paths import fixed_directory
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
    fixed_directory(root, directory, command=command, create=False, optional=True)
    git_directory = lock.git_dir(root, command)
    backend = lock.default_backend(platform)
    with lock.write_lock(git_directory, wait, backend):
        scratch_directory = scratch.shared_directory(git_directory, command)
        found = secrets.findings(scratch_directory, scan_text)
        if found:
            raise KbError("\n".join(refusal_lines(found)))

        # The scanned record becomes the published file through a hard link, so it takes
        # the umask's mode rather than the scan file's owner-only mode.
        temporary = scratch.create_file(
            scratch_directory, "record-", ".md", text.encode("utf-8"), mode=0o666
        )
        try:
            name = _publish(root, directory, temporary, when, command)
            _commit(root, f"{directory}/{name}", subject, command)
        finally:
            temporary.unlink(missing_ok=True)
    return name


def project() -> str:
    """The top of the process's Git repository, or its working directory outside one."""
    here = Path.cwd()
    top = git.run(here, "rev-parse", "--show-toplevel")
    if top.returncode == 0:
        # Git prints C:/ paths on Windows; Path gives them the native separator.
        return str(Path(top.stdout.removesuffix("\n")))
    return str(here)


def _publish(root: Path, directory: str, temporary: Path, when: datetime, command: str) -> str:
    """Link the temporary file to a free timestamped name without replacing a target."""
    destination = fixed_directory(root, directory, command=command, create=True)
    assert destination is not None
    for _ in range(MAX_NAME_TRIES):
        name = observation.file_name(when, os.urandom(4).hex())
        target = destination / name
        if target.exists():
            continue
        try:
            os.link(temporary, target)
        except FileExistsError:
            continue
        return name
    raise KbError(f"{command}: no free file name in {directory}")


def _commit(root: Path, path: str, subject: str, command: str) -> None:
    """Commit one new file and reconcile an exception before any rollback."""
    previous_head, files = commit.save_new_files(root, (path,), command)
    try:
        result = git.run(root, "add", "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
        result = git.run(root, "commit", "-q", "-m", subject, "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
    except BaseException as error:
        inspection = commit.inspect(
            lambda: commit.prove_new_files(
                root,
                commit.identify(root, previous_head, subject, allow_unborn=previous_head is None),
                files,
            ),
            fallback="",
        )
        if inspection.outcome == "committed":
            raise
        if inspection.outcome == "unknown":
            message = commit.uncertain_message(command, path, "file and index", inspection.detail)
            raise KbError(message) from error
        _rollback(root, path, command)
        raise


def _rollback(root: Path, path: str, command: str) -> None:
    """Unstage the new file before deleting it; retain it if index cleanup fails."""
    detail = commit.unstage(root, (path,), method="remove")
    if detail is not None:
        raise KbError(commit.rollback_failed(command, (path,), detail))
    (root / path).unlink(missing_ok=True)


def _commit_error(command: str, stderr: str) -> KbError:
    """Format a staging or commit failure with the command's error prefix."""
    detail = stderr.rstrip("\n")
    return KbError(
        f"{command}: commit failed: {detail}" if detail else f"{command}: commit failed:"
    )


# Removed in step A4.
@dataclass(frozen=True)
class CommitSnapshot:
    """The content and HEAD state needed to identify this one-path commit."""

    head: str | None
    path: str
    repository_path: str
    content: bytes


# Removed in step A4.
def _commit_snapshot(root: Path, path: str, command: str) -> CommitSnapshot:
    head, (saved,) = commit.save_new_files(root, (path,), command)
    return CommitSnapshot(head, saved.path, saved.repository_path, saved.content)


# Removed in step A4.
def _commit_outcome(root: Path, snapshot: CommitSnapshot, subject: str) -> tuple[str, str]:
    identified = commit.identify(root, snapshot.head, subject, allow_unborn=snapshot.head is None)
    saved = commit.NewFile(snapshot.path, snapshot.repository_path, snapshot.content)
    inspection = commit.prove_new_files(root, identified, (saved,))
    return inspection.outcome, inspection.detail


# Removed in step A4.
def _unstage_paths(root: Path, paths: Sequence[str], command: str) -> str | None:
    detail = commit.unstage(root, paths, method="remove")
    return None if detail is None else commit.rollback_failed(command, paths, detail)

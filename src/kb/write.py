"""The shared protected file publication and single-path Git commit operation."""

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from kb import git_paths, lock, observation, scratch, secrets
from kb.content_paths import fixed_directory
from kb.errors import KbError

MAX_NAME_TRIES = 5
RefusalLines = Callable[[Sequence[tuple[str, int]]], list[str]]


@dataclass(frozen=True)
class CommitSnapshot:
    """The content and HEAD state needed to identify this one-path commit."""

    head: str | None
    path: str
    repository_path: str
    content: bytes


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
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=here,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
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
    snapshot = _commit_snapshot(root, path, command)
    try:
        result = _git(root, "add", "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
        result = _git(root, "commit", "-q", "-m", subject, "--", path)
        if result.returncode != 0:
            raise _commit_error(command, result.stderr)
    except BaseException as error:
        try:
            outcome, detail = _commit_outcome(root, snapshot, subject)
        except BaseException as inspection_error:
            outcome = "unknown"
            detail = str(inspection_error)
        if outcome == "committed":
            raise
        if outcome == "unknown":
            message = (
                f"{command}: commit outcome is uncertain for {path}; the file and index were "
                "preserved; inspect Git status and HEAD before retrying"
            )
            raise KbError(f"{message}: {detail}" if detail else message) from error
        _rollback(root, path, command)
        raise


def _commit_snapshot(root: Path, path: str, command: str) -> CommitSnapshot:
    """Save HEAD and the published bytes before staging the transaction path."""
    prefix = git_paths.repository_prefix(root, command)
    repository_path = git_paths.to_repository_path(path, prefix)
    head, error = _read_head(root, allow_unborn=True)
    if error is not None:
        raise KbError(f"{command}: cannot save commit state for {path}: {error}")

    if head is not None:
        result = _git(root, "ls-tree", "-z", "--full-tree", head, "--", repository_path)
        if result.returncode != 0:
            detail = result.stderr.rstrip("\n")
            raise KbError(
                f"{command}: cannot save commit state for {path}: "
                f"cannot inspect HEAD path{': ' + detail if detail else ''}"
            )
        if result.stdout:
            raise KbError(f"{command}: refusing to commit an existing HEAD path: {path}")

    staged = _git(root, "diff", "--cached", "--name-only", "-z", "--", path)
    if staged.returncode != 0:
        detail = staged.stderr.rstrip("\n")
        raise KbError(
            f"{command}: cannot save commit state for {path}: "
            f"cannot inspect the index{': ' + detail if detail else ''}"
        )
    if staged.stdout:
        raise KbError(f"{command}: refusing to commit an already staged path: {path}")

    try:
        content = (root / path).read_bytes()
    except OSError as error:
        raise KbError(f"{command}: cannot save commit state for {path}: {error}") from error
    return CommitSnapshot(head, path, repository_path, content)


def _read_head(root: Path, *, allow_unborn: bool) -> tuple[str | None, str | None]:
    """Read HEAD, recognizing an unborn branch only when its named reference is absent."""
    result = _git(root, "rev-parse", "--verify", "HEAD")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip(), None
    if allow_unborn:
        symbolic = _git(root, "symbolic-ref", "-q", "HEAD")
        if symbolic.returncode == 0 and symbolic.stdout.strip():
            reference = _git(root, "show-ref", "--verify", "--quiet", symbolic.stdout.strip())
            if reference.returncode == 1:
                return None, None
    detail = result.stderr.rstrip("\n")
    return None, detail or "Git did not return HEAD"


def _commit_outcome(root: Path, snapshot: CommitSnapshot, subject: str) -> tuple[str, str]:
    """Distinguish this committed path, a failed commit, and an outcome needing inspection."""
    head, error = _read_head(root, allow_unborn=snapshot.head is None)
    if error is not None:
        return "unknown", error
    if head == snapshot.head:
        return "failed", "HEAD is unchanged"
    assert head is not None

    metadata = _git(root, "show", "-s", "--format=%P%x00%s", head)
    if metadata.returncode != 0:
        return "unknown", _detail(metadata.stderr, "cannot inspect the new commit")
    fields = metadata.stdout.rstrip("\n").split("\0", 1)
    if len(fields) != 2:
        return "unknown", "Git returned malformed commit metadata"
    parents = fields[0].split()
    expected_parents = [] if snapshot.head is None else [snapshot.head]
    if parents != expected_parents or fields[1] != subject:
        return "unknown", "HEAD changed but does not identify this transaction's commit"

    changed = _git(
        root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        head,
        "--",
        f":(top,literal){snapshot.repository_path}",
    )
    if changed.returncode != 0:
        return "unknown", _detail(changed.stderr, "cannot inspect the new commit's paths")
    if snapshot.repository_path not in changed.stdout.splitlines():
        return "unknown", "the new commit does not contain the transaction path"

    head_content, head_error = _git_blob(root, f"{head}:{snapshot.repository_path}")
    if head_content is None:
        return "unknown", _detail(head_error, "cannot read the committed file")
    index_content, index_error = _git_blob(root, f":{snapshot.repository_path}")
    if index_content is None:
        return "unknown", _detail(index_error, "cannot read the indexed file")
    try:
        worktree_content = (root / snapshot.path).read_bytes()
    except OSError as error:
        return "unknown", f"cannot read the worktree file: {error}"

    expected = snapshot.content
    if head_content != expected or index_content != expected or worktree_content != expected:
        return "unknown", "HEAD, index, and worktree do not match the saved file bytes"
    return "committed", ""


def _detail(stderr: str, fallback: str) -> str:
    """The useful error line from a failed Git inspection, or a short fallback."""
    detail = stderr.rstrip("\n")
    return detail or fallback


def _rollback(root: Path, path: str, command: str) -> None:
    """Unstage the new file before deleting it; retain it if index cleanup fails."""
    error = _unstage_paths(root, (path,), command)
    if error is not None:
        raise KbError(error)
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


def _git_blob(root: Path, revision: str) -> tuple[bytes | None, str]:
    """Read one blob as raw bytes, or return None and Git's error text.

    Text mode would translate CRLF to LF on Windows and alter the content.
    """
    result = subprocess.run(
        ["git", "show", revision],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None, result.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return result.stdout, ""


def _unstage_paths(
    root: Path,
    paths: Sequence[str],
    command: str,
    run_git: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> str | None:
    """Remove only these paths from the index, reporting errors before callers delete files."""
    if not paths:
        return None
    git = _git if run_git is None else run_git
    result = git(root, "ls-files", "-z", "--", *paths)
    if result.returncode == 0 and result.stdout:
        # A rejecting hook may have changed a staged file; force only these paths out of the index.
        result = git(root, "rm", "-q", "-f", "--cached", "--ignore-unmatch", "--", *paths)
    if result.returncode == 0:
        return None
    detail = result.stderr.rstrip("\n")
    listed = ", ".join(paths)
    message = (
        f"{command}: rollback failed for {listed}; files were preserved; "
        "inspect Git status before retrying"
    )
    return f"{message}: {detail}" if detail else message

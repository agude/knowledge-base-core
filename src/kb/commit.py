"""Commit new content and recover from a failed or interrupted commit.

Every writer that commits follows this rule:

1. Save state before staging.
2. On any failure or exception, inspect Git before cleaning anything up.
3. If the commit is proven to exist (**committed**): never clean up.
4. If Git cannot be inspected or the result is ambiguous (**unknown**): clean nothing;
   report that the files and index were kept.
5. If the commit is proven not to exist (**failed**): unstage; then, for new files only,
   delete them, and only if unstaging succeeded.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kb import git, git_paths
from kb.errors import KbError

Outcome = Literal["committed", "failed", "unknown"]
INTERRUPTED = "commit outcome inspection was interrupted"


@dataclass(frozen=True)
class Inspection:
    """What Git shows after a commit attempt, and why when it is not committed."""

    outcome: Outcome
    head: str | None
    detail: str


@dataclass(frozen=True)
class NewFile:
    """A new file's content-relative path, repository path, and bytes before staging."""

    path: str
    repository_path: str
    content: bytes


def read_head(
    root: Path,
    *,
    allow_unborn: bool,
    optional_locks: bool = True,
    fallback: str = "Git did not return HEAD",
) -> tuple[str | None, str | None]:
    """Read HEAD, recognizing an unborn branch only when its named reference is absent.

    Returns (head, None), (None, None) for an unborn branch, or (None, error text).
    """
    result = git.run(root, "rev-parse", "--verify", "HEAD", optional_locks=optional_locks)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip(), None
    if allow_unborn:
        symbolic = git.run(root, "symbolic-ref", "-q", "HEAD", optional_locks=optional_locks)
        if symbolic.returncode == 0 and symbolic.stdout.strip():
            reference = git.run(
                root,
                "show-ref",
                "--verify",
                "--quiet",
                symbolic.stdout.strip(),
                optional_locks=optional_locks,
            )
            if reference.returncode == 1:
                return None, None
    return None, _detail(result.stderr, fallback)


def save_new_files(
    root: Path, paths: Sequence[str], command: str
) -> tuple[str | None, tuple[NewFile, ...]]:
    """Save HEAD and each new file's bytes, refusing a path in HEAD or already staged."""
    prefix = git_paths.repository_prefix(root, command)
    head, error = read_head(root, allow_unborn=True)
    if error is not None:
        first = paths[0] if paths else ""
        raise KbError(f"{command}: cannot save commit state for {first}: {error}")
    return head, tuple(_save_new_file(root, head, path, prefix, command) for path in paths)


def _save_new_file(root: Path, head: str | None, path: str, prefix: str, command: str) -> NewFile:
    repository_path = git_paths.to_repository_path(path, prefix)
    if head is not None:
        result = git.run(root, "ls-tree", "-z", "--full-tree", head, "--", repository_path)
        if result.returncode != 0:
            detail = result.stderr.rstrip("\n")
            raise KbError(
                f"{command}: cannot save commit state for {path}: "
                f"cannot inspect HEAD path{': ' + detail if detail else ''}"
            )
        if result.stdout:
            raise KbError(f"{command}: refusing to commit an existing HEAD path: {path}")

    staged = git.run(root, "diff", "--cached", "--name-only", "-z", "--", path)
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
    return NewFile(path, repository_path, content)


def identify(
    root: Path,
    previous_head: str | None,
    subject: str,
    *,
    allow_unborn: bool,
    optional_locks: bool = True,
    commit_name: str = "this transaction's commit",
    head_fallback: str = "Git did not return HEAD",
) -> Inspection:
    """Whether HEAD moved to one new commit with this subject on the saved HEAD."""
    head, error = read_head(
        root, allow_unborn=allow_unborn, optional_locks=optional_locks, fallback=head_fallback
    )
    if error is not None:
        return Inspection("unknown", None, error)
    if head == previous_head:
        return Inspection("failed", None, "HEAD is unchanged")
    assert head is not None

    metadata = git.run(root, "show", "-s", "--format=%P%x00%s", head, optional_locks=optional_locks)
    if metadata.returncode != 0:
        return Inspection(
            "unknown", None, _detail(metadata.stderr, "cannot inspect the new commit")
        )
    fields = metadata.stdout.rstrip("\n").split("\0", 1)
    if len(fields) != 2:
        return Inspection("unknown", None, "Git returned malformed commit metadata")
    expected_parents = [] if previous_head is None else [previous_head]
    if fields[0].split() != expected_parents or fields[1] != subject:
        return Inspection("unknown", None, f"HEAD changed but does not identify {commit_name}")
    return Inspection("committed", head, "")


def prove_new_files(root: Path, inspection: Inspection, files: Sequence[NewFile]) -> Inspection:
    """Keep a committed inspection only when each file's bytes match in HEAD, index, and worktree."""
    if inspection.outcome != "committed":
        return inspection
    assert inspection.head is not None
    for new_file in files:
        detail = _new_file_difference(root, inspection.head, new_file)
        if detail is not None:
            return Inspection("unknown", None, detail)
    return inspection


def _new_file_difference(root: Path, head: str, new_file: NewFile) -> str | None:
    """Why the commit does not hold this file as saved, or None when it does."""
    changed = git.run(
        root,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        head,
        "--",
        f":(top,literal){new_file.repository_path}",
    )
    if changed.returncode != 0:
        return _detail(changed.stderr, "cannot inspect the new commit's paths")
    if new_file.repository_path not in changed.stdout.splitlines():
        return "the new commit does not contain the transaction path"

    head_content, head_error = _blob(root, f"{head}:{new_file.repository_path}")
    if head_content is None:
        return _detail(head_error, "cannot read the committed file")
    index_content, index_error = _blob(root, f":{new_file.repository_path}")
    if index_content is None:
        return _detail(index_error, "cannot read the indexed file")
    try:
        worktree_content = (root / new_file.path).read_bytes()
    except OSError as error:
        return f"cannot read the worktree file: {error}"

    expected = new_file.content
    if head_content != expected or index_content != expected or worktree_content != expected:
        return "HEAD, index, and worktree do not match the saved file bytes"
    return None


def prove_tree(root: Path, inspection: Inspection, expected_tree: str) -> Inspection:
    """Keep a committed inspection only when HEAD's tree, the index, and a clean worktree agree."""
    if inspection.outcome != "committed":
        return inspection
    head = inspection.head
    assert head is not None
    tree = git.run(root, "rev-parse", "--verify", f"{head}^{{tree}}", optional_locks=False)
    if tree.returncode != 0 or tree.stdout.strip() != expected_tree:
        detail = tree.stderr.rstrip("\n") or "the new commit tree differs from the staged set"
        return Inspection("unknown", None, detail)
    index = git.run(root, "write-tree", optional_locks=False)
    if index.returncode != 0 or index.stdout.strip() != expected_tree:
        detail = index.stderr.rstrip("\n") or "the index differs from the staged set"
        return Inspection("unknown", None, detail)
    status = git.run(
        root, "status", "--porcelain=v1", "-z", "--untracked-files=all", optional_locks=False
    )
    if status.returncode != 0 or status.stdout:
        detail = status.stderr.rstrip("\n") or "the worktree differs from the committed publication"
        return Inspection("unknown", None, detail)
    return inspection


def inspect(check: Callable[[], Inspection], *, fallback: str = INTERRUPTED) -> Inspection:
    """Run an inspection; an exception from it, an interrupt included, makes the outcome unknown."""
    try:
        return check()
    except BaseException as error:
        return Inspection("unknown", None, str(error) or fallback)


def unstage(root: Path, paths: Sequence[str], *, method: Literal["remove", "reset"]) -> str | None:
    """Remove only these paths from the index, keeping worktree bytes. Returns Git's error text.

    "remove" serves new files: it changes the index only when a path is staged, so a locked
    index with nothing staged is not a rollback failure, and it forces out a path a rejecting
    hook changed. "reset" serves curate's edits, deletions, and renames, and always takes the
    index lock.
    """
    if not paths:
        return None
    if method == "remove":
        result = git.run(root, "ls-files", "-z", "--", *paths)
        if result.returncode == 0 and result.stdout:
            result = git.run(root, "rm", "-q", "-f", "--cached", "--ignore-unmatch", "--", *paths)
    else:
        result = git.run(
            root,
            "--literal-pathspecs",
            "reset",
            "-q",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            input_text="".join(f"{path}\0" for path in paths),
        )
    if result.returncode == 0:
        return None
    return result.stderr.rstrip("\n")


def rollback_failed(command: str, paths: Sequence[str], detail: str) -> str:
    """The report for new files kept because unstaging them failed."""
    listed = ", ".join(paths)
    message = (
        f"{command}: rollback failed for {listed}; files were preserved; "
        "inspect Git status before retrying"
    )
    return f"{message}: {detail}" if detail else message


def committed_with_error(detail: str) -> str:
    """The warning for a commit that exists although the commit command exited nonzero."""
    clause = "committed, but Git reported an error"
    return f"{clause}: {detail}" if detail else clause


def uncertain_message(command: str, listing: str, preserved: str, detail: str) -> str:
    """The report for an unknown outcome, naming what was kept and how to recover."""
    message = (
        f"{command}: commit outcome is uncertain for {listing}; the {preserved} were preserved; "
        "inspect Git status and HEAD before retrying"
    )
    return f"{message}: {detail}" if detail else message


def _blob(root: Path, revision: str) -> tuple[bytes | None, str]:
    """Read one blob as raw bytes, or return None and Git's error text.

    Text mode would translate CRLF to LF on Windows and alter the content.
    """
    result = git.run_bytes(root, "show", revision)
    if result.returncode != 0:
        return None, result.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return result.stdout, ""


def _detail(stderr: str, fallback: str) -> str:
    """The useful error line from a failed Git inspection, or a short fallback."""
    return stderr.rstrip("\n") or fallback

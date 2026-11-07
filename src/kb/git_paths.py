"""Convert between paths relative to Git's worktree and the configured content root."""

import posixpath
import subprocess
from pathlib import Path

from kb.errors import KbError


def repository_prefix(content: Path, command: str) -> str:
    """Return the repository-root prefix of a content directory, including its trailing slash."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=content,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise KbError(f"{command}: the content repository is not a git repository: {content}")
    return result.stdout.removesuffix("\n")


def to_content_path(repository_path: str, prefix: str) -> str:
    """Convert a repository-relative path, keeping outside paths visibly outside the content root."""
    if not prefix:
        return repository_path
    directory = prefix.removesuffix("/")
    if repository_path == directory:
        return "."
    if repository_path.startswith(prefix):
        return repository_path[len(prefix) :]
    return posixpath.relpath(repository_path, directory)


def to_repository_path(content_path: str, prefix: str) -> str:
    """Convert a content-relative path to the repository-relative path used by HEAD:path."""
    if content_path == ".." or content_path.startswith("../"):
        raise ValueError("content path must not escape its root")
    return f"{prefix}{content_path}"

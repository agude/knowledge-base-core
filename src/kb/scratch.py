"""Create owned temporary files in the common Git scratch directory."""

import os
from pathlib import Path

from kb.errors import KbError

TMP = "kb-tmp"
MAX_NAME_TRIES = 5


def shared_directory(git_directory: Path, command: str) -> Path:
    """Create and validate the scratch directory inside the common Git directory."""
    scratch = git_directory / TMP
    if scratch.is_symlink():
        raise KbError(f"{command}: temporary directory is a symlink: {scratch}")
    scratch.mkdir(parents=True, exist_ok=True)
    if scratch.is_symlink():
        raise KbError(f"{command}: temporary directory is a symlink: {scratch}")
    if not scratch.resolve().is_relative_to(git_directory.resolve()):
        raise KbError(f"{command}: temporary directory escapes the Git directory")
    return scratch


def create_file(
    directory: Path,
    prefix: str,
    suffix: str,
    content: bytes,
    *,
    mode: int = 0o600,
    flush: bool = False,
) -> Path:
    """Exclusively create a private file, retrying occupied names and cleaning owned files."""
    if directory.is_symlink():
        raise OSError(f"temporary directory is a symlink: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise NotADirectoryError(f"temporary directory is unsafe: {directory}")

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for _ in range(MAX_NAME_TRIES):
        path = directory / f"{prefix}{os.urandom(8).hex()}{suffix}"
        try:
            descriptor = os.open(path, flags, mode)
        except FileExistsError:
            continue
        try:
            handle = os.fdopen(descriptor, "wb")
        except BaseException:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        try:
            with handle:
                handle.write(content)
                if flush:
                    handle.flush()
                    os.fsync(handle.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    raise FileExistsError(f"could not create a unique temporary file in {directory}")

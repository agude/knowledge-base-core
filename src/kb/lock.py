"""The write lock: a kernel lock that serializes kb writers.

A write takes an exclusive lock on <git dir>/kb.lock. The kernel releases it when the
process exits, so it needs no stale-lock logic.
"""

import importlib
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

from kb.errors import KbError
from kb.platform import WINDOWS

DEFAULT_WAIT = 30
POLL_SECONDS = 0.1
KERNEL_LOCK = "kb.lock"

Clock = Callable[[], float]
Pause = Callable[[float], None]


class InvalidWait(ValueError):
    """KB_LOCK_WAIT is not a non-negative integer. The command reports it as a usage error."""


class LockBusy(Exception):
    """A lock stayed held for the whole wait. waited is the configured wait, in seconds."""

    def __init__(self, waited: int) -> None:
        super().__init__(f"waited {waited}s for the lock")
        self.waited = waited


class FcntlModule(Protocol):
    """The parts of the fcntl module that the POSIX backend uses."""

    LOCK_EX: int
    LOCK_NB: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int, /) -> None: ...


class MsvcrtModule(Protocol):
    """The parts of the msvcrt module that the Windows backend uses."""

    LK_NBLCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


class Backend(Protocol):
    """The platform's exclusive file lock."""

    def try_lock(self, fd: int) -> bool:
        """Take the lock on fd without waiting. False means another process holds it."""
        ...

    def unlock(self, fd: int) -> None:
        """Release the lock that try_lock took on fd."""
        ...


class FlockBackend:
    """The POSIX backend: flock on the lock file's descriptor."""

    def __init__(self, module: FcntlModule) -> None:
        self._module = module

    def try_lock(self, fd: int) -> bool:
        try:
            self._module.flock(fd, self._module.LOCK_EX | self._module.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def unlock(self, fd: int) -> None:
        self._module.flock(fd, self._module.LOCK_UN)


class MsvcrtBackend:
    """The Windows backend: msvcrt.locking on byte 0 of the lock file."""

    def __init__(self, module: MsvcrtModule) -> None:
        self._module = module

    def try_lock(self, fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            self._module.locking(fd, self._module.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def unlock(self, fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        self._module.locking(fd, self._module.LK_UNLCK, 1)


def parse_wait(value: str | None) -> int:
    """KB_LOCK_WAIT in seconds: the default when unset or empty, else a non-negative integer."""
    if not value:
        return DEFAULT_WAIT
    if value.isascii() and value.isdigit():
        return int(value)
    raise InvalidWait(value)


def git_dir(content: Path, command: str = "observe") -> Path:
    """The git directory of the content repository, as git reports it.

    Raises KbError when the content root is not inside a git repository.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=content,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise KbError(f"{command}: the content repository is not a git repository: {content}")
    return (content / result.stdout.removesuffix("\n")).resolve()


def git_dir_path(content: Path, command: str) -> Path:
    """Find a worktree's common Git directory from its metadata without running Git."""
    marker = content / ".git"
    if marker.is_dir():
        git = marker.resolve()
    elif marker.is_file():
        line = marker.read_text(encoding="utf-8").removesuffix("\n").removesuffix("\r")
        if not line.startswith("gitdir: "):
            raise KbError(f"{command}: cannot locate the Git directory for {content}")
        git = Path(line.removeprefix("gitdir: "))
        if not git.is_absolute():
            git = marker.parent / git
        git = git.resolve()
        common = git / "commondir"
        if common.is_file():
            relative = Path(common.read_text(encoding="utf-8").strip())
            git = (git / relative).resolve() if not relative.is_absolute() else relative.resolve()
    else:
        raise KbError(f"{command}: cannot locate the Git directory for {content}")
    if not git.is_dir():
        raise KbError(f"{command}: cannot locate the Git directory for {content}")
    return git


def default_backend(
    platform: str, import_module: Callable[[str], ModuleType] = importlib.import_module
) -> Backend:
    """The backend for a platform. Only that platform's lock module is imported."""
    if platform == WINDOWS:
        return MsvcrtBackend(cast(MsvcrtModule, import_module("msvcrt")))
    return FlockBackend(cast(FcntlModule, import_module("fcntl")))


def acquire_kernel(
    path: Path,
    backend: Backend,
    wait: int,
    clock: Clock = time.monotonic,
    pause: Pause = time.sleep,
) -> int:
    """Take the kernel lock in the file at path, polling until wait seconds have passed.

    Returns the file descriptor, which holds the lock until it is closed. Raises LockBusy
    when another process holds the lock for the whole wait.
    """
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        deadline = clock() + wait
        while not backend.try_lock(fd):
            if clock() >= deadline:
                raise LockBusy(wait)
            pause(POLL_SECONDS)
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def write_lock(
    git: Path,
    wait: int,
    backend: Backend,
    clock: Clock = time.monotonic,
    pause: Pause = time.sleep,
) -> Iterator[None]:
    """Hold the write lock for the duration of the block.

    Takes the kernel lock in git/kb.lock and releases it on every exit, including an
    exception. Raises LockBusy when the lock stays held for wait seconds.
    """
    fd = acquire_kernel(git / KERNEL_LOCK, backend, wait, clock, pause)
    try:
        yield
    finally:
        try:
            backend.unlock(fd)
        finally:
            os.close(fd)

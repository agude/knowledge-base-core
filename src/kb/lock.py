"""The write lock: a kernel lock that serializes kb writers, and the old scripts' lock that kb shares.

A write takes two locks. The kernel lock is an exclusive lock on <git dir>/kb.lock.
The kernel releases it when the process exits, so it needs no stale-lock logic. The
legacy lock is the directory <content>/.observe.lock that the old scripts take with
their acquire_lock. kb takes it too, so that kb and the old scripts exclude each other
until cutover. The legacy lock is POSIX only: the old scripts run only on POSIX, and
its liveness check, os.kill(pid, 0), terminates the process on Windows.
"""

import importlib
import os
import shutil
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
LEGACY_LOCK = ".observe.lock"

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
    """The platform's exclusive file lock, and whether the legacy lock is taken with it."""

    legacy_lock: bool

    def try_lock(self, fd: int) -> bool:
        """Take the lock on fd without waiting. False means another process holds it."""
        ...

    def unlock(self, fd: int) -> None:
        """Release the lock that try_lock took on fd."""
        ...


class FlockBackend:
    """The POSIX backend: flock on the lock file's descriptor. It also takes the legacy lock."""

    legacy_lock = True

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
    """The Windows backend: msvcrt.locking on byte 0 of the lock file. It takes no legacy lock."""

    legacy_lock = False

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


def take_legacy_lock(
    content: Path,
    wait: int,
    clock: Clock = time.monotonic,
    pause: Pause = time.sleep,
) -> None:
    """Take the old scripts' lock the way their acquire_lock does. Raises LockBusy.

    Deleted at cutover, with the old scripts' lock. A directory whose pid file names a
    dead process is stale: it is removed and taken at once. Otherwise the call polls
    every POLL_SECONDS until wait seconds have passed.
    """
    lockdir = content / LEGACY_LOCK
    deadline = clock() + wait
    while True:
        try:
            lockdir.mkdir()
        except FileExistsError:
            if _owner_is_dead(lockdir / "pid"):
                shutil.rmtree(lockdir, ignore_errors=True)
                if not lockdir.exists():
                    continue
            if clock() >= deadline:
                raise LockBusy(wait) from None
            pause(POLL_SECONDS)
            continue
        (lockdir / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
        return


def release_legacy_lock(content: Path) -> None:
    """Remove the old scripts' lock directory. Deleted at cutover, with take_legacy_lock."""
    shutil.rmtree(content / LEGACY_LOCK, ignore_errors=True)


@contextmanager
def write_lock(
    git: Path,
    content: Path,
    wait: int,
    backend: Backend,
    clock: Clock = time.monotonic,
    pause: Pause = time.sleep,
) -> Iterator[None]:
    """Hold the write lock for the duration of the block.

    Takes the kernel lock in git/kb.lock, then the legacy lock when the backend has one.
    Releases them in the reverse order on every exit, including an exception. Raises
    LockBusy when a lock stays held for wait seconds.
    """
    fd = acquire_kernel(git / KERNEL_LOCK, backend, wait, clock, pause)
    try:
        if backend.legacy_lock:
            take_legacy_lock(content, wait, clock, pause)
            try:
                yield
            finally:
                release_legacy_lock(content)
        else:
            yield
    finally:
        try:
            backend.unlock(fd)
        finally:
            os.close(fd)


def _owner_is_dead(pidfile: Path) -> bool:
    """True when the pid file names a process that is not running.

    A missing or empty file names no owner yet, so the lock is not stale. Text that is
    not a process id names no process.
    """
    try:
        text = pidfile.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return False
    if not text:
        return False
    if not (text.isascii() and text.isdigit()):
        return True
    return not _process_exists(int(text))


def _process_exists(pid: int) -> bool:
    """Whether a process with this id is running, judged by os.kill(pid, 0) on POSIX."""
    if pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OverflowError:
        return False
    return True

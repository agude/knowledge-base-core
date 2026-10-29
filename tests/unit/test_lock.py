"""Tests of the write lock: the wait setting, the kernel lock, and release."""

import errno
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

from kb import lock
from kb.errors import KbError
from kb.lock import FlockBackend, InvalidWait, LockBusy, MsvcrtBackend


class FakeClock:
    """A clock that moves only when pause is called, so waits take no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.pauses: list[float] = []

    def __call__(self) -> float:
        return self.now

    def pause(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now = round(self.now + seconds, 6)


class FakeFcntl:
    """The parts of the fcntl module that the POSIX backend uses."""

    LOCK_EX = 2
    LOCK_NB = 4
    LOCK_UN = 8

    def __init__(self, busy: int = 0, fail: OSError | None = None) -> None:
        self.busy = busy
        self.fail = fail
        self.calls: list[tuple[int, int]] = []

    def flock(self, fd: int, operation: int, /) -> None:
        self.calls.append((fd, operation))
        if self.fail is not None:
            raise self.fail
        if operation & self.LOCK_NB and self.busy:
            self.busy -= 1
            raise BlockingIOError(errno.EWOULDBLOCK, "busy")


class FakeMsvcrt:
    """The parts of the msvcrt module that the Windows backend uses."""

    LK_NBLCK = 2
    LK_UNLCK = 0

    def __init__(self, busy: int = 0) -> None:
        self.busy = busy
        self.calls: list[tuple[int, int, int]] = []

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None:
        self.calls.append((fd, mode, nbytes))
        if mode == self.LK_NBLCK and self.busy:
            self.busy -= 1
            raise OSError(errno.EACCES, "locked")


class FakeBackend:
    """A backend whose lock is busy for a number of attempts, then free."""

    def __init__(self, busy: int = 0, error: Exception | None = None) -> None:
        self.busy = busy
        self.error = error
        self.unlocked: list[int] = []

    def try_lock(self, fd: int) -> bool:
        if self.error is not None:
            raise self.error
        if self.busy:
            self.busy -= 1
            return False
        return True

    def unlock(self, fd: int) -> None:
        self.unlocked.append(fd)


def make_repo(path: Path) -> Path:
    """A git repository with no commits, at path."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_unset_or_empty_wait_is_the_default() -> None:
    assert lock.parse_wait(None) == 30
    assert lock.parse_wait("") == 30


def test_wait_is_a_non_negative_integer() -> None:
    assert lock.parse_wait("0") == 0
    assert lock.parse_wait("12") == 12


@pytest.mark.parametrize("value", ["1.5", "-1", "x", " 3", "+3", "٣"])
def test_any_other_wait_is_refused(value: str) -> None:
    with pytest.raises(InvalidWait):
        lock.parse_wait(value)


def test_git_dir_is_the_git_directory_of_the_repository(tmp_path: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    assert lock.git_dir(repo) == (repo / ".git").resolve()


def test_git_dir_refuses_a_directory_outside_any_repository(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="not a git repository"):
        lock.git_dir(tmp_path)


def test_git_dir_path_reads_worktree_metadata_without_running_git(tmp_path: Path) -> None:
    content = tmp_path / "worktree"
    git = tmp_path / ".git"
    worktree_git = git / "worktrees" / "worktree"
    content.mkdir()
    worktree_git.mkdir(parents=True)
    (content / ".git").write_text(f"gitdir: {worktree_git}\n", encoding="utf-8")
    (worktree_git / "commondir").write_text("../..\n", encoding="utf-8")

    assert lock.git_dir_path(content, "verify") == git.resolve()


def test_flock_backend_takes_then_releases_an_exclusive_lock() -> None:
    module = FakeFcntl()
    backend = FlockBackend(module)
    assert backend.try_lock(7)
    backend.unlock(7)
    assert module.calls == [(7, FakeFcntl.LOCK_EX | FakeFcntl.LOCK_NB), (7, FakeFcntl.LOCK_UN)]


def test_flock_backend_reports_contention_as_not_taken() -> None:
    assert not FlockBackend(FakeFcntl(busy=1)).try_lock(7)


def test_flock_backend_passes_other_errors_through() -> None:
    backend = FlockBackend(FakeFcntl(fail=OSError(errno.EBADF, "bad descriptor")))
    with pytest.raises(OSError, match="bad descriptor"):
        backend.try_lock(7)


def test_msvcrt_backend_locks_byte_zero_from_the_start(tmp_path: Path) -> None:
    module = FakeMsvcrt()
    fd = os.open(tmp_path / "kb.lock", os.O_RDWR | os.O_CREAT, 0o666)
    try:
        os.lseek(fd, 5, os.SEEK_SET)
        assert MsvcrtBackend(module).try_lock(fd)
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        assert module.calls == [(fd, FakeMsvcrt.LK_NBLCK, 1)]
    finally:
        os.close(fd)


def test_msvcrt_backend_reports_contention_as_not_taken(tmp_path: Path) -> None:
    fd = os.open(tmp_path / "kb.lock", os.O_RDWR | os.O_CREAT, 0o666)
    try:
        backend = MsvcrtBackend(FakeMsvcrt(busy=1))
        assert not backend.try_lock(fd)
        assert backend.try_lock(fd)
    finally:
        os.close(fd)


def test_msvcrt_backend_unlocks_byte_zero(tmp_path: Path) -> None:
    module = FakeMsvcrt()
    fd = os.open(tmp_path / "kb.lock", os.O_RDWR | os.O_CREAT, 0o666)
    try:
        MsvcrtBackend(module).unlock(fd)
        assert module.calls == [(fd, FakeMsvcrt.LK_UNLCK, 1)]
    finally:
        os.close(fd)


def test_default_backend_imports_only_the_module_for_its_platform() -> None:
    fakes: dict[str, object] = {"fcntl": FakeFcntl(), "msvcrt": FakeMsvcrt()}
    imported: list[str] = []

    def record(name: str) -> ModuleType:
        imported.append(name)
        return cast(ModuleType, fakes[name])

    posix = lock.default_backend("linux", record)
    assert isinstance(posix, FlockBackend)
    assert imported == ["fcntl"]
    windows = lock.default_backend("win32", record)
    assert isinstance(windows, MsvcrtBackend)
    assert imported == ["fcntl", "msvcrt"]


def test_kernel_lock_polls_until_the_lock_is_free(tmp_path: Path) -> None:
    clock = FakeClock()
    path = tmp_path / "kb.lock"
    fd = lock.acquire_kernel(path, FakeBackend(busy=3), 1, clock, clock.pause)
    try:
        assert clock.pauses == [0.1, 0.1, 0.1]
        assert path.is_file()
    finally:
        os.close(fd)


def test_kernel_lock_gives_up_when_the_wait_has_passed(tmp_path: Path) -> None:
    clock = FakeClock()
    with pytest.raises(LockBusy) as busy:
        lock.acquire_kernel(tmp_path / "kb.lock", FakeBackend(busy=10**6), 1, clock, clock.pause)
    assert busy.value.waited == 1
    assert len(clock.pauses) == 10


def test_kernel_lock_with_no_wait_tries_once(tmp_path: Path) -> None:
    clock = FakeClock()
    with pytest.raises(LockBusy):
        lock.acquire_kernel(tmp_path / "kb.lock", FakeBackend(busy=1), 0, clock, clock.pause)
    assert clock.pauses == []


def test_kernel_lock_closes_its_descriptor_on_any_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[int] = []
    real_close = os.close

    def record(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "close", record)
    with pytest.raises(RuntimeError, match="interrupted"):
        lock.acquire_kernel(tmp_path / "kb.lock", FakeBackend(error=RuntimeError("interrupted")), 1)
    assert len(closed) == 1


def test_write_lock_holds_the_kernel_lock_then_releases_it(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    backend = lock.default_backend(sys.platform)
    with lock.write_lock(git, 0, backend):
        assert (git / lock.KERNEL_LOCK).is_file()
    with lock.write_lock(git, 0, backend):
        pass


def test_write_lock_releases_the_kernel_lock_when_the_block_raises(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    backend = lock.default_backend(sys.platform)
    with pytest.raises(RuntimeError, match="stopped"), lock.write_lock(git, 0, backend):
        raise RuntimeError("stopped")
    with lock.write_lock(git, 0, backend):
        pass


def test_write_lock_takes_only_the_kernel_lock(tmp_path: Path) -> None:
    git = tmp_path / "git"
    git.mkdir()
    backend = FakeBackend()
    with lock.write_lock(git, 0, backend):
        assert sorted(entry.name for entry in git.iterdir()) == [lock.KERNEL_LOCK]
    assert len(backend.unlocked) == 1


def test_write_lock_refuses_when_the_kernel_lock_stays_busy(tmp_path: Path) -> None:
    git = tmp_path / "git"
    git.mkdir()
    with pytest.raises(LockBusy), lock.write_lock(git, 0, FakeBackend(busy=1)):
        pass


def test_git_dir_path_rejects_a_gitfile_without_a_gitdir_line(tmp_path: Path) -> None:
    content = tmp_path / "worktree"
    content.mkdir()
    (content / ".git").write_text("not a gitfile\n", encoding="utf-8")

    with pytest.raises(KbError, match="cannot locate the Git directory"):
        lock.git_dir_path(content, "verify")


def test_git_dir_path_resolves_a_relative_gitdir(tmp_path: Path) -> None:
    content = tmp_path / "worktree"
    content.mkdir()
    (tmp_path / "git").mkdir()
    (content / ".git").write_text("gitdir: ../git\n", encoding="utf-8")

    assert lock.git_dir_path(content, "verify") == (tmp_path / "git").resolve()


def test_git_dir_path_rejects_a_gitdir_that_does_not_exist(tmp_path: Path) -> None:
    content = tmp_path / "worktree"
    content.mkdir()
    (content / ".git").write_text(f"gitdir: {tmp_path / 'absent'}\n", encoding="utf-8")

    with pytest.raises(KbError, match="cannot locate the Git directory"):
        lock.git_dir_path(content, "verify")


def test_git_dir_path_rejects_a_root_without_git_metadata(tmp_path: Path) -> None:
    with pytest.raises(KbError, match="cannot locate the Git directory"):
        lock.git_dir_path(tmp_path, "verify")

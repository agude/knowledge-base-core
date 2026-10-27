"""Tests of the write lock: the wait setting, the kernel lock, the legacy lock, and release."""

import errno
import os
import shutil
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

    def __init__(self, busy: int = 0, error: Exception | None = None, legacy: bool = True) -> None:
        self.busy = busy
        self.error = error
        self.legacy_lock = legacy
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


def dead_pid() -> int:
    """The id of a process that has already exited."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=30)
    return child.pid


def legacy_dir(content: Path) -> Path:
    """The old scripts' lock directory under a content root."""
    return content / ".observe.lock"


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


def test_take_legacy_lock_writes_our_pid_and_release_removes_it(tmp_path: Path) -> None:
    lock.take_legacy_lock(tmp_path, 0)
    assert (legacy_dir(tmp_path) / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"
    lock.release_legacy_lock(tmp_path)
    assert not legacy_dir(tmp_path).exists()


def test_legacy_lock_held_by_a_live_process_is_waited_for_then_refused(tmp_path: Path) -> None:
    clock = FakeClock()
    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    with pytest.raises(LockBusy) as busy:
        lock.take_legacy_lock(tmp_path, 1, clock, clock.pause)
    assert busy.value.waited == 1
    assert len(clock.pauses) == 10
    assert (legacy_dir(tmp_path) / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"


def test_legacy_lock_without_a_pid_file_is_not_stale(tmp_path: Path) -> None:
    legacy_dir(tmp_path).mkdir()
    with pytest.raises(LockBusy):
        lock.take_legacy_lock(tmp_path, 0)
    assert legacy_dir(tmp_path).is_dir()


def test_legacy_lock_with_an_empty_pid_file_is_not_stale(tmp_path: Path) -> None:
    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text("\n", encoding="utf-8")
    with pytest.raises(LockBusy):
        lock.take_legacy_lock(tmp_path, 0)
    assert legacy_dir(tmp_path).is_dir()


def test_legacy_lock_left_by_a_dead_process_is_removed_and_taken(tmp_path: Path) -> None:
    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text(f"{dead_pid()}\n", encoding="utf-8")
    lock.take_legacy_lock(tmp_path, 0)
    assert (legacy_dir(tmp_path) / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"


@pytest.mark.parametrize("owner", ["not a pid\n", "-5\n", "0\n", "9" * 30 + "\n"])
def test_legacy_lock_naming_no_process_is_stale(tmp_path: Path, owner: str) -> None:
    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text(owner, encoding="utf-8")
    lock.take_legacy_lock(tmp_path, 0)
    assert (legacy_dir(tmp_path) / "pid").read_text(encoding="utf-8") == f"{os.getpid()}\n"


def test_a_stale_lock_that_cannot_be_removed_is_waited_for_then_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text(f"{dead_pid()}\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "rmtree", lambda path, ignore_errors: None)
    with pytest.raises(LockBusy):
        lock.take_legacy_lock(tmp_path, 0)
    assert legacy_dir(tmp_path).is_dir()


def test_a_process_owned_by_another_user_counts_as_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied(pid: int, signal: int) -> None:
        raise PermissionError(errno.EPERM, "not permitted")

    legacy_dir(tmp_path).mkdir()
    (legacy_dir(tmp_path) / "pid").write_text("4242\n", encoding="utf-8")
    monkeypatch.setattr(os, "kill", denied)
    with pytest.raises(LockBusy):
        lock.take_legacy_lock(tmp_path, 0)
    assert legacy_dir(tmp_path).is_dir()


def test_release_tolerates_a_missing_legacy_lock(tmp_path: Path) -> None:
    lock.release_legacy_lock(tmp_path)
    assert not legacy_dir(tmp_path).exists()


def test_write_lock_holds_both_locks_then_releases_them(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    content = tmp_path / "repo"
    backend = lock.default_backend("linux")
    with lock.write_lock(git, content, 0, backend):
        assert (legacy_dir(content) / "pid").is_file()
    assert not legacy_dir(content).exists()
    with lock.write_lock(git, content, 0, backend):
        pass


def test_write_lock_releases_both_locks_when_the_block_raises(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    content = tmp_path / "repo"
    backend = lock.default_backend("linux")
    with pytest.raises(RuntimeError, match="stopped"), lock.write_lock(git, content, 0, backend):
        raise RuntimeError("stopped")
    assert not legacy_dir(content).exists()
    with lock.write_lock(git, content, 0, backend):
        pass


def test_write_lock_takes_only_the_kernel_lock_without_a_legacy_lock(tmp_path: Path) -> None:
    git = tmp_path / "git"
    git.mkdir()
    content = tmp_path / "content"
    content.mkdir()
    backend = FakeBackend(legacy=False)
    with lock.write_lock(git, content, 0, backend):
        assert not legacy_dir(content).exists()
    assert len(backend.unlocked) == 1


def test_write_lock_takes_no_legacy_lock_while_the_kernel_lock_is_busy(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    content = tmp_path / "repo"
    backend = lock.default_backend("linux")
    held = lock.acquire_kernel(git / "kb.lock", backend, 0)
    try:
        with pytest.raises(LockBusy), lock.write_lock(git, content, 0, backend):
            pass
        assert not legacy_dir(content).exists()
    finally:
        backend.unlock(held)
        os.close(held)


def test_write_lock_frees_the_kernel_lock_when_the_legacy_lock_is_busy(tmp_path: Path) -> None:
    git = make_repo(tmp_path / "repo") / ".git"
    content = tmp_path / "repo"
    legacy_dir(content).mkdir()
    (legacy_dir(content) / "pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    backend = lock.default_backend("linux")
    with pytest.raises(LockBusy), lock.write_lock(git, content, 0, backend):
        pass
    fd = lock.acquire_kernel(git / "kb.lock", backend, 0)
    backend.unlock(fd)
    os.close(fd)

"""Every operating-system-specific call the runtime makes.

No other module in kb calls os.kill, os.getuid, os.chmod, os.symlink, or
syslog, or opens a text file without an explicit encoding and newline;
tests/py/test_platform_rules.py enforces it. Linux and macOS share the
POSIX code. Windows follows after cutover; the functions that differ have
a Windows branch or say what it will be.

Text is UTF-8 with "\\n" line endings everywhere. Content files may hold
bytes that are not UTF-8, so text I/O uses surrogateescape: undecodable
bytes survive a read and a write unchanged.
"""

from __future__ import annotations

import contextlib
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePath

WINDOWS = sys.platform == "win32"
ENCODING = "utf-8"
ERRORS = "surrogateescape"


# Text I/O


def read_text(path: Path) -> str:
    with path.open(encoding=ENCODING, errors=ERRORS, newline="") as handle:
        return handle.read()


def write_text(path: Path, text: str) -> None:
    with path.open("w", encoding=ENCODING, errors=ERRORS, newline="") as handle:
        handle.write(text)


def append_text(path: Path, text: str) -> None:
    with path.open("a", encoding=ENCODING, errors=ERRORS, newline="") as handle:
        handle.write(text)


def configure_stdio() -> None:
    """UTF-8 with "\\n" line endings on stdout and stderr, whatever the console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding=ENCODING, errors=ERRORS, newline="\n")


def posix(path: PurePath | str) -> str:
    """A path as printed: forward slashes on every platform."""
    return PurePath(path).as_posix()


# Identity and permissions


def user_id() -> str:
    """The name part that keeps one user's session directory from another's."""
    if WINDOWS:
        return os.environ.get("USERNAME", "user")
    return str(os.getuid())


def owned_by_user(path: Path) -> bool:
    """True when path belongs to the current user, following symlinks as test -O does."""
    if WINDOWS:
        return True  # The per-user profile directory is private already.
    try:
        return path.stat().st_uid == os.getuid()
    except OSError:
        return False


def make_private(path: Path) -> None:
    """Mode 700 for a directory, 600 for a file; best effort, as in bash."""
    if WINDOWS:
        return
    mode = 0o700 if stat.S_ISDIR(path.lstat().st_mode) else 0o600
    with contextlib.suppress(OSError):
        os.chmod(path, mode)  # noqa: PTH101 - the one place modes are set


def make_private_dirs(path: Path) -> None:
    """Create path and its parents with no window in which they are readable."""
    if WINDOWS:
        path.mkdir(parents=True, exist_ok=True)
        return
    previous = os.umask(0o077)
    try:
        path.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(previous)


def make_executable(path: Path) -> None:
    if WINDOWS:
        return
    os.chmod(path, path.stat().st_mode | 0o111)  # noqa: PTH101


def symlink(target: Path | str, link: Path) -> None:
    os.symlink(target, link)  # noqa: PTH211 - the one place links are made


# Processes


def process_alive(pid: int) -> bool:
    """Whether a process with this pid exists.

    Never os.kill(pid, 0) on Windows, where signal 0 is CTRL_C_EVENT.
    """
    if pid <= 0:
        return False
    if WINDOWS:
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # It exists and belongs to someone else.
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes

    synchronize = 0x00100000
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        timeout = 0x00000102
        return kernel32.WaitForSingleObject(handle, 0) == timeout
    finally:
        kernel32.CloseHandle(handle)


def git_running_in(repo: Path) -> bool:
    """Whether a git process mentions repo on its command line (audit A-003).

    POSIX only: pgrep ships with Linux and macOS. On Windows the stale
    index-lock check is age-only.
    """
    if WINDOWS:
        return False
    try:
        result = subprocess.run(
            ["pgrep", "-f", f"git.*{repo}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def exit_on_signals() -> None:
    """Turn HUP, INT, and TERM into SystemExit(128 + signal number).

    The default actions end the process at once, skipping the finally
    blocks that release the observe lock; bash's EXIT trap runs instead.
    """
    import signal

    def handler(signum: int, frame: object) -> None:
        raise SystemExit(128 + signum)

    names = ("SIGINT", "SIGTERM") if WINDOWS else ("SIGHUP", "SIGINT", "SIGTERM")
    for name in names:
        signal.signal(getattr(signal, name), handler)


# Logging


def log(tag: str, message: str) -> None:
    """Send message to syslog under tag, best effort (audit A-004)."""
    if WINDOWS:
        return
    try:
        import syslog
    except ImportError:
        return
    syslog.openlog(tag)
    syslog.syslog(message)
    syslog.closelog()

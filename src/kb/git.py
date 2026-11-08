"""Run Git in a repository directory. Every Git subprocess in kb goes through here."""

import os
import subprocess
from pathlib import Path


def run(
    root: Path,
    *words: str,
    optional_locks: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git with UTF-8 text input and output. Never raises for a nonzero exit.

    Input is sent as exact UTF-8 bytes; text-mode pipes would write CRLF on Windows. Output
    newlines are translated to "\\n", as text mode does on every platform.
    """
    result = _run(
        root, words, optional_locks, None if input_text is None else input_text.encode("utf-8")
    )
    return subprocess.CompletedProcess(
        result.args, result.returncode, _text(result.stdout), _text(result.stderr)
    )


def run_bytes(
    root: Path,
    *words: str,
    optional_locks: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git with raw bytes, with no newline or encoding translation."""
    return _run(root, words, optional_locks, input_bytes)


def _run(
    root: Path, words: tuple[str, ...], optional_locks: bool, input_bytes: bytes | None
) -> subprocess.CompletedProcess[bytes]:
    """The one Git subprocess call. Tests replace run and run_bytes, never this."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        env=_environment(optional_locks),
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _environment(optional_locks: bool) -> dict[str, str] | None:
    """None inherits the environment; without optional locks, Git also gets GIT_OPTIONAL_LOCKS=0."""
    return None if optional_locks else {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def _text(data: bytes) -> str:
    """Decode UTF-8 strictly and translate newlines as a text-mode pipe does."""
    return data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")

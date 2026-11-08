"""Run Git in a repository directory. Every Git subprocess in kb goes through here."""

import os
import subprocess
from pathlib import Path


def run(
    root: Path,
    *words: str,
    read_only: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run git with UTF-8 text input and output. Never raises for a nonzero exit."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        env=_environment(read_only),
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def run_bytes(
    root: Path,
    *words: str,
    read_only: bool = False,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git with raw bytes, with no newline or encoding translation."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        env=_environment(read_only),
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def _environment(read_only: bool) -> dict[str, str] | None:
    """None inherits the environment; read-only runs also skip Git's optional locks."""
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0"} if read_only else None

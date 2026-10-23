"""Render filesystem and repository state as stable text for golden files."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def tree(root: Path, *, skip: tuple[str, ...] = (".git",), modes: bool = False) -> str:
    """List every path under root, relative and sorted; directories end in '/'.

    Symlinks are shown with their raw target. With modes, each line starts
    with the permission bits in octal.
    """
    lines = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        base = Path(dirpath)
        for name in dirnames:
            lines.append(_line(base / name, root, modes, suffix="/"))
        for name in sorted(filenames):
            if name in skip:
                continue
            lines.append(_line(base / name, root, modes))
    return "".join(sorted(lines))


def _line(path: Path, root: Path, modes: bool, suffix: str = "") -> str:
    rel = path.relative_to(root).as_posix() + suffix
    if path.is_symlink():
        rel = f"{rel.rstrip('/')} -> {os.readlink(path)}"  # noqa: PTH115 - keeps raw target
    if modes:
        mode = stat.S_IMODE(path.lstat().st_mode)
        return f"{mode:04o} {rel}\n"
    return f"{rel}\n"


def git(repo: Path, *args: str, env: dict[str, str]) -> str:
    """Run git in repo with the given environment and return stdout."""
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    ).stdout


def git_log(repo: Path, env: dict[str, str]) -> str:
    """Commits newest first: hash, author, subject, and changed paths."""
    return git(repo, "log", "--format=%H %an <%ae> %s", "--name-status", env=env)

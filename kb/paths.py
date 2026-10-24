"""Paths given on the command line, resolved inside the content repository.

These commands are auto-approved by the command-approval hook, so their
path arguments are a security boundary: nothing may resolve outside the
content root, including through a symlink.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from pathlib import Path, PurePosixPath

AREAS = ("knowledge", "sources", "observations", "questions")


class PathError(Exception):
    """Resolution failed and the reason was already printed to stderr."""


def contained(content: Path, target: Path) -> bool:
    """True when target, with every symlink resolved, is inside content."""
    root = os.path.realpath(content)
    real = os.path.realpath(target)
    return real == root or real.startswith(root + os.sep)


def _refuse(original: str) -> PathError:
    print(f"Refusing path outside the knowledge base: {original}", file=sys.stderr)
    return PathError()


def _matches(content: Path, pattern: str) -> list[Path]:
    found = []
    for area in AREAS:
        top = content / area
        if not top.is_dir():
            continue
        for directory, dirs, files in os.walk(top):
            for name in dirs + files:
                if fnmatch.fnmatchcase(name, pattern):
                    found.append(Path(directory) / name)
    return sorted(found, key=bytes)


def resolve(content: Path, value: str) -> str | None:
    """value as a content-relative path, or None if nothing matches.

    Tries, in order: an absolute path under the content root, a
    content-relative path, a knowledge/-relative path, and a unique file
    name anywhere in the four content areas. Raises PathError, after
    printing why, for a path outside the root or an ambiguous name (whose
    matches are listed in code-point order, audit A-029).
    """
    relative = value.removeprefix(f"{content}/")
    # Joined as strings, as bash does: an absolute value that is not under
    # the content root must not replace it.
    candidate = Path(f"{content}/{relative}")
    if candidate.exists():
        if not contained(content, candidate):
            raise _refuse(value)
        return relative
    if not relative.startswith(tuple(f"{area}/" for area in AREAS)):
        candidate = Path(f"{content}/knowledge/{relative}")
        if candidate.exists():
            if not contained(content, candidate):
                raise _refuse(value)
            return f"knowledge/{relative}"
    base = PurePosixPath(relative.rstrip("/")).name or relative
    matches = _matches(content, base)
    if not matches:
        return None
    if len(matches) == 1:
        if not contained(content, matches[0]):
            raise _refuse(value)
        return matches[0].relative_to(content).as_posix()
    print(f"Ambiguous match for '{base}' — {len(matches)} files found:", file=sys.stderr)
    for match in matches:
        print(f"  {match.relative_to(content).as_posix()}", file=sys.stderr)
    raise PathError()


def markdown_files(top: Path) -> list[Path]:
    """Regular *.md files under top, as `find -name '*.md' -type f`, in code-point order."""
    found = []
    for directory, _, files in os.walk(top):
        for name in files:
            path = Path(directory) / name
            if name.endswith(".md") and path.is_file() and not path.is_symlink():
                found.append(path)
    return sorted(found, key=bytes)


def relative(content: Path, path: Path) -> str:
    return str(path).removeprefix(f"{content}/")

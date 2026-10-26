"""The content repository's files: finding them, resolving PATH, and reading them.

This module, with config.py, is the code that reads the content repository.
Paths it returns are relative to the repository root, with "/" separators.
"""

import os
from pathlib import Path

from kb import model
from kb.errors import KbError

CURATED_DIRECTORIES = ("knowledge/", "sources/")


def is_curated(relpath: str) -> bool:
    """True for files that recall searches by default: knowledge/ and sources/."""
    return relpath.startswith(CURATED_DIRECTORIES)


def markdown_files(root: Path, under: str) -> list[str]:
    """The Markdown files under a directory, or the file itself, sorted.

    Hidden directories are skipped. A file that resolves outside the
    repository is left out.
    """
    base = root / under
    if not base.exists():
        return []
    if base.is_file():
        found = [base.resolve()] if base.name.endswith(".md") else []
    else:
        found = []
        for directory, subdirs, names in os.walk(base):
            subdirs[:] = sorted(name for name in subdirs if not name.startswith("."))
            found.extend(Path(directory, name).resolve() for name in names if name.endswith(".md"))
    return sorted(
        path.relative_to(root).as_posix()
        for path in found
        if path.is_file() and path.is_relative_to(root)
    )


def resolve_path(root: Path, path: str, who: str) -> str | None:
    """The content-relative path that PATH names, or None when nothing does.

    PATH is tried as a content-relative path, then relative to knowledge/,
    then as a file name that is unique in the repository. Raises KbError when
    PATH resolves outside the repository, or when a file name matches several
    files.
    """
    if not path:
        return None
    for candidate in (path, f"knowledge/{path}"):
        target = root / candidate
        if target.exists():
            resolved = target.resolve()
            if not resolved.is_relative_to(root):
                raise KbError(f"{who}: {path} resolves outside the content repository")
            return resolved.relative_to(root).as_posix()
    if "/" in path:
        return None
    matches = [
        relpath for relpath in markdown_files(root, ".") if relpath.rsplit("/", 1)[-1] == path
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        listing = [f'{who}: "{path}" matches {len(matches)} files:']
        listing.extend(f"  {relpath}" for relpath in matches)
        raise KbError("\n".join(listing))
    return None


def read_document(root: Path, relpath: str) -> model.Document:
    """Parse one file. Bytes are decoded as UTF-8, and bad bytes become U+FFFD."""
    try:
        data = (root / relpath).read_bytes()
    except OSError as error:
        raise KbError(f"kb: cannot read {relpath}: {error.strerror}") from error
    text = data.decode("utf-8", errors="replace").removeprefix("﻿")
    return model.parse(relpath, text)

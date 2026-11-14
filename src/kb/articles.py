"""Read and atomically replace one curated article under the caller's write lock."""

import stat
from dataclasses import dataclass
from pathlib import Path

from kb import corpus, scratch
from kb.errors import KbError


@dataclass(frozen=True)
class Article:
    """One article's original bytes, its byte order mark, and its text after the mark."""

    relpath: str
    original: bytes
    bom: str
    text: str


def read(root: Path, relpath: str, who: str) -> Article:
    """Read an article that must be UTF-8."""
    path = root / relpath
    try:
        original = path.read_bytes()
    except OSError as error:
        raise KbError(f"{who}: cannot read {relpath}: {error.strerror}") from error
    try:
        decoded = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"{who}: {relpath} is not valid UTF-8: {error.reason}") from error
    bom, text = corpus.split_bom(decoded)
    return Article(relpath, original, bom, text)


def write(root: Path, git_directory: Path, article: Article, text: str, who: str) -> bool:
    """Replace the article with text, keeping its mode and byte order mark.

    Returns False and writes nothing when the bytes would not change. The caller holds the
    content repository's write lock, so the file cannot change between read and replace.
    """
    result = (article.bom + text).encode("utf-8")
    if result == article.original:
        return False
    path = root / article.relpath
    temporary = scratch.create_file(
        scratch.shared_directory(git_directory, who),
        f"{who}-",
        ".md",
        result,
        mode=stat.S_IMODE(path.stat().st_mode),
    )
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True

"""The token cache: each evidence file's search tokens, kept in the content root's cache directory.

kb evidence and kb recall rank every evidence file on each query, and tokenizing the
harvested transcripts takes most of the time. This module keeps the tokens of each file
and reuses them while the file's bytes are unchanged.

The cache is one pickle of the records in kb.entries. It lives in cache/ at the top of each
worktree, which the content repository's .gitignore must ignore, so it is never committed or
synced. It can be deleted at any time. An unreadable or stale cache is rebuilt.
"""

import hashlib
import os
import pickle
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

from kb import addressing, chunks, corpus, evidence, lock, model, search
from kb.entries import Entry, PartTokens

FORMAT = 4
CACHE_DIRECTORY = "cache"
CACHE_FILE = "tokens.pickle"
LOCK_FILE = "tokens.lock"
EVIDENCE_DIRECTORIES = (
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
)
# The front matter fields that Entry.scalars keeps. Only these are read from it: source and
# created classify and date an evidence file, and context names its area in recall.
SCALAR_FIELDS = ("source", "created", "context")


@dataclass(frozen=True)
class RefreshReport:
    """What one update did.

    refreshed counts files tokenized again, restated counts files whose bytes did not
    change, removed counts entries dropped for files that are gone, and written tells
    whether the cache file was replaced.
    """

    refreshed: int
    restated: int
    removed: int
    written: bool


def load(
    root: Path, paths: Sequence[str], documents: corpus.Documents | None = None
) -> dict[str, Entry]:
    """Entries for paths, refreshing stale ones. Never raises on a bad cache.

    A stale file is parsed through documents, so a caller that reads the same files
    afterwards parses each one once. Without documents, a private set is used.
    """
    entries, _ = _update(root, paths, prune=False, documents=documents)
    return entries


def refresh(root: Path) -> RefreshReport:
    """Bring the whole evidence tier up to date. Used by kb sync and kb doctor."""
    _, report = _update(root, evidence_paths(root), prune=True, documents=None)
    return report


@dataclass(frozen=True)
class CacheStatus:
    """The cache file's state, read without tokenizing anything.

    state is "none" when the content root is not the top of a git worktree of its own,
    "unignored" when git does not ignore the cache file, "missing" when no cache file exists, "stale" when the file cannot be used or does not list the evidence files
    as they are on disk, and "current" otherwise. entries and size describe the file.
    """

    path: Path | None
    entries: int
    size: int
    state: Literal["none", "unignored", "missing", "stale", "current"]


def status(root: Path) -> CacheStatus:
    """The state of the cache file. Compares names and stat fields only, never bytes."""
    target, usable = _location(root)
    if target is None:
        return CacheStatus(None, 0, 0, "none")
    if not usable:
        return CacheStatus(target, 0, 0, "unignored")
    try:
        size = target.stat().st_size
    except OSError:
        return CacheStatus(target, 0, 0, "missing")
    stored = _read(target, fingerprint())
    if stored is None:
        return CacheStatus(target, 0, size, "stale")
    listed = evidence_paths(root)
    current = set(stored) == set(listed) and all(_on_disk(root, stored[path]) for path in listed)
    return CacheStatus(target, len(stored), size, "current" if current else "stale")


def _on_disk(root: Path, entry: Entry) -> bool:
    """Whether the file still has the modification time and size that its entry records."""
    try:
        status_result = (root / entry.path).stat()
    except OSError:
        return False
    return entry.mtime_ns == status_result.st_mtime_ns and entry.size == status_result.st_size


def evidence_paths(root: Path) -> list[str]:
    """The content-relative paths of every evidence file, sorted."""
    return sorted(
        {
            path
            for directory in EVIDENCE_DIRECTORIES
            for path in corpus.markdown_files(root, directory)
        }
    )


def cache_file(root: Path) -> Path | None:
    """The cache file, cache/tokens.pickle at the top of root's worktree, when kb may write it.

    None when root is not the top of a git worktree of its own, or when git does not ignore
    the cache file. A content root inside another repository, such as a fixture, gets no
    cache, and an unignored cache is never written where a commit could pick it up.
    """
    target, usable = _location(root)
    return target if usable else None


def _location(root: Path) -> tuple[Path | None, bool]:
    """The cache file's path, and whether git ignores it there.

    The path is None when root is not the top of a git worktree of its own.
    """
    toplevel = _git(root, "rev-parse", "--show-toplevel")
    if toplevel is None or toplevel.returncode != 0:
        return None, False
    lines = toplevel.stdout.splitlines()
    if len(lines) != 1 or Path(lines[0]).resolve() != root.resolve():
        return None, False
    relative = f"{CACHE_DIRECTORY}/{CACHE_FILE}"
    ignored = _git(root, "check-ignore", "--quiet", "--", relative)
    target = root.resolve() / CACHE_DIRECTORY / CACHE_FILE
    return target, ignored is not None and ignored.returncode == 0


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str] | None:
    """Run one read-only git command in root, or None when git cannot run."""
    try:
        return subprocess.run(
            ["git", *words],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None


def fingerprint(package: Traversable | None = None) -> str:
    """The SHA-256 of every Python source file in the kb package, subpackages included.

    Each file contributes its path relative to the package, a NUL byte, and its bytes, in
    sorted path order. Any edit to the package therefore changes the fingerprint and rebuilds
    the cache, so a change to the tokens, the message contract, or the addressing rules
    cannot leave stale entries behind.
    """
    source = resources.files("kb") if package is None else package
    digest = hashlib.sha256()
    for relpath, path in sorted(_python_sources(source, ""), key=lambda item: item[0]):
        digest.update(relpath.encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _python_sources(directory: Traversable, prefix: str) -> Iterator[tuple[str, Traversable]]:
    """Each *.py file under directory, with its path relative to the package in POSIX form."""
    for item in directory.iterdir():
        relpath = f"{prefix}{item.name}"
        if item.is_dir():
            yield from _python_sources(item, f"{relpath}/")
        elif item.name.endswith(".py"):
            yield relpath, item


def _update(
    root: Path,
    paths: Iterable[str],
    prune: bool,
    documents: corpus.Documents | None,
) -> tuple[dict[str, Entry], RefreshReport]:
    """Entries for paths, with stale ones retokenized, and the cache written if it changed.

    Without prune, entries for other paths stay in the cache. With prune, every entry
    outside paths is dropped.
    """
    wanted = sorted(set(paths))
    shared = corpus.Documents(root) if documents is None else documents
    target = cache_file(root)
    version = fingerprint()
    loaded = _read(target, version) if target is not None else None
    stored = loaded or {}
    merged = dict(stored)
    entries: dict[str, Entry] = {}
    refreshed = restated = removed = 0

    for relpath in wanted:
        path = root / relpath
        try:
            stat_result = path.stat()
        except OSError:
            continue
        old = stored.get(relpath)
        if (
            old is not None
            and old.mtime_ns == stat_result.st_mtime_ns
            and old.size == stat_result.st_size
        ):
            entries[relpath] = old
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if old is not None and old.digest == digest:
            entry = replace(old, mtime_ns=stat_result.st_mtime_ns, size=stat_result.st_size)
            restated += 1
        else:
            document = shared.parse(relpath, corpus.decode_text(data))
            entry = _build(document, stat_result.st_mtime_ns, stat_result.st_size, digest)
            refreshed += 1
        entries[relpath] = merged[relpath] = entry

    if prune:
        for relpath in sorted(set(merged) - set(wanted)):
            del merged[relpath]
            removed += 1

    written = False
    # A missing or unusable file is replaced even when no evidence file changed, so an
    # empty content repository still gets a cache that reports as current.
    if target is not None and (refreshed or restated or removed or loaded is None):
        written = _write(target, version, merged)
    return entries, RefreshReport(refreshed, restated, removed, written)


def _build(document: model.Document, mtime_ns: int, size: int, digest: str) -> Entry:
    """Tokenize one parsed file once.

    A transcript stores its title and its parts. Each part's lines are tokenized once, after
    chunks.parts has removed injected text. Other evidence stores its title and body.
    """
    relpath = document.path
    scalars = {
        name: value for name in SCALAR_FIELDS if (value := document.scalar(name)) is not None
    }
    title = search.index_tokens(document.title or "")
    if evidence.evidence_kind(relpath, document.scalar("source")) == "transcript":
        known: dict[str, tuple[str, ...]] = {}

        def tokens_of(line: str) -> tuple[str, ...]:
            tokens = known.get(line)
            if tokens is None:
                tokens = search.index_tokens(line)
                known[line] = tokens
            return tokens

        parts = tuple(
            PartTokens(
                part.number,
                part.timestamp,
                part.piece,
                part.size,
                tuple(token for line in part.lines for token in tokens_of(line)),
            )
            for part in chunks.parts(document)
        )
        addressable = addressing.message_sections(document) is not None
        return Entry(relpath, mtime_ns, size, digest, scalars, title, (), parts, addressable)
    lines = document.lines
    body = tuple(
        token
        for index in range(document.body_start, len(lines))
        if index not in document.heading_lines and index not in document.comment_lines
        for token in search.index_tokens(lines[index])
    )
    return Entry(relpath, mtime_ns, size, digest, scalars, title, body, (), False)


# The last cache file read or written in this process, keyed by its identity on disk. A
# command that ranks evidence several times, such as kb recall, decodes the file once.
_memo: tuple[tuple[object, ...], dict[str, Entry]] | None = None


def _identity(target: Path, version: str) -> tuple[object, ...] | None:
    """The cache file's path, inode, mtime, and size, with the format and code version.

    None when the file is missing.
    """
    try:
        status = target.stat()
    except OSError:
        return None
    return (str(target), status.st_ino, status.st_mtime_ns, status.st_size, FORMAT, version)


def _read(target: Path, version: str) -> dict[str, Entry] | None:
    """The stored entries, or None when the file is missing, unreadable, or for another version.

    The result is shared, not copied, while the file on disk is unchanged. Callers must not
    change it.
    """
    global _memo
    identity = _identity(target, version)
    if identity is not None and _memo is not None and _memo[0] == identity:
        return _memo[1]
    entries = _decode(target, version)
    _memo = (identity, entries) if identity is not None and entries is not None else None
    return entries


def _decode(target: Path, version: str) -> dict[str, Entry] | None:
    """The stored entries, or None for a missing, unreadable, or mismatched file.

    A pickle of the wrong shape, a format or fingerprint mismatch, or a key that names another
    entry's path returns None, so the caller rebuilds the cache.
    """
    try:
        with target.open("rb") as handle:
            data = pickle.load(handle)
        if not isinstance(data, dict) or data["format"] != FORMAT or data["fingerprint"] != version:
            return None
        stored = data["entries"]
        if not isinstance(stored, dict):
            return None
        for key, entry in stored.items():
            if not isinstance(entry, Entry) or entry.path != key:
                return None
        return stored
    except Exception:
        return None


def _write(target: Path, version: str, entries: dict[str, Entry]) -> bool:
    """Replace the cache file atomically. Returns False when another writer holds the lock."""
    directory = target.parent
    backend = lock.default_backend(sys.platform)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor = lock.acquire_kernel(directory / LOCK_FILE, backend, 0)
    except lock.LockBusy:
        return False
    except OSError as error:
        return _warn(target, error)
    global _memo
    try:
        _replace_file(target, version, entries)
        identity = _identity(target, version)
        _memo = (identity, dict(entries)) if identity is not None else None
    except OSError as error:
        return _warn(target, error)
    finally:
        backend.unlock(descriptor)
        os.close(descriptor)
    return True


def _replace_file(target: Path, version: str, entries: dict[str, Entry]) -> None:
    payload = {"format": FORMAT, "fingerprint": version, "entries": entries}
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=".tokens-", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            pickle.dump(payload, handle, protocol=5)
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _warn(target: Path, error: OSError) -> bool:
    """Print the one-line warning for a cache that could not be written. Always returns False."""
    sys.stderr.write(f"kb: token cache not written to {target}: {error.strerror or error}\n")
    return False

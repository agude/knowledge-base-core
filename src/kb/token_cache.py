"""The token cache: each evidence file's search tokens, kept in the content repository's git directory.

kb evidence and kb recall rank every evidence file on each query, and tokenizing the
harvested transcripts takes most of the time. This module keeps the tokens of each file
and reuses them while the file's bytes are unchanged.

The cache is one pickle of plain tuples, strings, and numbers, so it holds no kb classes.
It lives in the git directory of each worktree, is never committed or synced, and can be
deleted at any time. An unreadable or stale cache is rebuilt.
"""

import hashlib
import os
import pickle
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

from kb import addressing, chunks, corpus, evidence, lock, model, search

FORMAT = 3
CACHE_DIRECTORY = "kb"
CACHE_FILE = "tokens.pickle"
LOCK_FILE = "tokens.lock"
EVIDENCE_DIRECTORIES = (
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
)
# The modules whose code decides what an entry holds. An edit to any of them rebuilds the
# cache. Each file is hashed whole, so a change to the tokens or to the message contract
# cannot go unnoticed.
FINGERPRINT_MODULES = (
    "chunks.py",
    "derivations.py",
    "evidence.py",
    "model.py",
    "search.py",
    "stem.py",
    "token_cache.py",
)
# The front matter fields that the ranking path and its filters read.
SCALAR_FIELDS = (
    "title",
    "source",
    "created",
    "context",
    "project",
    "session",
    "part",
    "first_message",
    "last_message",
    "started",
    "ended",
)

# A search.Unit as plain tuples: title, aliases, headings, body, and the sorted phrases.
UnitTokens = tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]
]
# One addressable message: its number, its UTC timestamp in ISO form, its body tokens, and its
# length in characters when it is not split (0 when it is). The body is the tokens of the
# message's cleaned lines, so it equals its chunks' tokens joined.
MessageTokens = tuple[int, str, tuple[str, ...], int]
# One chunk: the numbers of its first and last messages (0 for none), the ISO timestamps of
# those messages (None for none), its piece index (0 for whole messages), and its body tokens.
ChunkTokens = tuple[int, int, str | None, str | None, int, tuple[str, ...]]
_STORED_FIELDS = 8
_STORED_UNIT_FIELDS = 5
_STORED_MESSAGE_FIELDS = 4
_STORED_CHUNK_FIELDS = 6


@dataclass(frozen=True)
class Entry:
    """The cached tokens of one evidence file.

    messages is empty unless the file is an addressable transcript. chunks is empty unless
    the file is a transcript. The stat fields are the file's modification time and size,
    and digest is the SHA-256 of its bytes.
    """

    path: str
    mtime_ns: int
    size: int
    digest: str
    scalars: dict[str, str]
    file_unit: UnitTokens
    messages: tuple[MessageTokens, ...]
    chunks: tuple[ChunkTokens, ...]


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

    state is "none" when the content root has no cache location, "missing" when no cache
    file exists, "stale" when the file cannot be used or does not list the evidence files
    as they are on disk, and "current" otherwise. entries and size describe the file.
    """

    path: Path | None
    entries: int
    size: int
    state: Literal["none", "missing", "stale", "current"]


def status(root: Path) -> CacheStatus:
    """The state of the cache file. Compares names and stat fields only, never bytes."""
    target = cache_file(root)
    if target is None:
        return CacheStatus(None, 0, 0, "none")
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
    """The cache file in the git directory of root's worktree.

    None when root is not the top of a git worktree of its own. A content root inside
    another repository, such as a fixture, gets no cache and writes nothing there.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-dir"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError:
        return None
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 2:
        return None
    toplevel, git = lines
    if Path(toplevel).resolve() != root.resolve():
        return None
    return (root / git).resolve() / CACHE_DIRECTORY / CACHE_FILE


def fingerprint(package: Traversable | None = None) -> str:
    """The SHA-256 of the source bytes of the modules that decide what an entry holds."""
    source = resources.files("kb") if package is None else package
    digest = hashlib.sha256()
    for name in FINGERPRINT_MODULES:
        digest.update(name.encode("ascii") + b"\0")
        digest.update(source.joinpath(name).read_bytes())
    return digest.hexdigest()


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
            status = path.stat()
        except OSError:
            continue
        old = stored.get(relpath)
        if old is not None and old.mtime_ns == status.st_mtime_ns and old.size == status.st_size:
            entries[relpath] = old
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if old is not None and old.digest == digest:
            entry = replace(old, mtime_ns=status.st_mtime_ns, size=status.st_size)
            restated += 1
        else:
            document = shared.parse(relpath, corpus.decode_text(data))
            entry = _build(document, status.st_mtime_ns, status.st_size, digest)
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
    """Tokenize one parsed file once. The file unit and the message bodies share its lines.

    A transcript is tokenized from chunks.visible, so injected text cannot match. Other
    evidence is tokenized as stored.
    """
    relpath = document.path
    transcript = evidence.evidence_kind(relpath, document.scalar("source")) == "transcript"
    view = chunks.visible(document) if transcript else document
    lines = view.lines
    kept = {
        index: search.index_tokens(lines[index])
        for index in range(view.body_start, len(lines))
        if index not in view.heading_lines and index not in view.comment_lines
    }
    title = search.index_tokens(document.title or "")
    body = tuple(token for tokens in kept.values() for token in tokens)
    file_unit: UnitTokens = (
        title,
        (),
        (),
        body,
        (" ".join(title),) if title else (),
    )
    scalars = {
        name: value for name in SCALAR_FIELDS if (value := document.scalar(name)) is not None
    }
    messages: tuple[MessageTokens, ...] = ()
    transcript_chunks: tuple[ChunkTokens, ...] = ()
    if transcript:
        # Most chunk lines are unchanged file lines, so their tokens are reused. Only the
        # lines that injected-text removal changed are tokenized again.
        known = {lines[index]: tokens for index, tokens in kept.items()}

        def tokens_of(line: str) -> tuple[str, ...]:
            tokens = known.get(line)
            if tokens is None:
                tokens = search.index_tokens(line)
                known[line] = tokens
            return tokens

        if addressing.message_sections(view) is not None:
            messages = _message_tokens(chunks.parts(document), tokens_of)
        transcript_chunks = tuple(
            (
                chunk.number,
                chunk.last,
                _iso(chunk.started),
                _iso(chunk.ended),
                chunk.piece,
                tuple(token for line in chunk.lines for token in tokens_of(line)),
            )
            for chunk in chunks.chunks(document)
        )
    return Entry(relpath, mtime_ns, size, digest, scalars, file_unit, messages, transcript_chunks)


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
    try:
        with target.open("rb") as handle:
            data = pickle.load(handle)
        if data["format"] != FORMAT or data["fingerprint"] != version:
            return None
        entries: dict[str, Entry] = {}
        for key, value in data["entries"].items():
            entry = _from_tuple(value)
            if entry.path != key:
                raise ValueError(key)
            entries[key] = entry
        return entries
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
    payload = {
        "format": FORMAT,
        "fingerprint": version,
        "entries": {path: _to_tuple(entry) for path, entry in entries.items()},
    }
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


def _to_tuple(entry: Entry) -> tuple[object, ...]:
    return (
        entry.path,
        entry.mtime_ns,
        entry.size,
        entry.digest,
        tuple(sorted(entry.scalars.items())),
        entry.file_unit,
        entry.messages,
        entry.chunks,
    )


def _from_tuple(value: object) -> Entry:
    """The entry that a stored tuple holds. Raises TypeError or ValueError on the wrong shape."""
    parts = _tuple(value)
    if len(parts) != _STORED_FIELDS:
        raise TypeError("entry")
    path, mtime_ns, size, digest, pairs, file_unit, messages, chunk_items = parts
    if not (
        isinstance(path, str)
        and isinstance(mtime_ns, int)
        and isinstance(size, int)
        and isinstance(digest, str)
    ):
        raise TypeError("entry fields")
    scalars: dict[str, str] = {}
    for pair in _tuple(pairs):
        name, text = _tuple(pair)
        if not (isinstance(name, str) and isinstance(text, str)):
            raise TypeError("scalar")
        scalars[name] = text
    return Entry(
        path=path,
        mtime_ns=mtime_ns,
        size=size,
        digest=digest,
        scalars=scalars,
        file_unit=_unit(file_unit),
        messages=tuple(_message(item) for item in _tuple(messages)),
        chunks=tuple(_chunk(item) for item in _tuple(chunk_items)),
    )


def _unit(value: object) -> UnitTokens:
    parts = _tuple(value)
    if len(parts) != _STORED_UNIT_FIELDS:
        raise TypeError("unit")
    title, aliases, headings, body, phrases = (_strings(part) for part in parts)
    return title, aliases, headings, body, phrases


def _chunk(value: object) -> ChunkTokens:
    parts = _tuple(value)
    if len(parts) != _STORED_CHUNK_FIELDS:
        raise TypeError("chunk")
    number, last, started, ended, piece, body = parts
    if not all(isinstance(item, int) for item in (number, last, piece)):
        raise TypeError("chunk numbers")
    for timestamp in (started, ended):
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise TypeError("chunk timestamp")
            datetime.fromisoformat(timestamp)
    return number, last, started, ended, piece, _strings(body)


def _message(value: object) -> MessageTokens:
    parts = _tuple(value)
    if len(parts) != _STORED_MESSAGE_FIELDS:
        raise TypeError("message")
    number, timestamp, body, size = parts
    if not (isinstance(number, int) and isinstance(timestamp, str) and isinstance(size, int)):
        raise TypeError("message fields")
    datetime.fromisoformat(timestamp)
    return number, timestamp, _strings(body), size


def _message_tokens(
    found: Sequence[chunks.Part], tokens_of: Callable[[str], tuple[str, ...]]
) -> tuple[MessageTokens, ...]:
    """One entry per addressable message, from its parts in order."""
    by_number: dict[int, list[chunks.Part]] = {}
    for part in found:
        if part.number:
            by_number.setdefault(part.number, []).append(part)
    out: list[MessageTokens] = []
    for number, members in by_number.items():
        first = members[0]
        body = tuple(
            token for member in members for line in member.lines for token in tokens_of(line)
        )
        size = 0 if first.piece else first.size
        out.append((number, _iso(first.timestamp) or "", body, size))
    return tuple(out)


def _iso(moment: datetime | None) -> str | None:
    """The ISO form of a timestamp, or None."""
    return None if moment is None else moment.isoformat()


def _tuple(value: object) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise TypeError("expected a tuple")
    return value


def _strings(value: object) -> tuple[str, ...]:
    items = _tuple(value)
    if not all(isinstance(item, str) for item in items):
        raise TypeError("expected strings")
    return items

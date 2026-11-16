"""The transcript cache: each transcript's parsed session, reused while its file is unchanged.

kb sync and kb curate triage parse every Claude and Codex transcript on each run, and most of
them have not changed since the last run. This module keeps each parsed session with its file's
size and modification time, and a scan reuses a stored session only while both still match.

The cache is one pickle at cache/transcripts.pickle in the content worktree. It follows the token
cache's rules: git must ignore it, so it is never committed, and it can be deleted at any time.
A cache that cannot be read, or that was written by other kb code, is ignored and replaced. A
write replaces the file atomically, so a reader never sees a partial file. Two runs that write
at once can each drop the other's entries, and the next run then parses those files again.

Pickles must come from trusted local storage.
"""

import os
import pickle
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from kb import token_cache
from kb.transcripts import Session

FORMAT = 1
CACHE_FILE = "transcripts.pickle"


@dataclass(frozen=True)
class Stored:
    """A transcript's parsed session and the file identity that it was parsed from."""

    size: int
    mtime_ns: int
    session: Session


class Cache:
    """The sessions that the last scan stored, and the ones that the current scan keeps.

    A scan asks session() before it parses a file, and calls add() after it parses one. save()
    then replaces the stored sessions with the ones this scan kept, which drops transcripts
    that are gone.
    """

    def __init__(self, target: Path | None, version: str, previous: dict[str, Stored]) -> None:
        self._target = target
        self._version = version
        self._previous = previous
        self._current: dict[str, Stored] = {}
        self._parsed = False

    @classmethod
    def load(cls, root: Path) -> "Cache":
        """The cache for root's content. It holds no sessions when the cache file is unusable."""
        version = token_cache.fingerprint()
        target = token_cache.cache_file(root, CACHE_FILE)
        previous = {} if target is None else _read(target, version)
        return cls(target, version, previous)

    def session(self, path: str, status: os.stat_result) -> Session | None:
        """The stored session for path, or None when it was never stored or the file changed."""
        stored = self._previous.get(path)
        if stored is None or (stored.size, stored.mtime_ns) != (status.st_size, status.st_mtime_ns):
            return None
        self._current[path] = stored
        return stored.session

    def add(self, path: str, status: os.stat_result, session: Session) -> None:
        """Keep a session that this scan parsed from path, whose identity is status."""
        self._current[path] = Stored(status.st_size, status.st_mtime_ns, session)
        self._parsed = True

    def save(self) -> None:
        """Store this scan's sessions when they differ from the stored ones.

        A scan that parsed nothing and saw the same transcripts as the last scan writes nothing.
        """
        if self._target is None:
            return
        if self._parsed or self._current.keys() != self._previous.keys():
            _write(self._target, self._version, self._current)


def _read(target: Path, version: str) -> dict[str, Stored]:
    """The stored sessions, or {} when the file is missing, unreadable, or from other code."""
    try:
        with target.open("rb") as handle:
            data = pickle.load(handle)
    except Exception:
        return {}
    if (
        not isinstance(data, dict)
        or data.get("format") != FORMAT
        or data.get("fingerprint") != version
        or not isinstance(data.get("entries"), dict)
    ):
        return {}
    entries = data["entries"]
    if not all(
        isinstance(key, str) and isinstance(value, Stored) for key, value in entries.items()
    ):
        return {}
    stored: dict[str, Stored] = entries
    return stored


def _write(target: Path, version: str, entries: dict[str, Stored]) -> None:
    """Replace the cache file atomically. A cache that cannot be written costs a parse next run."""
    payload = {"format": FORMAT, "fingerprint": version, "entries": entries}
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=target.parent, prefix=".transcripts-", suffix=".tmp"
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        temporary.replace(target)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        sys.stderr.write(
            f"kb: transcript cache not written to {target}: {error.strerror or error}\n"
        )

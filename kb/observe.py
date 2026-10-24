"""Writing observations to observations/pending/ and committing them."""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from kb import git, lock, platform
from kb.content import yaml_escape


class ObserveError(Exception):
    """Nothing was committed. The message, when there is one, says why;
    git has already reported a failed commit itself. status is the exit
    status to report: git's, for a failed commit."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


def _name(now: datetime) -> str:
    # 8 hex digits: a collision is a merge conflict on a content file (A-001).
    return f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}.md"


def render(title: str, body: str, source: str, now: datetime) -> str:
    """The observation file: front matter, a blank line, the body, a newline."""
    return (
        f'---\ntitle: "{yaml_escape(title)}"\nsource: {source}\n'
        f"created: {now:%Y-%m-%dT%H:%M:%SZ}\n---\n\n{body}\n"
    )


def write(
    content: Path,
    title: str,
    body: str,
    source: str = "session",
    *,
    commit: bool = True,
    announce: bool = True,
) -> str:
    """Publish one observation and return its file name.

    With commit, the file is committed under the observe lock, and it is
    published only once the lock is held, so a writer that times out leaves
    nothing in pending/. Without a git repository it refuses before writing
    anything (audit A-039). announce prints the `Wrote:` line.
    """
    if commit and not (content / ".git").is_dir():
        raise ObserveError(f"Not a git repository: {content}")
    pending = content / "observations" / "pending"
    now = datetime.now(UTC)
    name = _name(now)
    try:
        handle, temp_name = tempfile.mkstemp(prefix=".observation.", dir=pending)
    except OSError as error:
        raise ObserveError("Error: could not create an observation file") from error
    os.close(handle)
    temp = Path(temp_name)
    try:
        try:
            platform.write_text(temp, render(title, body, source, now))
        except OSError as error:
            raise ObserveError("Error: could not write observation file") from error
        if not commit:
            _publish(temp, pending / name, announce)
            return name
        try:
            with lock.held(content):
                git.break_stale_index_lock(content)
                _publish(temp, pending / name, announce)
                path = f"observations/pending/{name}"
                status = git.commit_paths(content, f"Observe: {title}", [path])
                if status:
                    raise ObserveError("", status)
        except lock.LockTimeout as error:
            raise ObserveError(str(error)) from error
        return name
    finally:
        temp.unlink(missing_ok=True)


def _publish(temp: Path, final: Path, announce: bool) -> None:
    try:
        temp.replace(final)
    except OSError as error:
        raise ObserveError("Error: could not publish observation file") from error
    if announce:
        print(f"Wrote: observations/pending/{final.name}", flush=True)


def report(error: ObserveError) -> int:
    if str(error):
        print(error, file=sys.stderr)
    return error.status

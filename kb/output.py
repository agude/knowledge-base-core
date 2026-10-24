"""Discarding output at the file-descriptor level, children included."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def discarded(*, stdout: bool = True, stderr: bool = True) -> Iterator[None]:
    """Send stdout and stderr, and those of any child process, to the null device.

    Bash silences a subprocess with `> /dev/null 2>&1` (or `2>/dev/null`);
    an in-process call needs the same for git and the hooks git runs.
    """
    descriptors = [fd for fd, chosen in ((1, stdout), (2, stderr)) if chosen]
    sys.stdout.flush()
    sys.stderr.flush()
    saved = {fd: os.dup(fd) for fd in descriptors}
    null = os.open(os.devnull, os.O_WRONLY)
    try:
        for fd in descriptors:
            os.dup2(null, fd)
        yield
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        for fd, copy in saved.items():
            os.dup2(copy, fd)
            os.close(copy)
        os.close(null)

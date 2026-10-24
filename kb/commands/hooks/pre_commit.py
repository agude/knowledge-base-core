"""pre-commit - Content-repo hook: lint staged articles and stamp `updated`.

Installed into <content>/.git/hooks/pre-commit by scripts/install.

Two jobs, both deterministic, which is why they belong in a hook rather
than in a curator's memory:

1. Lint them. A second H1, a missing or malformed `verified`, or an
   unclosed code fence corrupts retrieval, and none of it is visible by
   eye. Errors reject the commit; warnings print and let it through. When
   an article is moved or deleted, lint all knowledge articles so unchanged
   inbound links to the old path are checked too.

2. Stamp `updated:` to today on every staged knowledge article. If the
   content changed, the edit date is today; that is a fact. It is NOT
   `verified:`, which asserts that someone confirmed the content still
   holds — stamping that automatically would zero out `stale` forever.

Lint runs FIRST. A hook that rewrites files and then rejects the commit
leaves the author holding modified, staged files and a "rejected"
message that never mentions them.

Commits that stage no knowledge changes — every observe, ask, resolve, and
archive — exit immediately.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from kb import platform
from kb.commands import lint

FENCE = re.compile(r"---\s*")
UPDATED = re.compile(r"updated:\s*")


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], capture_output=True, check=False)


def _nul_split(data: bytes) -> list[str]:
    return [part.decode("utf-8", errors="surrogateescape") for part in data.split(b"\0") if part]


def topology_changed() -> bool:
    """Whether a staged rename or deletion can break an unchanged article's links."""
    result = _git("diff", "--cached", "--quiet", "--diff-filter=DR", "--", "knowledge/", "sources/")
    if result.returncode not in (0, 1):
        print("pre-commit: could not inspect staged link-target paths.", file=sys.stderr)
        raise SystemExit(1)
    if result.returncode == 1:
        return True
    # A pending-to-archived move adds an archive path; removing one still matters.
    entries = _nul_split(
        _git("diff", "--cached", "--name-status", "-z", "--diff-filter=DR", "--").stdout
    )
    index = 0
    while index + 1 < len(entries):
        change, old = entries[index], entries[index + 1]
        if change.startswith("R"):
            new = entries[index + 2] if index + 2 < len(entries) else ""
            if old.startswith("observations/archived/") and old.endswith(".md") and new != old:
                return True
            index += 3
        else:
            if (
                change.startswith("D")
                and old.startswith("observations/archived/")
                and old.endswith(".md")
            ):
                return True
            index += 2
    return False


def _front_matter(lines: list[str]) -> int:
    """The index of the closing `---`, or 0 when line 1 opens no front matter."""
    if not lines or not FENCE.fullmatch(lines[0]):
        return 0
    return next(
        (i for i, line in enumerate(lines[1:], start=1) if FENCE.fullmatch(line)), len(lines)
    )


def current_updated(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    end = _front_matter(lines)
    for line in lines[1:end]:
        if match := UPDATED.match(line):
            return line[match.end() :]
    return ""


def stamped(text: str, today: str) -> str:
    """Every `updated:` line in the front matter set to today; ends with a newline."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    end = _front_matter(lines)
    out = [
        f"updated: {today}" if 0 < i < end and UPDATED.match(line) else line
        for i, line in enumerate(lines)
    ]
    return "".join(f"{line}\n" for line in out)


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    toplevel = (
        _git("rev-parse", "--show-toplevel")
        .stdout.decode("utf-8", errors="surrogateescape")
        .strip()
    )
    # The hook runs in whichever content repository is committing.
    os.environ["KB_CONTENT_DIR"] = toplevel
    names = _nul_split(
        _git(
            "diff", "--cached", "-z", "--name-only", "--diff-filter=ACMR", "--", "knowledge/"
        ).stdout
    )
    staged = [name for name in names if name.endswith(".md") and Path(name).is_file()]
    topology = topology_changed()
    if not staged and not topology:
        return 0

    # 1. Lint, before touching anything.
    arguments = ["--path", f"{toplevel}/knowledge"] if topology else staged
    try:
        status = lint.main(arguments)
    except SystemExit as error:
        status = error.code if isinstance(error.code, int) else 1
    sys.stdout.flush()
    if status:
        print("\npre-commit: lint errors — commit rejected, nothing modified.", file=sys.stderr)
        return 1

    # 2. Stamp updated:.
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    index_file = os.environ.get("GIT_INDEX_FILE", "")
    # A partial commit runs against a temporary index, which discards what the hook stages.
    partial = bool(index_file) and not index_file.endswith(".git/index")
    count = 0
    for name in staged:
        path = Path(name)
        text = platform.read_text(path)
        current = current_updated(text)
        if not current or current == today:
            continue
        if partial:
            print(
                f"pre-commit: {name} has updated: {current}, not {today} (partial commit — not stamping)",
                file=sys.stderr,
            )
            continue
        new = stamped(text, today)
        if not new:
            print(f"pre-commit: could not stamp {name}, leaving it alone", file=sys.stderr)
            continue
        # Through the existing inode: a symlinked article stays a link (audit A-020).
        platform.write_text(path, new)
        _git("add", "--", name)
        count += 1
    if count:
        print(f"pre-commit: stamped updated: {today} on {count} article(s)")
    return 0

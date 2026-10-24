"""status - Summary stats for the knowledge base.

Prints article counts, observation counts, and timestamps for the
most recent knowledge update and observation.

Usage:
  status [--brief]

Options:
  --brief      One line of live state: pending, stale, open questions.
               Injected at session start so the backlog is visible
               instead of silent.
  -h, --help   Show this help message
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kb import cli, paths, platform
from kb.commands import stale
from kb.content import ROOT, content_dir


def count_md(directory: Path) -> int:
    return len(paths.markdown_files(directory)) if directory.is_dir() else 0


def _last_commit(content: Path, area: str) -> str:
    if not (content / ".git").is_dir():
        return "never"
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ai", "--", f"{area}/"],
        cwd=content,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "never"


def brief(content: Path) -> str:
    try:
        stale_count = str(stale.count(content))
    except Exception:  # Bash prints "?" when stale fails for any reason.
        stale_count = "?"
    return (
        f"{count_md(content / 'knowledge')} articles | {count_md(content / 'observations' / 'pending')} pending | "
        f"{stale_count} stale | {count_md(content / 'questions' / 'open')} open question(s)"
    )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(argv, __doc__, flags={"--brief": "brief"})
    content = content_dir()
    if "brief" in args.flags:
        print(brief(content))
        return 0
    lines = [
        f"Knowledge Base: {ROOT}",
        f"Content: {content}",
        "",
        f"  Knowledge articles:    {count_md(content / 'knowledge')}",
        f"  Pending observations:  {count_md(content / 'observations' / 'pending')}",
        f"  Archived observations: {count_md(content / 'observations' / 'archived')}",
        "",
        f"  Last knowledge update: {_last_commit(content, 'knowledge')}",
        f"  Last observation:      {_last_commit(content, 'observations')}",
    ]
    print("\n".join(lines))
    return 0

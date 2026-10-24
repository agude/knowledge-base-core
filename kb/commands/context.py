"""context - Output a brief knowledge base summary for session injection.

Prints a compact summary of the knowledge base: topic list, source
document count, pending observation count, and available scripts.
Intended for injection into an agent context at session start.

Usage:
  context

Options:
  -h, --help   Show this help message
"""

from __future__ import annotations

import sys

from kb import cli, paths, platform
from kb.commands import toc
from kb.commands.status import count_md
from kb.content import ROOT, content_dir

# The agent-facing commands, a fixed list (audit A-016).
SCRIPTS = (
    "archive",
    "ask",
    "batch",
    "commit",
    "context",
    "doctor",
    "evaluate-retrieval",
    "init",
    "lint",
    "observe",
    "pending",
    "questions",
    "resolve",
    "search",
    "section",
    "stale",
    "status",
    "sync",
    "toc",
)


def topics(content) -> list[str]:
    """`toc --depth 1 --flat`, indented, warning once per unreadable article."""
    lines = []
    for path in paths.markdown_files(content / "knowledge"):
        titles = toc.headings(content, path, 1, True)
        if titles is None:
            print(f"toc: cannot read {paths.relative(content, path)}", file=sys.stderr)
            continue
        lines += [f"  {title}" for title in titles]
    return lines


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    cli.parse(argv, __doc__)  # Help, and unknown options rejected (audit A-015).
    content = content_dir()
    out = [f"=== Knowledge Base ({ROOT}) ===", ""]
    count = count_md(content / "knowledge")
    if count:
        out.append(f"Topics ({count} files):")
        out += topics(content)
    else:
        out.append("Topics: (none yet)")
    out += [
        "",
        f"Source documents: {count_md(content / 'sources')}",
        "",
        f"Pending observations: {count_md(content / 'observations' / 'pending')}",
        "",
        f"Scripts: {', '.join(SCRIPTS)}",
        "Usage: $KNOWLEDGE_BASE/scripts/<script> [args]",
    ]
    print("\n".join(out))
    return 0

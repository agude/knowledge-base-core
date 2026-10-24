"""resolve - Mark an open question as resolved.

Moves a question from questions/open/ to questions/resolved/. The answer
is appended to the file for provenance. The curator should also write the
answer into the relevant knowledge article.

Usage:
  resolve --file FILENAME [--answer "..."]
  resolve --file FILENAME --answer - < answer.txt

Options:
  --file FILENAME   Filename in questions/open/ (required)
  --answer TEXT     Answer text appended to the file. Use "-" to read stdin.
  --no-commit       Skip the auto-commit

Examples:
  resolve --file 20260324T220000-0a1b2c3d.md --answer "See knowledge/ach/taxonomy-tool.md § Matching Rules."
  resolve --file 20260324T220000-0a1b2c3d.md --answer "No longer relevant — system decommissioned."
  echo "Long answer..." | resolve --file 20260324T220000-0a1b2c3d.md --answer -
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from kb import cli, frontmatter, git, lock, platform
from kb.content import content_dir


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--file": "file", "--answer": "answer"},
        flags={"--no-commit": "no-commit"},
    )
    name = args.get("file")
    if not name:
        cli.fail("Error: --file is required")
    if "/" in name:
        cli.fail(f"Not a question filename: {name}")
    content = content_dir()
    src = content / "questions" / "open" / name
    dst = content / "questions" / "resolved" / name
    if not src.is_file():
        cli.fail(f"Not found: questions/open/{name}")
    answer = args.get("answer")
    if answer == "-":
        answer = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape").rstrip("\n")
    if answer:
        # Verbatim, even when it looks like an option (audit A-014).
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        platform.append_text(src, f"\n## Resolution ({today})\n\n{answer}\n")
    src.replace(dst)
    print(f"Resolved: questions/open/{name} -> questions/resolved/{name}", flush=True)
    if "no-commit" in args.flags:
        return 0
    title = frontmatter.field(platform.read_text(dst), "title") or name
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            return git.commit_paths(content, f"Resolve: {title}", ["questions/"])
    except lock.LockTimeout as error:
        return lock.report_timeout(error)

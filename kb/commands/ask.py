"""ask - Record an open question in the knowledge base.

Creates a timestamped markdown file in questions/open/. Questions
represent gaps in knowledge that the curator or user should address.

Usage:
  ask --title "..." [--context FILE] [--body "..."]

Options:
  --title TEXT     Question (required)
  --context PATH   Knowledge file or directory this relates to (optional)
  --body TEXT      Additional context (optional). Use - to read stdin.
  --source TEXT    Who created this (default: "session")
  --no-commit      Skip the auto-commit

Examples:
  ask --title "Who owns paycheck-status now?" --context knowledge/ach/pdsa-green-status.md
  ask --title "How does the overdraft exclusion list work?"
  ask --title "Full NOT_A_PAYCHECK_CATEGORY enumeration?" --body "Referenced in pdsa-green-status but never listed."
"""

from __future__ import annotations

import secrets
import sys
from datetime import UTC, datetime

from kb import cli, git, lock, paths, platform
from kb.content import content_dir, yaml_escape


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--title": "title", "--context": "context", "--body": "body", "--source": "source"},
        flags={"--no-commit": "no-commit"},
    )
    title = args.get("title")
    if not title:
        cli.fail("Error: --title is required")
    body = args.get("body")
    if body == "-":
        # As $(cat): trailing newlines are dropped.
        body = sys.stdin.buffer.read().decode("utf-8", errors="surrogateescape").rstrip("\n")
    content = content_dir()
    commit = "no-commit" not in args.flags
    if commit and not (content / ".git").is_dir():
        cli.fail(f"Not a git repository: {content}")  # Before writing (audit A-039).
    context = args.get("context")
    if context:
        try:
            resolved = paths.resolve(content, context)
        except paths.PathError:
            return 1
        if resolved is None:
            cli.fail(f"Not found: {context}")
        context = resolved
    now = datetime.now(UTC)
    name = f"{now:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}.md"
    lines = ["---", f'title: "{yaml_escape(title)}"', f"source: {args.get('source', 'session')}"]
    if context:
        lines.append(f"context: {context}")
    lines += [f"created: {now:%Y-%m-%dT%H:%M:%SZ}", "---"]
    if body:
        lines += ["", body]  # Verbatim, even when it looks like an option (audit A-014).
    platform.write_text(content / "questions" / "open" / name, "\n".join(lines) + "\n")
    print(f"Wrote: questions/open/{name}", flush=True)
    if not commit:
        return 0
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            return git.commit_paths(content, f"Ask: {title}", [f"questions/open/{name}"])
    except lock.LockTimeout as error:
        return lock.report_timeout(error)

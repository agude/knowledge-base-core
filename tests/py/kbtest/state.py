"""The state-v1 fixture: a content repository with every kind of state.

Built in code with fixed content and commit dates, so two builds produce
identical trees and commit hashes. Read-only commands (pending, stale,
status, context, questions, session-context) are pinned against it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ARTICLES = {
    # Verified three days before the harness date (2026-10-23).
    "infra/fresh.md": '---\ntitle: "Fresh"\nupdated: 2026-10-20\nverified: 2026-10-20\n---\n\n'
    "# Fresh\n\n## Current\n\nRecently verified.\n",
    "infra/stale.md": '---\ntitle: "Stale"\nupdated: 2020-01-01\nverified: 2020-01-01\n---\n\n'
    "# Stale\n\n## Old\n\nLong unverified.\n",
    "people/owners.md": '---\ntitle: "Owners"\nupdated: 2026-10-01\nverified: 2026-10-01\nttl: people\n---\n\n'
    "# Owners\n\n## Teams\n\nWho owns what.\n",
    "rules/domain.md": '---\ntitle: "Domain"\nupdated: 2026-06-01\nverified: 2026-06-01\nttl: domain\n---\n\n'
    "# Domain\n\n## Rules\n\nSlow-changing rules.\n",
    "undated.md": '---\ntitle: "Undated"\nupdated: 2026-01-01\n---\n\n# Undated\n\n## Notes\n\nNo verified date.\n',
}

PENDING = {
    "20261001T000000-0000aaaa.md": (
        "Pending fact",
        "session",
        "2026-10-01T00:00:00Z",
        "A fact to curate.",
    ),
    "20261002T000000-0000bbbb.md": (
        "Session transcript (4 messages)",
        "session-transcript",
        "2026-10-02T00:00:00Z",
        "### user\n\nQ\n\n### assistant\n\nA\n",
    ),
    "20261003T000000-0000cccc.md": ("Another fact", "slack", "2026-10-03T00:00:00Z", "From chat."),
}

ARCHIVED = {
    "20260901T000000-0000dddd.md": (
        "Archived fact",
        "2026-09-01T00:00:00Z",
        "incorporated",
        "knowledge/infra/fresh.md#Current",
    ),
    "20260902T000000-0000eeee.md": ("Duplicate fact", "2026-09-02T00:00:00Z", "duplicate", ""),
}

QUESTIONS_OPEN = {
    "20261004T000000-0000ffff.md": ("Who owns the NAS?", "knowledge/people/owners.md"),
    "20261005T000000-00001111.md": ("Why is undated undated?", ""),
}

QUESTIONS_RESOLVED = {"20260903T000000-00002222.md": "What is fresh?"}

SOURCES = {
    "manual.md": '---\ntitle: "Manual"\nsynced: 2026-07-01\n---\n\n# Manual\n\nVendor text.\n',
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _git(content: Path, env: dict[str, str], *args: str, date: str | None = None) -> None:
    run_env = dict(env)
    if date:
        run_env["GIT_AUTHOR_DATE"] = run_env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", *args], cwd=content, env=run_env, check=True, capture_output=True)


def build(content: Path, env: dict[str, str]) -> None:
    """Populate an initialized content repository with the state-v1 history."""
    for name, text in ARTICLES.items():
        _write(content / "knowledge" / name, text)
    for name, text in SOURCES.items():
        _write(content / "sources" / name, text)
    _git(content, env, "add", "-A")
    _git(
        content,
        env,
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "Curate: articles",
        date="2026-10-05T00:00:00Z",
    )

    for name, (title, created, disposition, destination) in ARCHIVED.items():
        lines = [
            f'title: "{title}"',
            "source: session",
            f"created: {created}",
            f"disposition: {disposition}",
        ]
        if destination:
            lines.append(f"destination: {destination}")
        _write(
            content / "observations" / "archived" / name,
            "---\n" + "\n".join(lines) + "\n---\n\nArchived.\n",
        )
    _write(
        content / "questions" / "resolved" / next(iter(QUESTIONS_RESOLVED)),
        f'---\ntitle: "{next(iter(QUESTIONS_RESOLVED.values()))}"\nsource: test\n'
        "created: 2026-09-03T00:00:00Z\n---\n\n## Resolution (2026-09-04)\n\nAnswered.\n",
    )
    _git(content, env, "add", "-A")
    _git(
        content,
        env,
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "Archive: 2 observation(s)",
        date="2026-10-06T00:00:00Z",
    )

    for name, (title, source, created, body) in PENDING.items():
        _write(
            content / "observations" / "pending" / name,
            f'---\ntitle: "{title}"\nsource: {source}\ncreated: {created}\n---\n\n{body}\n',
        )
    for name, (title, context) in QUESTIONS_OPEN.items():
        lines = [f'title: "{title}"', "source: session"]
        if context:
            lines.append(f"context: {context}")
        lines.append("created: 2026-10-04T00:00:00Z")
        _write(content / "questions" / "open" / name, "---\n" + "\n".join(lines) + "\n---\n")
    _git(content, env, "add", "-A")
    _git(
        content,
        env,
        "commit",
        "-q",
        "--no-verify",
        "-m",
        "Observe: pending work",
        date="2026-10-07T00:00:00Z",
    )


def snapshot(content: Path) -> list[tuple[str, bytes]]:
    """Every tracked file and its bytes, for comparing two builds."""
    files = []
    for dirpath, dirnames, filenames in os.walk(content):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in sorted(filenames):
            path = Path(dirpath) / name
            files.append((path.relative_to(content).as_posix(), path.read_bytes()))
    return files

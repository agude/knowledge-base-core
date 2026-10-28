"""kb hook: the Git hook entry point for the content repository.

The pre-commit hook validates the staged articles, refuses staging that the hook cannot
validate, and stamps `updated` after validation passes. It never changes `verified` or
`ttl`. It takes no writer lock: every command that commits already holds it.
"""

import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from kb import args, dates, lint, model, publish
from kb.args import Spec
from kb.errors import KbError

WHO = "hook"
SPEC = Spec(
    usage="hook pre-commit",
    summary=(
        "Validate staged knowledge articles, stamp updated, and refuse unvalidated staging. "
        "Git runs it with the content repository as the working directory."
    ),
)


@dataclass(frozen=True)
class _Edit:
    """The bytes of one article after its updated field is stamped."""

    relpath: str
    content: bytes


def run(words: Sequence[str]) -> int:
    """Run the named hook and return its exit status."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words != ["pre-commit"] or parsed.values or parsed.switches:
        raise SPEC.usage_error()
    try:
        return pre_commit(Path.cwd(), os.environ)
    except (OSError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from None


def pre_commit(root: Path, environ: Mapping[str, str]) -> int:
    """Validate and stamp the staged change set for the commit Git is about to make."""
    changes = _staged_changes(root)
    articles = publish.changed_articles(changes)
    if not articles and not publish.topology_change(changes):
        return 0
    unstaged = _unstaged_articles(root, articles)
    if unstaged:
        for relpath in unstaged:
            _say(f"{relpath} has unstaged changes; stage or discard the unstaged changes")
        return 1
    verdict = publish.validate(root, changes)
    if verdict.blocking:
        for finding in verdict.blocking:
            _say(_finding_line(finding))
        _say("lint errors; commit rejected, nothing modified.")
        return 1
    if verdict.preexisting:
        _say(f"Preexisting (not blocking): {len(verdict.preexisting)}")
        for finding in verdict.preexisting:
            _say(f"  {_finding_line(finding)}")
    today = dates.now(environ).date().isoformat()
    edits, kept = _stamp_edits(root, articles, today, partial=_is_partial(root))
    for relpath, current in kept:
        _say(f"{relpath} has updated: {current}, not {today} (partial commit; not stamping)")
    for edit in edits:
        _write_and_stage(root, edit)
    if edits:
        _say(f"stamped updated: {today} on {len(edits)} article(s)")
    return 0


def _staged_changes(root: Path) -> list[publish.Change]:
    """The index against HEAD, with renames detected and paths read as NUL-delimited fields."""
    result = _git(root, "diff", "--cached", "--name-status", "-z", "-M", "--no-ext-diff")
    _require_success(result, "cannot read the staged changes")
    fields = result.stdout.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    changes: list[publish.Change] = []
    index = 0
    while index < len(fields):
        status = fields[index][:1]
        if status in {"R", "C"}:
            changes.append(publish.Change(status, fields[index + 2], fields[index + 1]))
            index += 3
        else:
            changes.append(publish.Change(status, fields[index + 1]))
            index += 2
    return changes


def _unstaged_articles(root: Path, articles: Sequence[str]) -> list[str]:
    """Staged articles whose worktree bytes differ from the staged blob."""
    if not articles:
        return []
    result = _git(root, "diff", "--name-only", "-z", "--no-ext-diff")
    _require_success(result, "cannot read the unstaged changes")
    differing = set(result.stdout.split("\0"))
    return [relpath for relpath in articles if relpath in differing]


def _is_partial(root: Path) -> bool:
    """Whether Git is committing through a temporary index, as `git commit -- PATH` does."""
    override = os.environ.get("GIT_INDEX_FILE", "")
    if not override:
        return False
    # --git-path index would return the override, so join the index name to the git directory.
    result = _git(root, "rev-parse", "--absolute-git-dir")
    _require_success(result, "cannot locate the Git directory")
    index = Path(result.stdout.strip()) / "index"
    return (root / override).resolve() != index.resolve()


def _stamp_edits(
    root: Path,
    articles: Sequence[str],
    today: str,
    *,
    partial: bool,
) -> tuple[list[_Edit], list[tuple[str, str]]]:
    """Compute every stamp before any write, so a failure leaves the worktree unchanged.

    Returns the edits to make and, for a partial commit, the articles that keep an older
    updated value. A missing updated field is never added; lint reports that instead.
    """
    edits: list[_Edit] = []
    kept: list[tuple[str, str]] = []
    for relpath in articles:
        raw = (root / relpath).read_bytes()
        text = raw.decode("utf-8")
        prefix = "﻿" if text.startswith("﻿") else ""
        body = text[len(prefix) :]
        current = model.parse(relpath, body).scalar("updated")
        if current is None or current == today:
            continue
        if partial:
            kept.append((relpath, current))
            continue
        try:
            stamped = prefix + model.edit_front_matter(body, "updated", today)
        except model.FrontMatterEditError as error:
            raise KbError(f"{WHO}: cannot stamp {relpath}: {error}") from None
        edits.append(_Edit(relpath, stamped.encode("utf-8")))
    return edits, kept


def _write_and_stage(root: Path, edit: _Edit) -> None:
    """Write through the existing path, so a symbolic link and its mode survive, then stage it."""
    (root / edit.relpath).write_bytes(edit.content)
    result = _git(root, "add", "--", edit.relpath)
    _require_success(result, f"cannot stage {edit.relpath}")


def _finding_line(finding: lint.Finding) -> str:
    return f"{finding.path}:{finding.line}: {finding.severity}: {finding.message}"


def _say(text: str) -> None:
    sys.stderr.write(f"{WHO}: {text}\n")


def _require_success(result: subprocess.CompletedProcess[str], message: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.rstrip("\n")
        raise KbError(f"{WHO}: {message}" + (f": {detail}" if detail else ""))


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run Git in the content repository and capture its text output."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

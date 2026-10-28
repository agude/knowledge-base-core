"""Publication rules: which changes are articles, which remove an existing path, and what blocks.

Git supplies the changes, and the commands print the verdict. The classification functions
are pure. Validation reads the content repository's files through corpus and lint, and it
writes nothing.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kb import corpus, lint, model

ARTICLES = "knowledge"
SOURCES = "sources"
ARCHIVED = "observations/archived"
PUBLISHED_ROOTS = (f"{ARTICLES}/", f"{SOURCES}/", "questions/")


@dataclass(frozen=True)
class Change:
    """One path that differs from the comparison commit.

    status is Git's status letter. old_path is set only for renames and copies.
    """

    status: str
    path: str
    old_path: str | None = None


@dataclass(frozen=True)
class Verdict:
    """The findings that refuse publication, and those that exist before this change."""

    blocking: tuple[lint.Finding, ...]
    preexisting: tuple[lint.Finding, ...]


def is_article(path: str) -> bool:
    """Whether a content-relative path is a Markdown article under knowledge/."""
    return path.startswith(f"{ARTICLES}/") and path.endswith(".md")


def is_published(path: str) -> bool:
    """Whether a changed path belongs to the publication set by its directory."""
    return path.startswith(PUBLISHED_ROOTS)


def changed_articles(changes: Iterable[Change]) -> tuple[str, ...]:
    """Articles added, modified, copied, renamed, or type-changed, by their new path."""
    return tuple(
        sorted(
            {change.path for change in changes if change.status != "D" and is_article(change.path)}
        )
    )


def vanished_paths(changes: Iterable[Change]) -> frozenset[str]:
    """Paths that no longer exist after the change: deleted files and the old names of renames."""
    found: set[str] = set()
    for change in changes:
        if change.status == "D":
            found.add(change.path)
        elif change.status == "R" and change.old_path is not None:
            found.add(change.old_path)
    return frozenset(found)


def topology_change(changes: Iterable[Change]) -> bool:
    """Whether an existing path under knowledge/ or sources/, or an archive, is removed or moved.

    A pending observation that moves to the archive is not a topology change: the archive
    side is an addition, and the pending side is not one of the protected roots.
    """
    for path in vanished_paths(changes):
        if path.startswith((f"{ARTICLES}/", f"{SOURCES}/")):
            return True
        if path.startswith(f"{ARCHIVED}/") and path.endswith(".md"):
            return True
    return False


def classify(
    findings: Iterable[lint.Finding],
    changed: frozenset[str],
    vanished: frozenset[str],
) -> Verdict:
    """Split findings into those that block publication and those that already existed.

    A finding in a changed article blocks. A reference finding in any other article blocks
    when its target is a path this change removed. Every other finding is preexisting.
    """
    blocking: list[lint.Finding] = []
    preexisting: list[lint.Finding] = []
    for finding in findings:
        removed_target = finding.target is not None and finding.target in vanished
        if finding.path in changed or removed_target:
            blocking.append(finding)
        else:
            preexisting.append(finding)
    return Verdict(tuple(blocking), tuple(preexisting))


def validate(root: Path, changes: Sequence[Change]) -> Verdict:
    """Lint every article against the worktree, then classify the findings.

    Changed articles are linted with a required TTL and must decode as UTF-8. Every
    article's references are checked, so a removed target is found wherever it is cited.
    """
    changed = frozenset(changed_articles(changes))
    vanished = vanished_paths(changes)
    documents: dict[str, model.Document] = {
        relpath: corpus.read_document(root, relpath)
        for relpath in corpus.markdown_files(root, ARTICLES)
    }
    findings: list[lint.Finding] = []
    for relpath in list(documents):
        if relpath in changed:
            try:
                (root / relpath).read_bytes().decode("utf-8")
            except UnicodeDecodeError:
                findings.append(lint.Finding(relpath, 1, "error", "article is not valid UTF-8"))
        findings.extend(lint.check_document(documents[relpath], require_ttl=relpath in changed))
    for relpath in list(documents):
        findings.extend(lint.reference_findings(root, documents[relpath], documents))
    return classify(findings, changed, vanished)

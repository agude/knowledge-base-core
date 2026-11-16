"""kb curate triage: archive pending transcripts that curation skips, in one commit.

The rules live in kb.triage. This module plans which pending transcripts move, keeps those that
other files still need, moves the rest to the archive with their rule, commits the moves once,
and undoes them when the commit was not made. A process that stops before the commit leaves
moves that sync recovery restores.
"""

import os
import socket
import stat
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from kb import args, corpus, lock, model, observation, triage
from kb.args import Spec
from kb.commands import curate
from kb.commands import sync as sync_command
from kb.commands.curate import ARCHIVED, PENDING, WHO, QueueEntry
from kb.content_paths import fixed_directory
from kb.context import load
from kb.errors import KbError

SPEC = Spec(
    usage="curate triage [--dry-run]",
    summary=(
        "Archive pending session transcripts that a triage rule matches, in one commit. "
        "delegated: the session has a parent. curation: this host's transcript shows the user "
        "invoked the curate skill; every part of that session matches. A transcript that already "
        "has a triage field, that a curated document links to, or whose session a staying "
        "transcript names in forked_from stays. --dry-run lists the matches and changes nothing."
    ),
    switches=frozenset({"--dry-run"}),
)


@dataclass(frozen=True)
class TriagePlan:
    """The pending transcripts that triage archives, with their rules, and those it keeps."""

    chosen: tuple[tuple[QueueEntry, triage.Rule], ...]
    kept: tuple[tuple[str, str], ...]
    # Source transcripts that could not be read, so their curation runs were not detected.
    unreadable: tuple[str, ...] = ()


def run(words: Sequence[str]) -> int:
    """Run kb curate triage and return its exit status."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words or parsed.values:
        raise SPEC.usage_error()
    try:
        wait = lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None
    try:
        context = load(os.environ, sys.platform, Path.home())
        root = context.root
        git_directory = lock.git_dir(root, WHO)
        if "--dry-run" in parsed.switches:
            plan = _triage_plan(root)
            _report_kept(plan)
            for entry, rule in plan.chosen:
                sys.stdout.write(f"{PENDING}/{entry.snapshot.filename}: {rule}\n")
            sys.stdout.write(f"Would triage: {len(plan.chosen)} session transcript(s)\n")
            return 1 if plan.unreadable else 0
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, wait, backend):
            host = observation.short_host(socket.gethostname())
            sync_command.recover(root, git_directory, host)
            curate.require_clean_tree(root)
            curate.check_existing_batches(root)
            plan = _triage_plan(root)
            _report_kept(plan)
            if plan.chosen:
                _archive_triaged(root, git_directory, plan.chosen)
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(_triage_summary(plan.chosen))
    return 1 if plan.unreadable else 0


def _triage_plan(root: Path) -> TriagePlan:
    """Match each pending transcript against the triage rules, without changing anything.

    delegated comes from front matter, so it covers every host's transcripts. curation comes
    from this host's transcripts, so each host triages its own curation runs.
    """
    entries = curate.pending_entries(root)
    fronts = {entry.snapshot.filename: entry.document for entry in entries}
    curation_runs, unreadable = _curation_sessions()
    rules: dict[str, triage.Rule] = {}
    for filename, front in fronts.items():
        rule = triage.from_front_matter(front)
        session = (front.scalar("app"), front.scalar("session"))
        if rule is None and _is_untriaged_transcript(front) and session in curation_runs:
            rule = "curation"
        if rule is not None:
            rules[filename] = rule
    references = curate.inbound_references(root)
    kept = {
        filename: "is linked from curated documents"
        for filename in rules
        if (root / PENDING / filename).resolve() in references
    }
    _keep_fork_owners(root, fronts, rules, kept)
    chosen = [
        (entry, rules[entry.snapshot.filename])
        for entry in entries
        if entry.snapshot.filename in rules and entry.snapshot.filename not in kept
    ]
    return TriagePlan(tuple(chosen), tuple(sorted(kept.items())), unreadable)


def _is_untriaged_transcript(front: model.Document) -> bool:
    return front.scalar("source") == triage.TRANSCRIPT and triage.FIELD not in front.front


def _curation_sessions() -> tuple[frozenset[tuple[str | None, str | None]], tuple[str, ...]]:
    """The (app, session) keys of this host's curation runs, and the transcripts not read."""
    scanned = sync_command.scan_transcripts(os.environ)
    runs = frozenset(
        (candidate.session.app, candidate.session.id)
        for candidate in scanned.candidates
        if triage.for_session(candidate.session) == "curation"
    )
    return runs, tuple(f"{failure.session}: {failure.reason}" for failure in scanned.failures)


def _keep_fork_owners(
    root: Path,
    fronts: Mapping[str, model.Document],
    rules: Mapping[str, triage.Rule],
    kept: dict[str, str],
) -> None:
    """Keep each matched transcript whose session a staying transcript names in forked_from.

    A transcript that names a session in forked_from left its shared prefix in that session's
    observation, so the owner must stay wherever the naming transcript stays: in pending, kept
    in pending, or curated in the archive. A kept owner protects its own owner in turn.
    """
    by_session: dict[str, list[str]] = {}
    for filename in rules:
        session = fronts[filename].scalar("session")
        if session:
            by_session.setdefault(session, []).append(filename)
    staying = [
        front for filename, front in fronts.items() if filename not in rules or filename in kept
    ]
    staying.extend(_curated_archives(root))
    owners = [owner for front in staying if (owner := _forked_from(front))]
    while owners:
        for filename in by_session.get(owners.pop(), ()):
            if filename in kept:
                continue
            kept[filename] = "holds shared messages that a staying transcript names in forked_from"
            if owner := _forked_from(fronts[filename]):
                owners.append(owner)


def _forked_from(front: model.Document) -> str | None:
    if front.scalar("source") != triage.TRANSCRIPT:
        return None
    return front.scalar("forked_from") or None


def _curated_archives(root: Path) -> list[model.Document]:
    """The front matter of the archived transcripts that curation read.

    Curation's archives carry curation_batch, and older ones have no triage field. A
    transcript restored to pending by hand keeps its triage field when curation archives it,
    so curation_batch decides. Only an archive that triage made, with triage and no
    curation_batch, is left out.
    """
    directory = fixed_directory(root, ARCHIVED, command=WHO, create=False, optional=True)
    if directory is None:
        return []
    documents: list[model.Document] = []
    for path in sorted(directory.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        front = model.parse_front_matter(path.name, corpus.strip_bom(path.read_text("utf-8")))
        if _is_untriaged_transcript(front) or (
            front.scalar("source") == triage.TRANSCRIPT and "curation_batch" in front.front
        ):
            documents.append(front)
    return documents


def _report_kept(plan: TriagePlan) -> None:
    for failure in plan.unreadable:
        sys.stderr.write(
            f"{WHO}: cannot inspect transcript {failure}; a curation run it holds stays pending\n"
        )
    for filename, reason in plan.kept:
        sys.stderr.write(f"{WHO}: warning: {PENDING}/{filename} {reason}; kept in pending\n")


def _triage_summary(chosen: Sequence[tuple[QueueEntry, triage.Rule]]) -> str:
    rules = Counter(rule for _, rule in chosen)
    lines = [f"Triaged: {len(chosen)} session transcript(s)"]
    lines.extend(f"  {rule}: {rules[rule]}" for rule in sorted(rules))
    return "\n".join(lines) + "\n"


def _archive_triaged(
    root: Path, git_directory: Path, chosen: Sequence[tuple[QueueEntry, triage.Rule]]
) -> None:
    """Move each chosen pending transcript to the archive with its rule, in one commit.

    On a failure before the commit exists, the worktree is restored. A process that stops
    before the commit leaves a move that recovery restores.
    """
    rendered = [(entry, _triaged_bytes(entry, rule)) for entry, rule in chosen]
    previous_head = curate.head_commit(root)
    published: list[str] = []
    removed: list[QueueEntry] = []
    try:
        for entry, content in rendered:
            filename = entry.snapshot.filename
            pending = root / PENDING / filename
            curate.publish_archive(
                root, git_directory, filename, content, stat.S_IMODE(pending.lstat().st_mode)
            )
            published.append(filename)
            pending.unlink()
            removed.append(entry)
        names = [entry.snapshot.filename for entry, _ in chosen]
        paths = [f"{PENDING}/{name}" for name in names] + [f"{ARCHIVED}/{name}" for name in names]
        curate.commit_set(root, git_directory, paths, "triage", lambda _: _triage_message(chosen))
    except BaseException as error:
        _undo_triage(root, previous_head, published, removed, error)
        raise


def _triaged_bytes(entry: QueueEntry, rule: triage.Rule) -> bytes:
    """The pending file's bytes with its triage rule added to the front matter."""
    bom, text = corpus.split_bom(entry.snapshot.content.decode("utf-8"))
    try:
        edited = model.edit_front_matter(text, triage.FIELD, rule)
    except model.FrontMatterEditError as error:
        raise KbError(
            f"{WHO}: cannot triage {PENDING}/{entry.snapshot.filename}: {error}"
        ) from error
    return (bom + edited).encode("utf-8")


def _triage_message(chosen: Sequence[tuple[QueueEntry, triage.Rule]]) -> str:
    """The triage commit's message: a count, then the count for each rule."""
    rules = Counter(rule for _, rule in chosen)
    lines = [
        f"Triage: {len(chosen)} session transcript(s)",
        "",
        "Filed in observations/archived/ by triage rule; curation does not read them.",
        "",
        "Rules:",
        *(f"- {rule}: {rules[rule]}" for rule in sorted(rules)),
    ]
    return "\n".join(lines) + "\n"


def _undo_triage(
    root: Path,
    previous_head: str,
    published: Sequence[str],
    removed: Sequence[QueueEntry],
    error: BaseException,
) -> None:
    """Restore the pending files and remove the new archives when no commit was made."""
    try:
        if curate.head_commit(root) != previous_head:
            return
        for entry in removed:
            pending = root / PENDING / entry.snapshot.filename
            pending.write_bytes(entry.snapshot.content)
            pending.chmod(stat.S_IMODE((root / ARCHIVED / entry.snapshot.filename).stat().st_mode))
        for filename in published:
            (root / ARCHIVED / filename).unlink(missing_ok=True)
    except (OSError, KbError) as cleanup:
        raise KbError(
            f"{WHO}: cannot undo triage: {cleanup}; inspect Git status; original failure: {error}"
        ) from error

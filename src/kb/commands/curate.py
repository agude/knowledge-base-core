"""Local curation batch selection and progress reporting."""

import hashlib
import os
import shlex
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from subprocess import run as run_process
from typing import cast

from kb import (
    archive,
    args,
    corpus,
    curation,
    dates,
    evidence,
    freshness,
    lint,
    locators,
    lock,
    model,
    secrets,
)
from kb.args import Spec
from kb.commands import recall as recall_command
from kb.context import Context, load
from kb.errors import KbError

WHO = "curate"
PENDING = "observations/pending"
ARCHIVED = "observations/archived"
BATCHES = "observations/batches"
MAX_REPORT_ITEMS = curation.MAX_REPORT_ITEMS
START_SPEC = Spec(
    usage="curate start --max-bytes N [FILENAME...]",
    summary=(
        "Create a local batch from pending observations. N counts original UTF-8 bytes; "
        "selection is bounded and remains unpublished until committed."
    ),
    valued=frozenset({"--max-bytes"}),
)
STATUS_SPEC = Spec(
    usage="curate status RUN",
    summary="Show local batch progress and any commands needed to recover or drop an item.",
)
NEXT_SPEC = Spec(
    usage="curate next RUN [--query TEXT]",
    summary=(
        "Show the next unchanged observation in full with matching curated sections and open "
        "questions. --query overrides the observation title for related context."
    ),
    valued=frozenset({"--query"}),
)
COMPLETE_SPEC = Spec(
    usage="curate complete RUN FILENAME --disposition DISPOSITION [--reason TEXT] [LOCATOR...]",
    summary=(
        "Record an observation outcome and archive it. Incorporated and duplicate outcomes need "
        "knowledge locators; ephemeral outcomes need a reason."
    ),
    valued=frozenset({"--disposition", "--reason"}),
)
DEFER_SPEC = Spec(
    usage="curate defer RUN FILENAME --reason TEXT",
    summary="Keep an unchanged pending observation for a later local batch.",
    valued=frozenset({"--reason"}),
)
DROP_SPEC = Spec(
    usage="curate drop RUN FILENAME --reason TEXT",
    summary="Settle a pending member whose input is missing or changed without altering that file.",
    valued=frozenset({"--reason"}),
)
SPEC = Spec(
    usage="curate {start,status,next,complete,defer,drop} ...",
    summary=(
        "Manage local curation batches. Start selects bounded input; status reports persisted "
        "progress without changing files or contacting Git. Complete records outcomes and "
        "archives unchanged observations."
    ),
)


@dataclass(frozen=True)
class QueueEntry:
    """One eligible pending observation and its parsed metadata warnings."""

    snapshot: curation.PendingInput
    title: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class StaleArticle:
    """A stale knowledge article surfaced by the selected observations."""

    path: str
    status: str


def run(words: Sequence[str]) -> int:
    """Dispatch local curation batch commands."""
    if not words or words[0] in args.HELP_FLAGS:
        sys.stdout.write(SPEC.help_text())
        return 0
    command, *arguments = words
    if command == "start":
        return _start_command(arguments)
    if command == "status":
        return _status_command(arguments)
    if command == "next":
        return _next_command(arguments)
    if command == "complete":
        return _complete_command(arguments)
    if command == "defer":
        return _defer_command(arguments)
    if command == "drop":
        return _drop_command(arguments)
    raise KbError(f"Usage: kb {SPEC.usage}")


def _start_command(words: Sequence[str]) -> int:
    parsed = args.parse(START_SPEC, words)
    if parsed.help:
        sys.stdout.write(START_SPEC.help_text())
        return 0
    raw_budget = parsed.values.get("--max-bytes")
    if raw_budget is None:
        raise START_SPEC.usage_error()
    if not raw_budget.isascii() or not raw_budget.isdigit():
        raise KbError(f"{WHO}: --max-bytes must be a nonnegative ASCII decimal integer")
    max_bytes = int(raw_budget)
    try:
        wait = lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise START_SPEC.usage_error() from None

    try:
        context = load(os.environ, sys.platform, Path.home())
        git_directory = lock.git_dir_path(context.root, WHO)
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, context.root, wait, backend):
            return _start(context, git_directory, max_bytes, parsed.words)
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except curation.SelectionError as error:
        raise KbError(f"{WHO}: {error}") from error
    except curation.StateError as error:
        raise KbError(f"{WHO}: {error}") from error
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error


def _status_command(words: Sequence[str]) -> int:
    parsed = args.parse(STATUS_SPEC, words)
    if parsed.help:
        sys.stdout.write(STATUS_SPEC.help_text())
        return 0
    if len(parsed.words) != 1:
        raise STATUS_SPEC.usage_error()
    try:
        context = load(os.environ, sys.platform, Path.home())
        batch = _read_batch(context.root, parsed.words[0])
        status, exit_code = _status(context.root, batch)
    except curation.StateError as error:
        raise KbError(f"{WHO}: {error}") from error
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(status)
    return exit_code


def _next_command(words: Sequence[str]) -> int:
    parsed = args.parse(NEXT_SPEC, words)
    if parsed.help:
        sys.stdout.write(NEXT_SPEC.help_text())
        return 0
    if len(parsed.words) != 1:
        raise NEXT_SPEC.usage_error()
    try:
        context = load(os.environ, sys.platform, Path.home())
        batch = _read_batch(context.root, parsed.words[0])
        output, exit_code = _next(context, batch, parsed.values.get("--query"))
    except curation.StateError as error:
        raise KbError(f"{WHO}: {error}") from error
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(output)
    return exit_code


def _complete_command(words: Sequence[str]) -> int:
    parsed = args.parse(COMPLETE_SPEC, words)
    if parsed.help:
        sys.stdout.write(COMPLETE_SPEC.help_text())
        return 0
    if len(parsed.words) < 2:
        raise COMPLETE_SPEC.usage_error()
    raw_disposition = parsed.values.get("--disposition")
    if raw_disposition not in {"incorporated", "duplicate", "ephemeral"}:
        raise KbError("curate: --disposition must be incorporated, duplicate, or ephemeral")
    try:
        wait = lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise COMPLETE_SPEC.usage_error() from None

    try:
        context = load(os.environ, sys.platform, Path.home())
        git_directory = lock.git_dir_path(context.root, WHO)
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, context.root, wait, backend):
            batch = _read_batch(context.root, parsed.words[0])
            output = _complete(
                context,
                git_directory,
                batch,
                parsed.words[1],
                cast(curation.Disposition, raw_disposition),
                parsed.words[2:],
                parsed.values.get("--reason"),
            )
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except curation.StateError as error:
        raise KbError(f"{WHO}: {error}") from error
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(output)
    return 0


def _defer_command(words: Sequence[str]) -> int:
    return _transition_command(words, DEFER_SPEC, "deferred")


def _drop_command(words: Sequence[str]) -> int:
    return _transition_command(words, DROP_SPEC, "dropped")


def _transition_command(words: Sequence[str], spec: Spec, outcome: str) -> int:
    """Run a locked reason-bearing transition that only replaces the manifest."""
    parsed = args.parse(spec, words)
    if parsed.help:
        sys.stdout.write(spec.help_text())
        return 0
    reason = parsed.values.get("--reason")
    if len(parsed.words) != 2 or reason is None:
        raise spec.usage_error()
    try:
        wait = lock.parse_wait(os.environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise spec.usage_error() from None

    try:
        context = load(os.environ, sys.platform, Path.home())
        git_directory = lock.git_dir_path(context.root, WHO)
        backend = lock.default_backend(sys.platform)
        with lock.write_lock(git_directory, context.root, wait, backend):
            batch = _read_batch(context.root, parsed.words[0])
            output = _transition_member(
                context,
                git_directory,
                batch,
                parsed.words[1],
                reason,
                outcome,
            )
    except lock.LockBusy as busy:
        raise KbError(
            f"{WHO}: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except curation.StateError as error:
        raise KbError(f"{WHO}: {error}") from error
    except KbError as error:
        if str(error).startswith((f"{WHO}:", "Usage:")):
            raise
        raise KbError(f"{WHO}: {error}") from error
    except (OSError, RuntimeError, UnicodeError) as error:
        raise KbError(f"{WHO}: {error}") from error
    sys.stdout.write(output)
    return 0


def _start(
    context: Context,
    git_directory: Path,
    max_bytes: int,
    explicit_names: Sequence[str],
) -> int:
    """Validate repository gates, snapshot the chosen inputs, and publish one manifest."""
    root = context.root
    _require_clean_tree(root)
    _check_existing_batches(root)
    entries = _pending_entries(root)
    selection = curation.select(
        [entry.snapshot for entry in entries],
        max_bytes,
        explicit_names if explicit_names else None,
    )
    entry_by_name = {entry.snapshot.filename: entry for entry in entries}
    selected_entries = [entry_by_name[item.filename] for item in selection.selected]
    stale_articles = _related_stale(root, context, selected_entries)
    open_question_count = len(corpus.markdown_files(root, "questions/open"))

    if not selection.selected:
        sys.stdout.write(
            _start_report(
                None,
                max_bytes,
                len(entries),
                selection,
                entries,
                open_question_count,
                stale_articles,
            )
        )
        if not entries:
            sys.stdout.write("No pending observations.\n")
        else:
            sys.stdout.write(f"No observations fit --max-bytes {max_bytes}.\n")
        return 1

    now = dates.now(os.environ)
    members = [curation.make_member(item.filename, item.content) for item in selection.selected]
    batch = curation.make_batch(
        curation.make_run_id(now, os.urandom(4).hex()), now, max_bytes, members
    )
    batches_directory = _fixed_directory(root, BATCHES, create=True)
    assert batches_directory is not None
    target = batches_directory / f"{batch.id}.json"
    if target.exists() or target.is_symlink():
        raise KbError(f"{WHO}: batch manifest already exists: {target.name}")
    _publish_manifest(git_directory, target, curation.render_batch(batch))
    sys.stdout.write(
        _start_report(
            batch.id,
            max_bytes,
            len(entries),
            selection,
            entries,
            open_question_count,
            stale_articles,
        )
    )
    return 0


def _status(root: Path, batch: curation.Batch) -> tuple[str, int]:
    """Format progress, checking pending inputs and archives without mutations."""
    counts = Counter(member.status for member in batch.members)
    dispositions = Counter(
        member.disposition for member in batch.members if member.disposition is not None
    )
    destination_counts = Counter(
        destination.locator for member in batch.members for destination in member.destinations
    )
    lines = [
        f"Batch {batch.id}: {len(batch.members)} observation(s)",
        f"States: pending={counts['pending']}, archiving={counts['archiving']}, "
        f"complete={counts['complete']}, deferred={counts['deferred']}, dropped={counts['dropped']}",
        f"Dispositions: incorporated={dispositions['incorporated']}, "
        f"duplicate={dispositions['duplicate']}, ephemeral={dispositions['ephemeral']}",
        f"Remaining pending bytes: "
        f"{sum(member.original_bytes for member in batch.members if member.status == 'pending')}",
    ]
    if destination_counts:
        lines.append("Destinations:")
        lines.extend(
            f"  {locator} ({count} item(s))"
            for locator, count in sorted(destination_counts.items())
        )
    else:
        lines.append("Destinations: none")

    problems: list[str] = []
    for status in ("pending", "deferred", "dropped"):
        members = [member for member in batch.members if member.status == status]
        if not members:
            continue
        lines.append(f"{status.capitalize()} work:")
        for index, member in enumerate(members):
            is_displayed = index < MAX_REPORT_ITEMS
            if is_displayed:
                detail = f" — {member.reason}" if member.reason is not None else ""
                lines.append(f"  {member.filename}{detail}")
            if status == "pending" and not _matches_snapshot(root, PENDING, member):
                problems.append(member.filename)
                lines.append(f"  Changed or missing: {PENDING}/{member.filename}")
                lines.append(
                    "  Run: "
                    + shlex.join(["kb", "curate", "drop", batch.id, member.filename])
                    + " --reason TEXT"
                )
        omitted = len(members) - MAX_REPORT_ITEMS
        if omitted:
            lines.append(f"  ... {omitted} more {status} item(s)")

    for member in batch.members:
        if member.status == "archiving":
            lines.append("Archive recovery:")
            lines.append("  Run: " + shlex.join(_completion_words(batch.id, member)))
        elif member.status == "complete" and not _matches_snapshot(
            root, ARCHIVED, member, archive=True
        ):
            lines.append(f"Inconsistent complete archive: {ARCHIVED}/{member.filename}")
            problems.append(member.filename)

    if curation.is_settled(batch):
        lines.append("Batch is locally settled and unpublished.")
    return "\n".join(lines) + "\n", int(bool(problems))


def _next(context: Context, batch: curation.Batch, query_override: str | None) -> tuple[str, int]:
    """Render the first pending member with recall context, without changing state."""
    recoverable = [member for member in batch.members if member.status == "archiving"]
    if recoverable:
        commands = [
            "Run: " + shlex.join(_completion_words(batch.id, member)) for member in recoverable
        ]
        return "\n".join(
            ["Batch has an interrupted archive; finish it before presenting more work.", *commands]
        ) + "\n", 1

    pending = next((member for member in batch.members if member.status == "pending"), None)
    if pending is None:
        return "No pending members; batch is locally settled and unpublished.\n", 0

    content = _snapshot_bytes(context.root, PENDING, pending)
    if content is None:
        command = (
            shlex.join(["kb", "curate", "drop", batch.id, pending.filename]) + " --reason TEXT"
        )
        return (
            f"Pending input is missing or changed: {PENDING}/{pending.filename}\nRun: {command}\n",
            1,
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"{WHO}: pending observation is not valid UTF-8: {error.reason}") from error
    document = model.parse(f"{PENDING}/{pending.filename}", text.removeprefix("\ufeff"))
    query = query_override if query_override is not None else (document.title or "")
    query_words = [query] if query else []
    sections = recall_command.matching_sections(context, query_words, limit=3)
    question_rows = recall_command.matching_open_question_rows(
        context, query_words, has_curated_matches=bool(sections)
    )
    return _render_next(batch, pending, content, text, query, sections, question_rows), 0


def _complete(
    context: Context,
    git_directory: Path,
    batch: curation.Batch,
    filename: str,
    disposition: curation.Disposition,
    destination_words: Sequence[str],
    reason: str | None,
) -> str:
    """Record an outcome and finish or resume its durable archive intent."""
    root = context.root
    _scan_completion_text(destination_words, reason)
    member = next((item for item in batch.members if item.filename == filename), None)
    if member is None:
        raise KbError(f"{WHO}: not a batch member")
    try:
        destinations = _requested_destinations(root, destination_words, disposition, reason)
    except KbError as error:
        if member.status != "archiving":
            raise
        command = shlex.join(_completion_words(batch.id, member))
        raise KbError(f"{error}; resume with: {command}") from error

    if member.status == "complete":
        if not _same_outcome(member, disposition, destinations, reason):
            raise KbError(f"{WHO}: member is complete with a different outcome")
        pending_bytes = _member_file_bytes(root, PENDING, member.filename)
        archive_bytes = _member_file_bytes(root, ARCHIVED, member.filename)
        if pending_bytes is not None:
            raise KbError(f"{WHO}: completed member still has a pending copy; inspect manually")
        if (
            archive_bytes is None
            or hashlib.sha256(archive_bytes).hexdigest() != member.archive_sha256
        ):
            raise KbError(f"{WHO}: completed archive is missing or changed; inspect manually")
        return _archived_line(member.filename)

    if member.status not in {"pending", "archiving"}:
        raise KbError(f"{WHO}: cannot complete member in {member.status} state")
    if member.status == "archiving":
        if not _same_outcome(member, disposition, destinations, reason):
            command = shlex.join(_completion_words(batch.id, member))
            raise KbError(
                f"{WHO}: requested outcome differs from the stored archive intent; "
                f"resume with: {command}"
            )
        if tuple(destinations) != member.destinations:
            command = shlex.join(_completion_words(batch.id, member))
            raise KbError(
                f"{WHO}: destination heading changed since the archive intent; inspect the "
                f"article, then resume with: {command}"
            )
        try:
            return _resume_archive(context, git_directory, batch, member)
        except Exception as error:
            command = shlex.join(_completion_words(batch.id, member))
            raise KbError(
                f"{WHO}: archive operation failed: {error}; inspect the files, "
                f"then resume with: {command}"
            ) from error

    original = _member_file_bytes(root, PENDING, member.filename)
    if original is None or not _matches_bytes(member, original):
        raise KbError(f"{WHO}: input is changed or missing")
    if _member_file_bytes(root, ARCHIVED, member.filename) is not None:
        raise KbError(f"{WHO}: archive already exists: {ARCHIVED}/{member.filename}")
    _refuse_inbound_pending_references(root, member.filename)

    try:
        original_text = original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise KbError(f"{WHO}: pending observation is not valid UTF-8: {error.reason}") from error
    try:
        rendered = archive.render(
            original_text,
            disposition,
            member.original_sha256,
            batch.id,
            destinations,
            reason,
        ).encode("utf-8")
    except (model.FrontMatterEditError, curation.StateError) as error:
        raise KbError(f"{WHO}: unsafe pending front matter or outcome: {error}") from error

    intent = curation.begin_archive(
        member,
        disposition,
        destinations,
        reason,
        hashlib.sha256(rendered).hexdigest(),
    )
    intent_batch = curation.replace_member(batch, intent)
    manifest = _batch_path(root, batch.id)
    try:
        _replace_manifest(git_directory, manifest, intent_batch)
        return _resume_archive(context, git_directory, intent_batch, intent)
    except Exception as error:
        persisted = _read_batch(root, batch.id)
        persisted_member = next(item for item in persisted.members if item.filename == filename)
        if persisted_member.status in {"archiving", "complete"}:
            command = shlex.join(_completion_words(batch.id, persisted_member))
            raise KbError(
                f"{WHO}: archive operation failed: {error}; inspect the files, "
                f"then resume with: {command}"
            ) from error
        raise


def _transition_member(
    context: Context,
    git_directory: Path,
    batch: curation.Batch,
    filename: str,
    reason: str,
    outcome: str,
) -> str:
    """Defer an unchanged input or drop a changed/missing one in the manifest only."""
    _scan_completion_text((), reason)
    if not reason.strip() or "\n" in reason or "\r" in reason:
        raise KbError(f"{WHO}: {outcome} reason must be nonempty and single-line")
    member = next((item for item in batch.members if item.filename == filename), None)
    if member is None:
        raise KbError(f"{WHO}: not a batch member")
    if member.status == outcome:
        if member.reason == reason:
            return f"{outcome.capitalize()}: {filename} in batch {batch.id}\n"
        raise KbError(f"{WHO}: member is already {outcome} with a different reason")
    if member.status != "pending":
        verb = "defer" if outcome == "deferred" else "drop"
        raise KbError(f"{WHO}: cannot {verb} member in {member.status} state")

    content = _member_file_bytes(context.root, PENDING, filename)
    unchanged = content is not None and _matches_bytes(member, content)
    if outcome == "deferred":
        if not unchanged:
            raise KbError(f"{WHO}: input is changed or missing; use drop to settle this member")
        updated = curation.defer_member(member, reason)
    else:
        if unchanged:
            raise KbError(f"{WHO}: input is unchanged; use defer to keep it for a later batch")
        updated = curation.drop_member(member, reason)

    updated_batch = curation.replace_member(batch, updated)
    _replace_manifest(
        git_directory,
        _batch_path(context.root, batch.id),
        updated_batch,
    )
    return f"{outcome.capitalize()}: {filename} in batch {batch.id}\n"


def _resume_archive(
    context: Context,
    git_directory: Path,
    batch: curation.Batch,
    member: curation.Member,
) -> str:
    """Apply the recovery table to an already persisted archive intent."""
    root = context.root
    stored_destinations = _requested_destinations(
        root,
        [destination.locator for destination in member.destinations],
        cast(curation.Disposition, member.disposition),
        member.reason,
    )
    if stored_destinations != member.destinations:
        raise KbError(f"{WHO}: a destination heading changed; inspect the archive intent")
    _refuse_inbound_pending_references(root, member.filename)

    pending_bytes = _member_file_bytes(root, PENDING, member.filename)
    archive_bytes = _member_file_bytes(root, ARCHIVED, member.filename)
    pending_exists = _member_file_exists(root, PENDING, member.filename)
    archive_exists = _member_file_exists(root, ARCHIVED, member.filename)
    if pending_exists and (pending_bytes is None or not _matches_bytes(member, pending_bytes)):
        raise KbError(f"{WHO}: pending copy changed; manual inspection needed")
    if archive_exists and (
        archive_bytes is None or hashlib.sha256(archive_bytes).hexdigest() != member.archive_sha256
    ):
        raise KbError(f"{WHO}: archive conflicts with the stored intent; manual inspection needed")
    if not pending_exists and not archive_exists:
        raise KbError(f"{WHO}: both copies are missing; manual inspection needed")

    if pending_exists and not archive_exists:
        assert pending_bytes is not None
        try:
            original_text = pending_bytes.decode("utf-8")
            rendered = archive.render(
                original_text,
                cast(curation.Disposition, member.disposition),
                member.original_sha256,
                batch.id,
                member.destinations,
                member.reason,
            ).encode("utf-8")
        except (UnicodeDecodeError, model.FrontMatterEditError, curation.StateError) as error:
            raise KbError(f"{WHO}: cannot reconstruct the expected archive: {error}") from error
        if hashlib.sha256(rendered).hexdigest() != member.archive_sha256:
            raise KbError(f"{WHO}: reconstructed archive does not match the stored intent")
        source_mode = (root / PENDING / member.filename).stat().st_mode
        _publish_archive(root, git_directory, member.filename, rendered, stat.S_IMODE(source_mode))
        archive_exists = True

    if pending_exists:
        _remove_pending(root, member)

    completed = curation.finish_archive(member)
    completed_batch = curation.replace_member(batch, completed)
    _replace_manifest(git_directory, _batch_path(root, batch.id), completed_batch)
    return _archived_line(member.filename)


def _requested_destinations(
    root: Path,
    words: Sequence[str],
    disposition: curation.Disposition,
    reason: str | None,
) -> tuple[curation.Destination, ...]:
    """Resolve, canonicalize, and validate a caller's outcome destinations."""
    if disposition == "ephemeral":
        if words:
            raise KbError(f"{WHO}: ephemeral outcome does not accept destinations")
        if reason is None or not reason.strip() or "\n" in reason or "\r" in reason:
            raise KbError(f"{WHO}: ephemeral outcome needs a nonempty single-line --reason")
        return ()
    if reason is not None:
        raise KbError(f"{WHO}: --reason is only valid for an ephemeral outcome")
    if not words:
        raise KbError(f"{WHO}: {disposition} outcome needs at least one knowledge destination")

    destinations: list[curation.Destination] = []
    seen: set[str] = set()
    for word in words:
        locator = locators.parse_locator(word)
        relpath = corpus.resolve_path(root, locator.path, WHO)
        if relpath is None:
            raise KbError(f"{WHO}: no such destination: {word}")
        if not relpath.startswith("knowledge/") or not relpath.endswith(".md"):
            raise KbError(f"{WHO}: destination must resolve under knowledge/: {relpath}")
        path = root / relpath
        if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
            raise KbError(f"{WHO}: destination must name a contained Markdown file: {relpath}")
        document = corpus.read_document(root, relpath)
        fragment = locator.fragment
        heading: str | None = None
        if fragment is not None:
            selection = locators.select(document, fragment)
            if selection is None:
                available = [f"  {item}" for item in locators.outline(document)]
                raise KbError(
                    "\n".join(
                        [f"{WHO}: {relpath} has no section {fragment}. Its locators:", *available]
                    )
                )
            heading = selection.heading
        if disposition == "duplicate" and (
            fragment is None or locators.NUMBERED.fullmatch(fragment) is None
        ):
            raise KbError(f"{WHO}: duplicate destinations must name numbered sections")
        canonical = relpath if fragment is None else f"{relpath}#{fragment}"
        if canonical in seen:
            continue
        seen.add(canonical)
        destinations.append(curation.Destination(canonical, heading))
    return tuple(destinations)


def _same_outcome(
    member: curation.Member,
    disposition: curation.Disposition,
    destinations: Sequence[curation.Destination],
    reason: str | None,
) -> bool:
    """Compare outcome fields and canonical locators, excluding current heading text."""
    stored = tuple(item.locator for item in member.destinations)
    requested = tuple(item.locator for item in destinations)
    return member.disposition == disposition and member.reason == reason and stored == requested


def _scan_completion_text(destination_words: Sequence[str], reason: str | None) -> None:
    """Scan supplied locators and reasons before diagnostics or state writes."""
    entries = [(f"destination {index}", word) for index, word in enumerate(destination_words, 1)]
    if reason is not None:
        entries.append(("--reason", reason))
    for label, value in entries:
        findings = secrets.findings(Path(tempfile.gettempdir()), value)
        if findings:
            detectors = ", ".join(sorted({detector for detector, _line in findings}))
            raise KbError(f"{WHO}: possible secret in {label}: {detectors}")


def _refuse_inbound_pending_references(root: Path, filename: str) -> None:
    """Refuse curated documents that still point at the pending file."""
    pending = (root / PENDING / filename).resolve()
    found: list[str] = []
    for directory in ("knowledge", "sources"):
        for relpath in corpus.markdown_files(root, directory):
            document = corpus.read_document(root, relpath)
            for reference in lint.references(document):
                target_text = reference.destination.partition("#")[0]
                if (
                    not target_text
                    or target_text.startswith("/")
                    or target_text.startswith("//")
                    or PureWindowsPath(target_text).is_absolute()
                ):
                    continue
                base = root if reference.kind == "source" else (root / relpath).parent
                try:
                    target = (base / target_text).resolve()
                except (OSError, RuntimeError) as error:
                    raise KbError(
                        f"{WHO}: cannot resolve a reference in {relpath}: {error}"
                    ) from error
                if target == pending:
                    found.append(f"{reference.source_path}:{reference.line} ({reference.kind})")
    if found:
        lines = [
            f"{WHO}: references still target the pending observation {PENDING}/{filename}:",
            *(f"  {item}" for item in sorted(set(found))),
        ]
        raise KbError("\n".join(lines))


def _batch_path(root: Path, run_id: str) -> Path:
    """The validated file path for a batch manifest that must already exist."""
    directory = _fixed_directory(root, BATCHES, create=False)
    assert directory is not None
    path = directory / f"{run_id}.json"
    if path.is_symlink() or not path.is_file():
        raise KbError(f"{WHO}: batch manifest is missing or unsafe: {run_id}")
    return path


def _replace_manifest(git_directory: Path, target: Path, batch: curation.Batch) -> None:
    """Atomically replace one existing manifest from the common Git scratch directory."""
    temporary = _write_scratch_file(git_directory, curation.render_batch(batch).encode("utf-8"))
    try:
        if target.is_symlink() or not target.is_file():
            raise KbError(f"{WHO}: batch manifest is missing or unsafe: {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_archive(
    root: Path,
    git_directory: Path,
    filename: str,
    content: bytes,
    mode: int,
) -> None:
    """Atomically publish an archive without replacing an existing file."""
    directory = _fixed_directory(root, ARCHIVED, create=True)
    assert directory is not None
    target = directory / filename
    if target.exists() or target.is_symlink():
        raise KbError(f"{WHO}: archive already exists: {ARCHIVED}/{filename}")
    temporary = _write_scratch_file(git_directory, content)
    try:
        temporary.chmod(mode)
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise KbError(f"{WHO}: archive already exists: {ARCHIVED}/{filename}") from error
    finally:
        temporary.unlink(missing_ok=True)


def _write_scratch_file(git_directory: Path, content: bytes) -> Path:
    """Write and fsync temporary bytes under the common Git scratch directory."""
    scratch = git_directory / "kb-tmp"
    if scratch.is_symlink():
        raise KbError(f"{WHO}: temporary directory is a symlink: {scratch}")
    scratch.mkdir(parents=True, exist_ok=True)
    if not scratch.resolve().is_relative_to(git_directory.resolve()):
        raise KbError(f"{WHO}: temporary directory escapes the Git directory")
    temporary = scratch / f"curate-{os.urandom(8).hex()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _remove_pending(root: Path, member: curation.Member) -> None:
    """Remove only a pending file that still matches its original snapshot."""
    if not _member_file_exists(root, PENDING, member.filename):
        raise KbError(f"{WHO}: pending copy disappeared before removal")
    content = _member_file_bytes(root, PENDING, member.filename)
    if content is None or not _matches_bytes(member, content):
        raise KbError(f"{WHO}: pending copy changed before removal")
    (root / PENDING / member.filename).unlink()


def _member_file_exists(root: Path, directory: str, filename: str) -> bool:
    """Whether a direct member file exists, rejecting symlinks and special files."""
    fixed_directory = _fixed_directory(root, directory, create=False, optional=True)
    if fixed_directory is None:
        return False
    path = fixed_directory / filename
    if path.is_symlink():
        raise KbError(f"{WHO}: unsafe symlink: {directory}/{filename}")
    if not path.exists():
        return False
    if not path.is_file():
        raise KbError(f"{WHO}: unsafe non-file: {directory}/{filename}")
    return True


def _member_file_bytes(root: Path, directory: str, filename: str) -> bytes | None:
    """Read one direct member file without following links or special files."""
    fixed_directory = _fixed_directory(root, directory, create=False, optional=True)
    if fixed_directory is None:
        return None
    path = fixed_directory / filename
    if path.is_symlink():
        raise KbError(f"{WHO}: unsafe symlink: {directory}/{filename}")
    if not path.exists():
        return None
    if not path.is_file():
        raise KbError(f"{WHO}: unsafe non-file: {directory}/{filename}")
    return path.read_bytes()


def _matches_bytes(member: curation.Member, content: bytes) -> bool:
    """Whether bytes match both fields of the pending snapshot."""
    return len(content) == member.original_bytes and hashlib.sha256(content).hexdigest() == (
        member.original_sha256
    )


def _archived_line(filename: str) -> str:
    """The success line shared by initial completion and recovery."""
    return f"Archived: {PENDING}/{filename} -> {ARCHIVED}/{filename}\n"


def _render_next(
    batch: curation.Batch,
    member: curation.Member,
    content: bytes,
    text: str,
    query: str,
    sections: Sequence[str],
    question_rows: Sequence[str],
) -> str:
    """Format the full observation and bounded context in the documented order."""
    complete_count = sum(item.status == "complete" for item in batch.members)
    deferred_count = sum(item.status == "deferred" for item in batch.members)
    dropped_count = sum(item.status == "dropped" for item in batch.members)
    pending_count = sum(item.status == "pending" for item in batch.members)
    lines = [
        f"Batch: {batch.id}",
        f"Progress: {complete_count} complete, {deferred_count} deferred, "
        f"{dropped_count} dropped of {len(batch.members)}; {pending_count} pending",
        f"Pending locator: {PENDING}/{member.filename}",
        f"Input bytes: {len(content)}",
        f"SHA-256: {member.original_sha256}",
        "Observation:",
    ]
    output = "\n".join(lines) + "\n" + text
    if not text.endswith("\n"):
        output += "\n"
    output += f"\nQuery: {query}\n"
    if sections:
        output += "Matching curated sections:\n" + "".join(sections)
    elif query:
        output += f'No curated sections match "{query}".\n'
    else:
        output += "No curated sections match an empty query.\n"
    if question_rows:
        output += "Related open questions:\n"
        output += "\n".join(question_rows) + "\n"
        output += evidence.READ_WITH + "\n"
    else:
        output += "No related open questions.\n"

    complete = shlex.join(
        ["kb", "curate", "complete", batch.id, member.filename, "--disposition", "incorporated"]
    )
    duplicate = shlex.join(
        ["kb", "curate", "complete", batch.id, member.filename, "--disposition", "duplicate"]
    )
    ephemeral = shlex.join(
        ["kb", "curate", "complete", batch.id, member.filename, "--disposition", "ephemeral"]
    )
    defer = shlex.join(["kb", "curate", "defer", batch.id, member.filename])
    output += (
        "Commands:\n"
        f"  {complete} LOCATOR...\n"
        f"  {duplicate} LOCATOR...\n"
        f"  {ephemeral} --reason TEXT\n"
        f"  {defer} --reason TEXT\n"
        "Check related stale claims with kb verify only when evidence supports verification.\n"
        "Close supported gaps with kb resolve; leave unanswered questions open.\n"
    )
    return output


def _completion_words(run_id: str, member: curation.Member) -> list[str]:
    """Reconstruct the exact complete invocation represented by an archive intent."""
    if member.disposition is None:
        raise curation.StateError("archiving member has no disposition")
    words = [
        "kb",
        "curate",
        "complete",
        run_id,
        member.filename,
        "--disposition",
        member.disposition,
    ]
    if member.disposition == "ephemeral":
        words.extend(["--reason", member.reason or ""])
    else:
        words.extend(destination.locator for destination in member.destinations)
    return words


def _start_report(
    run_id: str | None,
    max_bytes: int,
    eligible_count: int,
    selection: curation.Selection,
    entries: Sequence[QueueEntry],
    open_question_count: int,
    stale_articles: Sequence[StaleArticle],
) -> str:
    """Render the bounded queue, selection, and related verification report."""
    lines = []
    if run_id is not None:
        lines.append(f"Created batch: {run_id}")
    lines.extend(
        [
            f"Selected: {len(selection.selected)} observation(s)",
            f"Selected bytes: {selection.selected_bytes}",
            f"Eligible pending observations: {eligible_count}",
            f"Input budget: {max_bytes} bytes",
            f"Open questions: {open_question_count}",
            f"Related stale articles: {len(stale_articles)}",
        ]
    )
    if selection.skipped:
        skipped_bytes = sum(item.size for item in selection.skipped)
        lines.append(f"Skipped: {len(selection.skipped)} observation(s), {skipped_bytes} bytes")
        for item in selection.skipped[:MAX_REPORT_ITEMS]:
            lines.append(f"  {item.filename} ({item.size} bytes)")
        _omitted_line(lines, len(selection.skipped), "skipped")
    if selection.larger_than_budget:
        largest = max(item.size for item in selection.larger_than_budget)
        lines.append(
            f"Larger than budget: {len(selection.larger_than_budget)} observation(s); "
            f"largest is {largest} bytes"
        )
        for item in selection.larger_than_budget[:MAX_REPORT_ITEMS]:
            filename = shlex.quote(item.filename)
            lines.append(
                "  Larger than --max-bytes; select alone: "
                f"kb curate start --max-bytes {item.size} {filename}"
            )
        _omitted_line(lines, len(selection.larger_than_budget), "larger-than-budget")

    warnings = [
        f"Metadata warning: {entry.snapshot.filename}: {warning}"
        for entry in entries
        for warning in entry.warnings
    ]
    lines.extend(warnings)
    if stale_articles:
        lines.append("Related stale knowledge:")
        lines.extend(f"  {article.path} | {article.status}" for article in stale_articles[:8])
        _omitted_line(lines, len(stale_articles), "stale article", limit=8)
    else:
        lines.append("Related stale knowledge: none")
    return "\n".join(lines) + "\n"


def _omitted_line(lines: list[str], count: int, label: str, limit: int = MAX_REPORT_ITEMS) -> None:
    """Append a deterministic omitted count after a bounded list."""
    omitted = count - limit
    if omitted > 0:
        lines.append(f"  ... {omitted} more {label}(s)")


def _pending_entries(root: Path) -> list[QueueEntry]:
    """Read ordinary, non-hidden Markdown files directly under pending."""
    directory = _fixed_directory(root, PENDING, create=False, optional=True)
    if directory is None:
        return []
    entries: list[QueueEntry] = []
    for path in sorted(directory.iterdir(), key=lambda candidate: candidate.name):
        if path.name.startswith(".") or not path.name.endswith(".md"):
            continue
        if path.is_symlink():
            raise KbError(f"{WHO}: pending observation is a symlink: {path.name}")
        if not stat.S_ISREG(path.lstat().st_mode):
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise KbError(f"{WHO}: pending observation escapes the content repository: {path.name}")
        curation.validate_filename(path.name)
        content = path.read_bytes()
        text = content.decode("utf-8")
        document = model.parse(path.name, text.removeprefix("\ufeff"))
        created = evidence.created_date(document)
        warnings = []
        if created is None:
            raw_created = document.scalar("created")
            detail = "missing" if raw_created is None else "invalid"
            warnings.append(f"created date is {detail}; observation sorts after dated items")
        if document.title is None:
            warnings.append("title is missing; related stale search is unavailable")
        entries.append(
            QueueEntry(
                curation.PendingInput(path.name, content, created),
                document.title,
                tuple(warnings),
            )
        )
    return entries


def _related_stale(
    root: Path, context: Context, selected: Sequence[QueueEntry]
) -> list[StaleArticle]:
    """Find deduplicated stale articles among the top three recall results per title."""
    found: dict[str, str] = {}
    documents: dict[str, model.Document] = {}
    for entry in selected:
        if not entry.title:
            continue
        locators = recall_command.ranked_locators(root, [entry.title])[:3]
        for locator in locators:
            path, _separator, fragment = locator.partition("#")
            document = documents.get(path)
            if document is None:
                document = corpus.read_document(root, path)
                documents[path] = document
            section = None if fragment in {"", "title", "top"} else document.section(fragment)
            status = freshness.status(document, section, context.today)
            if status.startswith("stale"):
                found.setdefault(path, status)
    return [StaleArticle(path, status) for path, status in found.items()]


def _require_clean_tree(root: Path) -> None:
    """Refuse selection when the index or worktree contains non-lock changes."""
    result = run_process(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise KbError(f"{WHO}: cannot inspect Git status" + (f": {detail}" if detail else ""))
    records = result.stdout.split(b"\0")
    dirty: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise KbError(f"{WHO}: Git returned malformed NUL-delimited status")
        status = record[:2]
        paths = [os.fsdecode(record[3:])]
        if b"R" in status or b"C" in status:
            if index >= len(records) or not records[index]:
                raise KbError(f"{WHO}: Git returned malformed rename status")
            paths.append(os.fsdecode(records[index]))
            index += 1
        dirty.extend(
            path
            for path in paths
            if path != ".observe.lock" and not path.startswith(".observe.lock/")
        )
    if dirty:
        listing = ", ".join(sorted(set(dirty)))
        raise KbError(f"{WHO}: content repository has uncommitted changes: {listing}")


def _check_existing_batches(root: Path) -> None:
    """Refuse active new batches and old pending TSV batches without changing them."""
    directory = _fixed_directory(root, BATCHES, create=False, optional=True)
    if directory is None:
        return
    for path in sorted(directory.iterdir(), key=lambda candidate: candidate.name):
        if path.suffix == ".tsv":
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise KbError(f"{WHO}: malformed old batch manifest: {path.name}")
            if _old_batch_has_pending(path):
                raise KbError(f"{WHO}: an old batch has pending work: {path.name}")
        elif path.suffix == ".json":
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise KbError(f"{WHO}: malformed batch manifest: {path.name}")
            batch = _load_batch_file(path)
            if batch.id != path.stem:
                raise KbError(f"{WHO}: batch identifier does not match filename: {path.name}")
            active = [
                member.filename
                for member in batch.members
                if member.status in {"pending", "archiving"}
            ]
            if active:
                raise KbError(f"{WHO}: another batch has pending or archiving work: {path.name}")


def _old_batch_has_pending(path: Path) -> bool:
    """Read the legacy TSV header and status cells, rejecting malformed manifests."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise KbError(f"{WHO}: malformed old batch manifest: {path.name}: {error}") from error
    expected = ["filename", "original_sha256", "status", "disposition", "destination"]
    if not lines or lines[0].split("\t") != expected:
        raise KbError(f"{WHO}: malformed old batch manifest: {path.name}")
    pending = False
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != len(expected) or fields[2] not in {"pending", "complete", "deferred"}:
            raise KbError(f"{WHO}: malformed old batch manifest: {path.name}")
        pending = pending or fields[2] == "pending"
    return pending


def _read_batch(root: Path, run_id: str) -> curation.Batch:
    """Read one safely contained manifest after validating its bare run identifier."""
    curation.validate_run_id(run_id)
    directory = _fixed_directory(root, BATCHES, create=False, optional=True)
    if directory is None:
        raise KbError(f"{WHO}: batch not found: {run_id}")
    path = directory / f"{run_id}.json"
    if path.is_symlink() or not path.is_file():
        raise KbError(f"{WHO}: batch not found: {run_id}")
    batch = _load_batch_file(path)
    if batch.id != run_id:
        raise KbError(f"{WHO}: batch identifier does not match filename: {path.name}")
    return batch


def _load_batch_file(path: Path) -> curation.Batch:
    """Load a manifest and attach its filename to validation errors."""
    try:
        return curation.load_batch(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, curation.StateError) as error:
        raise KbError(f"{WHO}: malformed batch manifest {path.name}: {error}") from error


def _matches_snapshot(
    root: Path,
    directory: str,
    member: curation.Member,
    *,
    archive: bool = False,
) -> bool:
    """Whether a safe file currently matches a pending or archived state hash."""
    return _snapshot_bytes(root, directory, member, archive=archive) is not None


def _snapshot_bytes(
    root: Path,
    directory: str,
    member: curation.Member,
    *,
    archive: bool = False,
) -> bytes | None:
    """Read a safe file only when it matches the hash and size recorded in state."""
    fixed_directory = _fixed_directory(root, directory, create=False, optional=True)
    if fixed_directory is None:
        return None
    path = fixed_directory / member.filename
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    expected_hash = member.archive_sha256 if archive else member.original_sha256
    expected_bytes = None if archive else member.original_bytes
    if hashlib.sha256(data).hexdigest() != expected_hash:
        return None
    if expected_bytes is not None and len(data) != expected_bytes:
        return None
    return data


def _fixed_directory(
    root: Path,
    relative: str,
    *,
    create: bool,
    optional: bool = False,
) -> Path | None:
    """Resolve a fixed content directory without following symlink components."""
    root_resolved = root.resolve()
    path = root
    for component in relative.split("/"):
        path = path / component
        if path.is_symlink():
            raise KbError(f"{WHO}: content directory is a symlink: {relative}")
        if not path.exists():
            if not create:
                if optional:
                    return None
                raise KbError(f"{WHO}: content directory is missing: {relative}")
            path.mkdir()
        if not path.is_dir() or not path.resolve().is_relative_to(root_resolved):
            raise KbError(f"{WHO}: unsafe content directory: {relative}")
    return path


def _publish_manifest(git_directory: Path, target: Path, text: str) -> None:
    """Publish one manifest atomically from the common Git directory's scratch area."""
    scratch = git_directory / "kb-tmp"
    if scratch.is_symlink():
        raise KbError(f"{WHO}: temporary directory is a symlink: {scratch}")
    scratch.mkdir(parents=True, exist_ok=True)
    if not scratch.resolve().is_relative_to(git_directory.resolve()):
        raise KbError(f"{WHO}: temporary directory escapes the Git directory")
    temporary = scratch / f"curate-{os.urandom(8).hex()}.json"
    try:
        with temporary.open("xb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists() or target.is_symlink():
            raise KbError(f"{WHO}: batch manifest already exists: {target.name}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)

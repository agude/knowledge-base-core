"""Local curation batch selection and progress reporting."""

import hashlib
import os
import shlex
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import run as run_process

from kb import args, corpus, curation, dates, evidence, freshness, lock, model
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
SPEC = Spec(
    usage="curate {start,status} ...",
    summary=(
        "Manage local curation batches. Start selects bounded input; status reports persisted "
        "progress without changing files or contacting Git."
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
    fixed_directory = _fixed_directory(root, directory, create=False, optional=True)
    if fixed_directory is None:
        return False
    path = fixed_directory / member.filename
    if path.is_symlink() or not path.is_file():
        return False
    try:
        data = path.read_bytes()
    except OSError:
        return False
    expected_hash = member.archive_sha256 if archive else member.original_sha256
    expected_bytes = None if archive else member.original_bytes
    return hashlib.sha256(data).hexdigest() == expected_hash and (
        expected_bytes is None or len(data) == expected_bytes
    )


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

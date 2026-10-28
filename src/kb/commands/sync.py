"""kb sync: harvest finished transcripts, commit them, and sync the content repository."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from kb import (
    __version__,
    args,
    config,
    dates,
    harvest,
    lock,
    model,
    observation,
    remote,
    secrets,
    sync_state,
)
from kb.args import Spec
from kb.config import content_root
from kb.errors import KbError
from kb.hosts import claude, codex
from kb.platform import config_file
from kb.remote import RemoteStatus as RemoteStatus
from kb.transcript_observation import (
    ContentLine,
    redact_messages,
    scan_text,
    title_after_scan,
    title_candidates,
)
from kb.transcript_observation import (
    render as render_observation,
)
from kb.transcript_observation import (
    validate as validate_observation,
)
from kb.transcripts import App, Session, parse_timestamp

PENDING = "observations/pending"
ARCHIVED = "observations/archived"
TMP = sync_state.TMP
MAX_NAME_TRIES = 5
REDACTION_PASSES = 3
SPEC = Spec(
    usage="sync [--status] [--no-push] [--dry-run]",
    summary=(
        "Harvest finished Claude Code and Codex transcripts, commit the observations, and sync "
        "the content repository with origin."
    ),
    switches=frozenset({"--status", "--no-push", "--dry-run"}),
)


@dataclass(frozen=True)
class Failure:
    """A session-level problem that makes the completed run exit nonzero."""

    session: str
    reason: str


@dataclass(frozen=True)
class ScanResult:
    """Parsed transcript candidates and files that could not be read or identified."""

    candidates: tuple[harvest.Candidate, ...]
    failures: tuple[Failure, ...]


@dataclass(frozen=True)
class Prepared:
    """A validated observation ready to write, or the reason it must be skipped."""

    text: str | None
    reason: str | None
    messages: int
    redacted_by_detector: Mapping[str, int]

    @property
    def redacted_lines(self) -> int:
        """The count of distinct content lines removed from the rendered observation."""
        return sum(self.redacted_by_detector.values())

    @property
    def byte_count(self) -> int:
        """The UTF-8 size of the observation, or zero when it was skipped."""
        return 0 if self.text is None else len(self.text.encode("utf-8"))


# The seams that the sync tests replace. The remote steps live in kb.remote.
_dirty_paths = remote.dirty_paths
_fetch_status = remote.fetch_status


def run(words: Sequence[str]) -> int:
    """Run sync, status, or dry-run and return its exit status."""
    parsed = args.parse(SPEC, words)
    if parsed.help:
        sys.stdout.write(SPEC.help_text())
        return 0
    if parsed.words:
        raise SPEC.usage_error()
    status = "--status" in parsed.switches
    no_push = "--no-push" in parsed.switches
    dry_run = "--dry-run" in parsed.switches
    if sum((status, dry_run, no_push)) > 1 and (status or dry_run):
        raise SPEC.usage_error()

    environ = os.environ
    configuration = config_file(environ, sys.platform, Path.home())
    try:
        root = content_root(environ, configuration)
        harvest_since = config.read_harvest_since(configuration)
        now = dates.now(environ)
        host = observation.short_host(socket.gethostname())
        git_directory = lock.git_dir(root)
    except KbError as error:
        raise KbError(f"sync: {error}") from None
    except (OSError, UnicodeError) as error:
        raise KbError(f"sync: {error}") from None

    if dry_run:
        return _dry_run(root, git_directory, environ, host, now, harvest_since)
    try:
        wait = lock.parse_wait(environ.get("KB_LOCK_WAIT"))
    except lock.InvalidWait:
        raise SPEC.usage_error() from None
    backend = lock.default_backend(sys.platform)
    try:
        with lock.write_lock(git_directory, root, wait, backend):
            if status:
                return _status(root, environ, host, now, harvest_since)
            return _sync(root, git_directory, environ, host, now, harvest_since, no_push)
    except lock.LockBusy as busy:
        raise KbError(
            f"sync: content repository is busy (waited {busy.waited}s for the lock)"
        ) from None
    except KbError as error:
        message = str(error)
        if message.startswith("sync:"):
            raise
        raise KbError(f"sync: {message}") from None
    except (OSError, UnicodeError) as error:
        raise KbError(f"sync: {error}") from None


def recover_and_harvest(
    root: Path,
    git_directory: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Recover this host's interrupted observations, then harvest finished transcripts.

    Prints the harvest totals and returns the warnings and the errors for the caller to
    report. The caller holds the writer lock; this function takes none.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        _recover(root, git_directory, host)
    except (OSError, UnicodeError, KbError) as error:
        errors.append(f"sync: recovery failed: {error}")

    if harvest_since is not None:
        with _scanner_workspace(git_directory, preserve=False) as scan_directory:
            candidates = _scan_transcripts(environ)
            errors.extend(_failure_text(failure) for failure in candidates.failures)
            records = _head_records(root)
            state = harvest.reconstruct_state(records, _sessions(candidates.candidates), host)
            selection = harvest.select_candidates(candidates.candidates, state, now, harvest_since)
            warnings.extend(selection.warnings)
            _write_record_counts(candidates.candidates)
            harvested, messages, byte_count, redacted, detectors = _write_selection(
                root, selection.plans, scan_directory, host, now
            )
            errors.extend(harvested.failures)
        sys.stdout.write(f"Harvested: {harvested.count} session transcript(s)\n")
        if messages or byte_count or redacted:
            sys.stdout.write(
                f"Harvest totals: {messages} messages, {byte_count} bytes, "
                f"{redacted} redacted lines\n"
            )
        if detectors:
            sys.stdout.write(f"Redacted by detector: {_format_counts(detectors)}\n")
    return tuple(warnings), tuple(errors)


def _sync(
    root: Path,
    git_directory: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
    no_push: bool,
) -> int:
    """Run recovery, optional harvest, then pull and push when the tree is clean.

    Records the outcome in the sync state file. Returns 1 when any step failed, else 0.
    """
    try:
        dirty, failures = _integrate(
            root, git_directory, environ, host, now, harvest_since, no_push
        )
    except (KbError, OSError, UnicodeError) as error:
        _record_outcome(git_directory, now, "error", _labelled(str(error)))
        raise
    if failures:
        _record_outcome(git_directory, now, "error", failures[0])
        return 1
    _record_outcome(git_directory, now, "dirty" if dirty else "ok", None)
    return 0


def _integrate(
    root: Path,
    git_directory: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
    no_push: bool,
) -> tuple[bool, list[str]]:
    """Harvest, then integrate with origin when the worktree is clean.

    Prints what sync prints. Returns whether the worktree was dirty, and every failure line.
    """
    warnings, errors = recover_and_harvest(root, git_directory, environ, host, now, harvest_since)
    for warning in warnings:
        sys.stderr.write(f"sync: warning: {warning}\n")
    for message in errors:
        sys.stderr.write(f"{message}\n")

    dirty = _dirty_paths(root)
    if dirty:
        sys.stderr.write(f"sync: uncommitted changes in {root}; not pulling or pushing\n")
        for path in dirty[:10]:
            sys.stderr.write(f"  {path}\n")
        return True, list(errors)

    status, fetch_error = _fetch_status(root)
    if fetch_error is not None:
        sys.stderr.write(f"{fetch_error}\n")
        return False, [*errors, fetch_error]
    assert status is not None
    actions, sync_errors = _sync_remote(root, status, no_push)
    for action in actions:
        sys.stdout.write(f"{action}\n")
    for message in sync_errors:
        sys.stderr.write(f"{message}\n")
    return False, [*errors, *sync_errors]


def _record_outcome(git_directory: Path, now: datetime, outcome: str, failure: str | None) -> None:
    """Replace the sync outcome record. A failed write is reported and changes no exit status.

    An ok run sets last_exchange to now. Other outcomes keep the previous exchange time. The
    caller holds the writer lock.
    """
    try:
        previous = sync_state.read(git_directory)
    except KbError:
        previous = None
    previous_exchange = None if previous is None else previous.last_exchange
    last_exchange = now if outcome == "ok" else previous_exchange
    state = sync_state.SyncState(
        kb_version=__version__,
        last_run=now,
        last_outcome=outcome,
        last_exchange=last_exchange,
        message=None if failure is None else _first_line(failure),
    )
    try:
        sync_state.write(git_directory, state)
    except (KbError, OSError, UnicodeError) as error:
        sys.stderr.write(f"sync: cannot record sync outcome: {error}\n")


def _labelled(text: str) -> str:
    """The text with the sync label that run() puts on its errors."""
    return text if text.startswith("sync:") else f"sync: {text}"


def _first_line(text: str) -> str:
    """The first line of a failure, which is the message that the outcome record keeps."""
    lines = text.splitlines()
    return lines[0] if lines else "sync failed"


@dataclass(frozen=True)
class Backlog:
    """The transcript scan and the harvest selection made from it."""

    scan: ScanResult
    selection: harvest.Selection


def backlog(
    root: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
) -> Backlog:
    """Scan transcripts and select what a harvest would take, reading HEAD only.

    Never fetches, locks, or writes. A caller that needs origin's state fetches it separately.
    """
    scanned = _scan_transcripts(environ)
    state = harvest.reconstruct_state(_head_records(root), _sessions(scanned.candidates), host)
    selection = harvest.select_candidates(scanned.candidates, state, now, harvest_since)
    return Backlog(scanned, selection)


def _status(
    root: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
) -> int:
    """Fetch remote state and report transcript backlog plus ahead and behind counts."""
    errors: list[str] = []
    ready = waiting = 0
    if harvest_since is not None:
        found = backlog(root, environ, host, now, harvest_since)
        errors.extend(_failure_text(failure) for failure in found.scan.failures)
        ready, waiting = found.selection.ready_count, found.selection.waiting_count
    fetched, fetch_error = _fetch_status(root)
    if fetch_error is not None:
        errors.append(fetch_error)
    else:
        assert fetched is not None
        sys.stdout.write(f"Ready: {ready} session(s)\n")
        sys.stdout.write(f"Waiting: {waiting} session(s)\n")
        sys.stdout.write(f"Ahead: {fetched.ahead} commit(s)\n")
        sys.stdout.write(f"Behind: {fetched.behind} commit(s)\n")
    for error in errors:
        sys.stderr.write(f"{error}\n")
    return 1 if errors else 0


def _dry_run(
    root: Path,
    git_directory: Path,
    environ: Mapping[str, str],
    host: str,
    now: datetime,
    harvest_since: datetime | None,
) -> int:
    """Show the observations that would be written without locking or changing git state."""
    if harvest_since is None:
        sys.stdout.write("Totals: 0 sessions, 0 messages, 0 bytes, 0 redacted lines\n")
        return 0
    try:
        with _scanner_workspace(git_directory, preserve=True) as scan_directory:
            scanned = _scan_transcripts(environ)
            records = _head_records(root)
            state = harvest.reconstruct_state(records, _sessions(scanned.candidates), host)
            selection = harvest.select_candidates(scanned.candidates, state, now, harvest_since)
            failures = list(scanned.failures)
            prepared: list[tuple[harvest.HarvestPlan, Prepared]] = []
            for plan in selection.plans:
                result = _prepare(plan, scan_directory, host, now)
                if result.reason is not None:
                    failures.append(Failure(plan.session.id or "unknown", result.reason))
                else:
                    prepared.append((plan, result))
            totals = _totals(prepared)
            for plan, result in prepared:
                sys.stdout.write(
                    f"{plan.session.app} {plan.session.id} part {plan.part}: "
                    f"{result.messages} messages, {result.byte_count} bytes, "
                    f"{result.redacted_lines} redacted lines\n"
                )
            _write_totals(*totals)
            _write_record_counts(scanned.candidates)
            if totals[3]:
                sys.stdout.write(f"Redacted by detector: {_format_counts(totals[4])}\n")
            for failure in failures:
                sys.stderr.write(f"{_failure_text(failure)}\n")
            for warning in selection.warnings:
                sys.stderr.write(f"sync: warning: {warning}\n")
            return 1 if failures else 0
    except (OSError, UnicodeError, KbError) as error:
        raise KbError(f"sync: dry-run failed: {error}") from None


def _scan_transcripts(environ: Mapping[str, str]) -> ScanResult:
    """Read isolated Claude and Codex transcript files once and parse their snapshots."""
    candidates: list[harvest.Candidate] = []
    failures: list[Failure] = []
    claude_root = _store_root(environ, "CLAUDE_CONFIG_DIR", ".claude") / "projects"
    for project in sorted(claude_root.glob("*")):
        if not project.is_dir():
            continue
        for path in sorted(project.glob("*.jsonl")):
            _read_candidate(path, failures, candidates, "claude-code")
        for session_directory in sorted(project.iterdir()):
            if not session_directory.is_dir():
                continue
            for path in sorted((session_directory / "subagents").glob("agent-*.jsonl")):
                _read_candidate(path, failures, candidates, "claude-code", session_directory.name)
    codex_root = _store_root(environ, "CODEX_HOME", ".codex") / "sessions"
    for path in sorted(codex_root.rglob("rollout-*.jsonl")):
        _read_candidate(path, failures, candidates, "codex")
    return ScanResult(tuple(candidates), tuple(failures))


def _read_candidate(
    path: Path,
    failures: list[Failure],
    candidates: list[harvest.Candidate],
    app: App,
    parent_session: str | None = None,
) -> None:
    """Read one transcript and add its parsed session or a redacted failure reason."""
    label = _session_label(path)
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        text = path.read_text(encoding="utf-8")
        if app == "claude-code":
            session = claude.parse(text, path.stem, parent_session)
        else:
            session = codex.parse(text, path.name)
    except UnicodeDecodeError:
        failures.append(Failure(label, "transcript is not UTF-8"))
        return
    except OSError as error:
        failures.append(Failure(label, f"cannot read transcript: {error.strerror}"))
        return
    if session.id is None:
        failures.append(Failure(label, "no filename-matching session metadata"))
        return
    candidates.append(harvest.Candidate(session, modified))


def _store_root(environ: Mapping[str, str], name: str, default: str) -> Path:
    """The configured transcript root or its host-specific home-directory default."""
    value = environ.get(name, "")
    return Path(value).expanduser() if value else Path.home() / default


def _session_label(path: Path) -> str:
    """A filename-derived identifier safe to report before a file has parsed."""
    stem = path.stem
    return stem.removeprefix("rollout-") if stem.startswith("rollout-") else stem


def _sessions(candidates: Sequence[harvest.Candidate]) -> tuple[Session, ...]:
    """The parsed sessions represented by scanned candidates."""
    return tuple(candidate.session for candidate in candidates)


def _head_records(root: Path) -> tuple[harvest.HarvestRecord, ...]:
    """Read transcript observation front matter from HEAD, never from the worktree or index."""
    tree = _git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD", "--", PENDING, ARCHIVED)
    if tree.returncode != 0:
        detail = tree.stderr.decode("utf-8", errors="replace").rstrip("\n")
        raise KbError(f"cannot list committed observations: {detail}")
    entries: list[tuple[str, str]] = []
    for entry in tree.stdout.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", 1)
        _mode, kind, object_id = metadata.decode("ascii").split()
        if kind != "blob" or not encoded_path.endswith(b".md"):
            continue
        try:
            relative = encoded_path.decode("utf-8")
        except UnicodeDecodeError:
            continue
        entries.append((object_id, relative))
    if not entries:
        return ()
    batch = _git_bytes(
        root, "cat-file", "--batch", input_text="".join(f"{oid}\n" for oid, _ in entries)
    )
    if batch.returncode != 0:
        detail = batch.stderr.decode("utf-8", errors="replace").rstrip("\n")
        raise KbError(f"cannot read committed observations: {detail}")
    records: list[harvest.HarvestRecord] = []
    cursor = 0
    for _, relative in entries:
        header_end = batch.stdout.find(b"\n", cursor)
        if header_end < 0:
            raise KbError("git cat-file returned a truncated observation batch")
        header = batch.stdout[cursor:header_end].split()
        if len(header) != 3 or header[1] != b"blob":
            raise KbError("git cat-file returned an invalid observation header")
        size = int(header[2])
        cursor = header_end + 1
        content = batch.stdout[cursor : cursor + size]
        if len(content) != size:
            raise KbError("git cat-file returned a truncated observation")
        cursor += size
        if batch.stdout[cursor : cursor + 1] != b"\n":
            raise KbError("git cat-file returned an invalid observation separator")
        cursor += 1
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        document = model.parse(relative, text)
        record = _record_from_document(document)
        if record is not None:
            records.append(record)
    return tuple(records)


def _record_from_document(document: model.Document) -> harvest.HarvestRecord | None:
    """Extract an observation state record when the relevant fields have supported shapes."""
    source = document.scalar("source")
    host = document.scalar("host")
    if source != "session-transcript" or host is None:
        return None
    app_value = document.scalar("app")
    if app_value == "claude-code":
        app: App | None = "claude-code"
    elif app_value == "codex":
        app = "codex"
    else:
        app = None
    session_id = document.scalar("session")
    part_text = document.scalar("part")
    part = int(part_text) if part_text and part_text.isascii() and part_text.isdigit() else None
    return harvest.HarvestRecord(
        source=source,
        host=host,
        app=app,
        session=session_id,
        part=part,
        first_message=document.scalar("first_message"),
        last_message=document.scalar("last_message"),
        started=parse_timestamp(document.scalar("started")),
        ended=parse_timestamp(document.scalar("ended")),
        created=parse_timestamp(document.scalar("created")),
        forked_from=document.scalar("forked_from"),
    )


def _recover(root: Path, git_directory: Path, host: str) -> None:
    """Remove this host's uncommitted transcript observations and empty kb-tmp."""
    _empty_directory(git_directory / TMP)
    pending = root / PENDING
    if not pending.is_dir():
        return
    for path in sorted(pending.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        committed = _git(root, "cat-file", "-e", f"HEAD:{relative}")
        if committed.returncode == 0:
            continue
        try:
            document = model.parse(relative, path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            continue
        if document.scalar("source") != "session-transcript" or document.scalar("host") != host:
            continue
        unstaged = _git(root, "rm", "-q", "--cached", "--ignore-unmatch", "--", relative)
        if unstaged.returncode != 0:
            raise KbError(f"cannot unstage interrupted observation {relative}")
        path.unlink(missing_ok=True)


def _empty_directory(path: Path) -> None:
    """Remove each file or directory directly inside path without following symlinks."""
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return
    if not path.is_dir():
        path.unlink()
        return
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)


@contextmanager
def _scanner_workspace(git_directory: Path, preserve: bool) -> Iterator[Path]:
    """Yield a private scanner directory under git/kb-tmp and remove it on exit."""
    scratch = git_directory / TMP
    if scratch.is_symlink():
        raise KbError(f"{scratch} must not be a symbolic link")
    original = scratch.stat() if preserve and scratch.exists() else None
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="sync-", dir=scratch) as directory:
            yield Path(directory)
    finally:
        if preserve:
            if original is None:
                scratch.rmdir()
            else:
                os.utime(scratch, ns=(original.st_atime_ns, original.st_mtime_ns))


def _write_selection(
    root: Path,
    plans: Sequence[harvest.HarvestPlan],
    scan_directory: Path,
    host: str,
    now: datetime,
) -> tuple["WriteResult", int, int, int, dict[str, int]]:
    """Prepare selected observations, commit their paths once, and report failures."""
    prepared: list[tuple[harvest.HarvestPlan, Prepared]] = []
    failures: list[str] = []
    for plan in plans:
        result = _prepare(plan, scan_directory, host, now)
        if result.reason is not None:
            failures.append(_failure_text(Failure(plan.session.id or "unknown", result.reason)))
        else:
            prepared.append((plan, result))
    paths: list[str] = []
    for plan, result in prepared:
        assert result.text is not None
        try:
            path = _publish(root, scan_directory, result.text, now)
        except (OSError, UnicodeError, KbError) as error:
            failures.append(_failure_text(Failure(plan.session.id or "unknown", str(error))))
            _remove_paths(root, paths)
            return WriteResult(0, tuple(failures)), 0, 0, 0, {}
        paths.append(path)
    if paths:
        commit_error = _commit_observations(root, paths)
        if commit_error is not None:
            failures.append(commit_error)
            return WriteResult(0, tuple(failures)), 0, 0, 0, {}
    detector_counts: dict[str, int] = {}
    for _, result in prepared:
        for detector, count in result.redacted_by_detector.items():
            detector_counts[detector] = detector_counts.get(detector, 0) + count
    return (
        WriteResult(len(paths), tuple(failures)),
        sum(result.messages for _, result in prepared),
        sum(result.byte_count for _, result in prepared),
        sum(result.redacted_lines for _, result in prepared),
        detector_counts,
    )


@dataclass(frozen=True)
class WriteResult:
    """The count committed in one harvest transaction and its skipped sessions."""

    count: int
    failures: tuple[str, ...]


def _prepare(plan: harvest.HarvestPlan, scan_directory: Path, host: str, now: datetime) -> Prepared:
    """Redact user content, validate it, and render one planned observation."""
    _, title, excerpt = title_candidates(plan.messages)
    detector_lines: dict[str, set[ContentLine | str]] = {}
    if excerpt is not None:
        title_findings = secrets.findings(scan_directory, excerpt)
        title, title_redacted = title_after_scan(plan.messages, title_findings)
        if title_redacted:
            _record_detector_lines(detector_lines, title_findings, (), "title")
    else:
        title_redacted = 0

    messages = plan.messages
    findings_remaining: list[tuple[str, int]] = []
    for _ in range(REDACTION_PASSES):
        scanned_text, locations = scan_text(messages)
        findings = secrets.findings(scan_directory, scanned_text) if scanned_text else []
        if not findings:
            findings_remaining = []
            break
        _record_detector_lines(detector_lines, findings, locations)
        messages, _ = redact_messages(messages, findings, locations)
        findings_remaining = findings
    else:
        scanned_text, locations = scan_text(messages)
        findings_remaining = secrets.findings(scan_directory, scanned_text) if scanned_text else []
        if findings_remaining:
            _record_detector_lines(detector_lines, findings_remaining, locations)

    if findings_remaining:
        detector_names = sorted({kind for kind, _ in findings_remaining})
        return Prepared(
            None,
            "possible secrets remain after three redaction passes ("
            + ", ".join(detector_names)
            + ")",
            len(messages),
            _detector_counts(detector_lines),
        )

    try:
        text = render_observation(
            plan.session, messages, plan.part, host, now, plan.forked_from, title
        )
    except (ValueError, OverflowError) as error:
        return Prepared(
            None, f"invalid observation: {error}", len(messages), _detector_counts(detector_lines)
        )
    invalid = validate_observation(
        text, plan.session, messages, plan.part, host, now, plan.forked_from, title
    )
    if invalid:
        return Prepared(
            None,
            "observation validation failed: " + ", ".join(invalid),
            len(messages),
            _detector_counts(detector_lines),
        )
    return Prepared(text, None, len(messages), _detector_counts(detector_lines))


def _record_detector_lines(
    counts: dict[str, set[ContentLine | str]],
    findings: Sequence[tuple[str, int]],
    locations: Sequence[ContentLine],
    title: str | None = None,
) -> None:
    """Count each redacted message line once by its first detector."""
    seen: set[ContentLine | str] = set()
    for detector, line_number in findings:
        if title is not None:
            location: ContentLine | str = title
        else:
            index = line_number - 1
            if not 0 <= index < len(locations):
                continue
            location = locations[index]
        if location in seen or any(location in known for known in counts.values()):
            continue
        seen.add(location)
        counts.setdefault(detector, set()).add(location)


def _detector_counts(counts: Mapping[str, set[ContentLine | str]]) -> dict[str, int]:
    """Convert detector locations to line counts."""
    return {detector: len(locations) for detector, locations in counts.items()}


def _publish(root: Path, scan_directory: Path, text: str, now: datetime) -> str:
    """Write a temporary observation, rename it into pending, and return its relative path."""
    temporary = scan_directory / observation.temporary_name(os.urandom(4).hex())
    pending = root / PENDING
    pending.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
        for _ in range(MAX_NAME_TRIES):
            name = observation.file_name(now, os.urandom(4).hex())
            destination = pending / name
            if destination.exists():
                continue
            temporary.rename(destination)
            return f"{PENDING}/{name}"
        raise KbError(f"no free file name in {PENDING}")
    finally:
        temporary.unlink(missing_ok=True)


def _commit_observations(root: Path, paths: Sequence[str]) -> str | None:
    """Stage and commit only this run's paths, deleting them if the commit fails."""
    subject = f"Observe: {len(paths)} session transcript(s)"
    staged = _git(root, "add", "--", *paths)
    if staged.returncode == 0:
        committed = _git(root, "commit", "-q", "-m", subject, "--", *paths)
        if committed.returncode == 0:
            return None
        detail = committed.stderr.rstrip("\n")
    else:
        detail = staged.stderr.rstrip("\n")
    _remove_paths(root, paths)
    return f"sync: commit failed: {detail}" if detail else "sync: commit failed"


def _remove_paths(root: Path, paths: Sequence[str]) -> None:
    """Unstage and delete only the observation paths supplied by this run."""
    _git(root, "rm", "-q", "--cached", "--ignore-unmatch", "--", *paths)
    for relative in paths:
        (root / relative).unlink(missing_ok=True)


def _totals(
    prepared: Sequence[tuple[harvest.HarvestPlan, Prepared]],
) -> tuple[int, int, int, int, dict[str, int]]:
    """Add session, message, byte, and redaction counts for rendered plans."""
    detectors: dict[str, int] = {}
    for _, result in prepared:
        for detector, count in result.redacted_by_detector.items():
            detectors[detector] = detectors.get(detector, 0) + count
    return (
        len(prepared),
        sum(result.messages for _, result in prepared),
        sum(result.byte_count for _, result in prepared),
        sum(result.redacted_lines for _, result in prepared),
        detectors,
    )


def _write_totals(
    sessions: int, messages: int, bytes_count: int, redacted: int, _: Mapping[str, int]
) -> None:
    """Print the dry-run aggregate line."""
    sys.stdout.write(
        f"Totals: {sessions} sessions, {messages} messages, {bytes_count} bytes, "
        f"{redacted} redacted lines\n"
    )


def _write_record_counts(candidates: Sequence[harvest.Candidate]) -> None:
    """Report malformed records and duplicate IDs discarded by the host parsers."""
    malformed = sum(candidate.session.malformed_lines for candidate in candidates)
    duplicates = sum(candidate.session.duplicate_ids for candidate in candidates)
    if malformed or duplicates:
        sys.stdout.write(
            f"Skipped transcript records: {malformed} malformed line(s), "
            f"{duplicates} duplicate message ID(s)\n"
        )


def _format_counts(counts: Mapping[str, int]) -> str:
    """Format detector counts without exposing any matching text."""
    return ", ".join(f"{name}: {counts[name]}" for name in sorted(counts))


def _failure_text(failure: Failure) -> str:
    """Format a skipped-session message with no transcript content."""
    return f"sync: skipped session {failure.session}: {failure.reason}"


def _sync_remote(
    root: Path, status: RemoteStatus, no_push: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Integrate with origin and return the lines kb sync prints and the errors it reports."""
    result = remote.integrate(root, status, push=not no_push)
    actions: list[str] = []
    if result.pulled:
        actions.append(f"Pulled: {result.pulled} commit(s)")
    if result.pushed:
        actions.append(f"Pushed: {result.pushed} commit(s)")
    if result.already_in_sync:
        actions.append(f"Already in sync with origin/{status.branch}.")
    return tuple(actions), result.errors


def _git(root: Path, *words: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in the content repository."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _git_bytes(root: Path, *words: str, input_text: str = "") -> subprocess.CompletedProcess[bytes]:
    """Run a git command with byte output for NUL-delimited tree and blob data."""
    return subprocess.run(
        ["git", *words],
        cwd=root,
        input=input_text.encode("utf-8"),
        capture_output=True,
        check=False,
    )

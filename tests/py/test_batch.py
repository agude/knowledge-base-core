"""batch and archive --batch: snapshot, complete, defer, recover, and budget."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result

CREATED = re.compile(r"^Created batch: (\S+)$", re.MULTILINE)


def _commit(kb: KB) -> None:
    kb.git("add", "observations/")
    kb.git("commit", "-q", "-m", "add observations")


def _pending(kb: KB) -> Path:
    return kb.layout.content / "observations" / "pending"


def _start(kb: KB, *args: str) -> tuple[Result, str]:
    result = kb.run("batch", "start", *args)
    match = CREATED.search(result.out)
    return result, match.group(1) if match else ""


def _manifest(kb: KB, batch_id: str) -> Path:
    return kb.layout.content / "observations" / "batches" / batch_id


def _rewrite_rows(manifest: Path, update: dict[int, str]) -> None:
    """Rewrite fields (0-based column -> value) of every data row."""
    lines = manifest.read_text(encoding="utf-8").splitlines()
    rows = [lines[0]]
    for line in lines[1:]:
        fields = line.split("\t")
        for column, value in update.items():
            fields[column] = value
        rows.append("\t".join(fields))
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _record(kb: KB, *results: Result) -> str:
    parts = []
    for r in results:
        args = " ".join(r.args)
        parts.append(f"$ {r.script} {args}\nexit {r.returncode}\n{r.out}{r.err}")
    return kb.norm("\n".join(parts))


def _state(kb: KB) -> str:
    parts = []
    for area in ("pending", "archived", "batches"):
        directory = kb.layout.content / "observations" / area
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            parts.append(f"## {area}/{path.name}\n{path.read_text(encoding='utf-8')}")
    return kb.norm("".join(parts))


@pytest.mark.bats("batch.bats", "batch selects only observations present at start")
@pytest.mark.audit("A-025")
def test_batch_snapshot_complete_defer(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    kb.create_observation("b.md", "B", "Body B")
    _commit(kb)
    start, batch = _start(kb)
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "ephemeral", "a.md", "--no-commit"
    )
    defer = kb.run("batch", "defer", batch, "b.md")
    kb.create_observation("c.md", "C", "Body C")
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, start, archive, defer, status))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "batch snapshots an explicit selected subset")
def test_batch_explicit_subset(kb: KB, golden: Golden) -> None:
    for name in ("a.md", "b.md", "c.md"):
        kb.create_observation(name, name[0].upper(), f"Body {name[0]}")
    _commit(kb)
    start, batch = _start(kb, "--files", "c.md", "a.md")
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, start, status))
    golden.check("manifest", kb.norm(_manifest(kb, batch).read_text(encoding="utf-8")))


@pytest.mark.bats("batch.bats", "batch rejects invalid explicit selections")
@pytest.mark.parametrize(
    "files",
    [["a.md", "missing.md"], ["a.md", "a.md"], ["../a.md"]],
    ids=["missing", "duplicate", "path"],
)
def test_batch_invalid_selection(kb: KB, golden: Golden, files: list[str]) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    start, _ = _start(kb, "--files", *files)
    golden.check("commands", _record(kb, start))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "batch detects changed input and supports deferral")
def test_batch_changed_input(kb: KB, golden: Golden) -> None:
    path = kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    start, batch = _start(kb)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\nchanged\n")
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit"
    )
    defer = kb.run("batch", "defer", batch, "a.md")
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, start, archive, defer, status))
    golden.check("state", _state(kb))


@pytest.mark.bats(
    "batch.bats", "budgeted batch rejects changed and excluded inputs without losing evidence"
)
def test_budgeted_batch_rejections(kb: KB, golden: Golden) -> None:
    a = kb.create_observation("a.md", "A", "Body A")
    kb.create_observation("z.md", "Z", "A larger excluded body that does not fit")
    _commit(kb)
    start, batch = _start(kb, "--max-bytes", str(a.stat().st_size))
    with a.open("a", encoding="utf-8") as handle:
        handle.write("\nchanged after selection\n")
    changed = a.read_bytes()
    kb.create_observation("arrived.md", "Arrived", "Body arrived")
    results = [
        kb.run("archive", "--batch", batch, "--disposition", "duplicate", name, "--no-commit")
        for name in ("a.md", "z.md", "arrived.md")
    ]
    status = kb.run("batch", "status", batch)
    assert a.read_bytes() == changed
    golden.check("commands", _record(kb, start, *results, status))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "repeating batch completion does not overwrite archive")
def test_repeat_completion(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    first = kb.run("archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit")
    archived = kb.layout.content / "observations" / "archived" / "a.md"
    original = archived.read_text(encoding="utf-8")
    second = kb.run(
        "archive", "--batch", batch, "--disposition", "ephemeral", "a.md", "--no-commit"
    )
    assert archived.read_text(encoding="utf-8") == original
    golden.check("commands", _record(kb, first, second))


@pytest.mark.bats("batch.bats", "incorporated completion records its destination and batch status")
def test_incorporated_completion(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    archive = kb.run(
        "archive",
        "--batch",
        batch,
        "--disposition",
        "incorporated",
        "--destination",
        "knowledge/topic.md#Section",
        "a.md",
        "--no-commit",
    )
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, archive, status))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "archive resumes after the observation move")
def test_archive_resumes_after_move(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    # An interrupted archive: the file moved with its disposition, but the
    # manifest row still says pending.
    kb.run("archive", "--disposition", "duplicate", "a.md", "--no-commit")
    _rewrite_rows(_manifest(kb, batch), {2: "pending", 3: "", 4: ""})
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit"
    )
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, archive, status))


@pytest.mark.bats("batch.bats", "budgeted archive recovery preserves selection sizes and arrivals")
def test_budgeted_recovery(kb: KB, golden: Golden) -> None:
    a = kb.create_observation("a.md", "A", "Body A")
    kb.create_observation("z.md", "Z", "Body Z")
    _commit(kb)
    _, batch = _start(kb, "--max-bytes", str(a.stat().st_size))
    meta = Path(str(_manifest(kb, batch)) + ".meta")
    original_meta = meta.read_bytes()
    kb.create_observation("arrived.md", "Arrived", "Body arrived")
    kb.run("archive", "--disposition", "duplicate", "a.md", "--no-commit")
    _rewrite_rows(_manifest(kb, batch), {2: "pending", 3: "", 4: ""})
    arrived = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "arrived.md", "--no-commit"
    )
    recovered = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit"
    )
    status = kb.run("batch", "status", batch)
    assert meta.read_bytes() == original_meta
    golden.check("commands", _record(kb, arrived, recovered, status))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "batch rejects the compatibility processed disposition")
def test_batch_rejects_processed(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "processed", "a.md", "--no-commit"
    )
    golden.check("commands", _record(kb, archive))
    assert (_pending(kb) / "a.md").is_file()


@pytest.mark.bats("batch.bats", "recovery rejects a non-member archive")
def test_recovery_rejects_non_member(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    kb.create_observation("outsider.md", "Outsider", "Body outsider")
    kb.run("archive", "--disposition", "duplicate", "outsider.md", "--no-commit")
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "outsider.md", "--no-commit"
    )
    golden.check("commands", _record(kb, archive))
    golden.check("manifest", kb.norm(_manifest(kb, batch).read_text(encoding="utf-8")))


@pytest.mark.bats("batch.bats", "recovery rejects an archive with the wrong original hash")
def test_recovery_rejects_wrong_hash(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    kb.run("archive", "--disposition", "duplicate", "a.md", "--no-commit")
    archived = kb.layout.content / "observations" / "archived" / "a.md"
    archived.write_text(
        re.sub(
            r"^original_sha256: .*$",
            "original_sha256: invalid",
            archived.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )
    archive = kb.run(
        "archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit"
    )
    golden.check("commands", _record(kb, archive))
    golden.check("manifest", kb.norm(_manifest(kb, batch).read_text(encoding="utf-8")))


@pytest.mark.bats(
    "batch.bats", "batch status reports dispositions, destinations, and deferred work"
)
def test_batch_status_report(kb: KB, golden: Golden) -> None:
    for name in ("a.md", "b.md", "c.md"):
        kb.create_observation(name, name[0].upper(), f"Body {name[0]}")
    _commit(kb)
    _, batch = _start(kb)
    kb.run(
        "archive",
        "--batch",
        batch,
        "--disposition",
        "incorporated",
        "--destination",
        "knowledge/topic.md#Section",
        "a.md",
        "--no-commit",
    )
    kb.run("archive", "--batch", batch, "--disposition", "duplicate", "c.md", "--no-commit")
    kb.run("batch", "defer", batch, "b.md")
    golden.check("commands", _record(kb, kb.run("batch", "status", batch)))


@pytest.mark.bats("batch.bats", "batch status rejects an invalid persisted disposition")
def test_batch_status_invalid_disposition(kb: KB, golden: Golden) -> None:
    kb.create_observation("a.md", "A", "Body A")
    _commit(kb)
    _, batch = _start(kb)
    kb.run("archive", "--batch", batch, "--disposition", "duplicate", "a.md", "--no-commit")
    _rewrite_rows(_manifest(kb, batch), {2: "complete", 3: "corrupt"})
    golden.check("commands", _record(kb, kb.run("batch", "status", batch)))


@pytest.mark.bats("batch.bats", "batch start selects deterministic files within a byte budget")
def test_batch_byte_budget(kb: KB, golden: Golden) -> None:
    a = kb.create_observation("a.md", "A", "small")
    kb.create_observation("b.md", "B", "a much larger observation body that exceeds the budget")
    _commit(kb)
    start, batch = _start(kb, "--max-bytes", str(a.stat().st_size))
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, start, status))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "batch start and status bound oversized-item reporting")
def test_batch_bounds_oversized_report(kb: KB, golden: Golden) -> None:
    for index in range(1, 26):
        kb.create_observation(f"oversized-{index}.md", f"Observation {index}", f"Body {index}")
    _commit(kb)
    cap = str((_pending(kb) / "oversized-1.md").stat().st_size)
    start, batch = _start(kb, "--max-bytes", cap)
    status = kb.run("batch", "status", batch)
    golden.check("commands", _record(kb, start, status))


@pytest.mark.bats("batch.bats", "batch start rejects an explicit over-budget selection")
@pytest.mark.bats("batch.bats", "batch start rejects an invalid byte budget")
@pytest.mark.bats("batch.bats", "batch start reports an empty automatic zero-byte selection")
@pytest.mark.parametrize(
    "args",
    [["--files", "a.md", "--max-bytes", "0"], ["--max-bytes", "nope"], ["--max-bytes", "0"]],
    ids=["explicit-over", "invalid", "automatic-zero"],
)
def test_batch_budget_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    kb.create_observation("a.md", "A", "observation")
    _commit(kb)
    start, _ = _start(kb, *args)
    golden.check("commands", _record(kb, start))
    golden.check("state", _state(kb))


@pytest.mark.bats("batch.bats", "batch ordering uses complete creation timestamps before filenames")
def test_batch_orders_by_creation_time(kb: KB, golden: Golden) -> None:
    (_pending(kb) / "a-new.md").write_text(
        '---\ntitle: "New later observation"\nsource: test\ncreated: 2026-10-03T23:00:00Z\n---\n\n'
        "This later observation is intentionally larger than the budget.\n",
        encoding="utf-8",
    )
    old = _pending(kb) / "z-old.md"
    old.write_text(
        '---\ntitle: "Old observation"\nsource: test\ncreated: 2026-10-03T01:00:00Z\n---\n\nOld.\n',
        encoding="utf-8",
    )
    _commit(kb)
    start, batch = _start(kb, "--max-bytes", str(old.stat().st_size))
    golden.check("commands", _record(kb, start))
    golden.check("manifest", kb.norm(_manifest(kb, batch).read_text(encoding="utf-8")))


@pytest.mark.bats(
    "batch.bats", "batch ordering breaks timestamp ties by filename and puts invalid dates last"
)
def test_batch_tie_break_and_invalid_dates(kb: KB, golden: Golden) -> None:
    kb.create_observation("z-equal.md", "Z equal", "Body")
    equal = kb.create_observation("a-equal.md", "A equal", "Body")
    invalid = kb.create_observation("0-invalid.md", "Invalid date", "Body")
    invalid.write_text(
        re.sub(
            r"^created: .*$",
            "created: not-a-date",
            invalid.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        ),
        encoding="utf-8",
    )
    _commit(kb)
    start, batch = _start(kb, "--max-bytes", str(equal.stat().st_size))
    golden.check("commands", _record(kb, start))
    golden.check("manifest", kb.norm(_manifest(kb, batch).read_text(encoding="utf-8")))
    _, everything = _start(kb)
    golden.check("order", kb.norm(_manifest(kb, everything).read_text(encoding="utf-8")))


@pytest.mark.bats(
    "batch.bats", "batch explicit selection distinguishes exact fit from one byte short"
)
def test_batch_exact_fit(kb: KB, golden: Golden) -> None:
    exact = kb.create_observation("exact.md", "Exact", "Body")
    kb.create_observation("short.md", "Short", "Body")
    _commit(kb)
    size = exact.stat().st_size
    fit, _ = _start(kb, "--files", "exact.md", "--max-bytes", str(size))
    short, _ = _start(kb, "--files", "short.md", "--max-bytes", str(size - 1))
    golden.check("commands", _record(kb, fit, short))


@pytest.mark.bats("batch.bats", "legacy manifests remain usable without budget metadata")
def test_legacy_manifest(kb: KB, golden: Golden) -> None:
    legacy = kb.create_observation("legacy.md", "Legacy", "Body legacy")
    budgeted = kb.create_observation("budgeted.md", "Budgeted", "Body budgeted")
    _commit(kb)
    _, legacy_id = _start(kb, "--files", "legacy.md", "--max-bytes", str(legacy.stat().st_size))
    _, budgeted_id = _start(
        kb, "--files", "budgeted.md", "--max-bytes", str(budgeted.stat().st_size)
    )
    Path(str(_manifest(kb, legacy_id)) + ".meta").unlink()
    results = [
        kb.run("batch", "status", legacy_id),
        kb.run("batch", "status", budgeted_id),
        kb.run(
            "archive",
            "--batch",
            legacy_id,
            "--disposition",
            "duplicate",
            "legacy.md",
            "--no-commit",
        ),
        kb.run(
            "archive",
            "--batch",
            budgeted_id,
            "--disposition",
            "duplicate",
            "budgeted.md",
            "--no-commit",
        ),
        kb.run("batch", "status", legacy_id),
        kb.run("batch", "status", budgeted_id),
    ]
    golden.check("commands", _record(kb, *results))


@pytest.mark.bats(
    "batch.bats", "batch excludes concurrent arrivals and rejects excluded completion"
)
def test_batch_excludes_arrivals(kb: KB, golden: Golden) -> None:
    selected = kb.create_observation("a-selected.md", "Selected", "Body")
    kb.create_observation("z-excluded.md", "Excluded", "Body")
    _commit(kb)
    _, batch = _start(kb, "--max-bytes", str(selected.stat().st_size))
    kb.create_observation("arrived.md", "Arrived later", "Body")
    results = [
        kb.run("archive", "--batch", batch, "--disposition", "duplicate", name, "--no-commit")
        for name in ("z-excluded.md", "arrived.md")
    ]
    golden.check("commands", _record(kb, *results))
    golden.check("state", _state(kb))


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["bogus"],
        ["status"],
        ["status", "missing.tsv"],
        ["status", "../x.tsv"],
        ["defer", "x.tsv"],
    ],
    ids=["none", "unknown", "status-no-id", "status-missing", "status-path", "defer-no-file"],
)
def test_batch_usage_errors(kb: KB, golden: Golden, args: list[str]) -> None:
    golden.check("commands", _record(kb, kb.run("batch", *args)))

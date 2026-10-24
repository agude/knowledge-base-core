"""batch - Create and inspect a curation batch.

Usage:
  batch start [--max-bytes N]
  batch start --files FILENAME [FILENAME ...] [--max-bytes N]
  batch status BATCH_ID
  batch defer BATCH_ID FILENAME
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from kb import batches, cli, lock, pending, platform
from kb.content import content_dir, nonnegative

MAX_BATCH_REPORT_ITEMS = 8


class Die(Exception):
    """An error reported as `Error: <message>`, exit 1."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def start(content: Path, argv: list[str]) -> int:
    explicit = False
    selected: list[str] = []
    max_bytes = None
    index = 0
    while index < len(argv):
        word = argv[index]
        if word == "--max-bytes":
            if index + 1 >= len(argv):
                cli.fail(f"Option {word} requires an argument")
            max_bytes = nonnegative("--max-bytes", argv[index + 1])
            index += 2
        elif word == "--files":
            explicit = True
            index += 1
            if index >= len(argv):
                raise Die("--files requires at least one filename")
            while index < len(argv) and argv[index] != "--max-bytes":
                name = argv[index]
                if "/" in name:
                    raise Die(f"not a pending filename: {name}")
                if not name.endswith(".md"):
                    raise Die(f"not a markdown filename: {name}")
                if name in selected:
                    raise Die(f"duplicate filename: {name}")
                selected.append(name)
                index += 1
        else:
            raise Die("usage: batch start [--max-bytes N] [--files FILENAME [FILENAME ...]]")

    pending_dir = content / "observations" / "pending"
    oversized: list[str] = []
    with lock.held(content):
        directory = batches.directory(content)
        directory.mkdir(parents=True, exist_ok=True)
        batch_id = f"{datetime.now(UTC):%Y%m%dT%H%M%S}-{os.getpid()}.tsv"
        manifest = directory / batch_id
        if explicit:
            total = 0
            for name in selected:
                path = pending_dir / name
                if not path.is_file():
                    raise Die(f"pending observation not found: {name}")
                total += path.stat().st_size
            if max_bytes is not None and total > max_bytes:
                raise Die(f"explicit selection is {total} bytes, over --max-bytes {max_bytes}")
        else:
            selection = pending.select(pending_dir, max_bytes)
            selected = [path.name for path in selection.files]
            total = selection.total
            oversized = selection.skipped
        if not selected:
            if max_bytes is not None and oversized:
                raise Die(f"no pending observations fit --max-bytes {max_bytes}")
            raise Die("no pending observations")
        rows = [batches.HEADER] + [
            f"{name}\t{_sha(pending_dir / name)}\tpending\t\t" for name in selected
        ]
        platform.write_text(manifest, "\n".join(rows) + "\n")
        if max_bytes is not None:
            meta = [f"max_bytes={max_bytes}", f"selected_bytes={total}"]
            if oversized:
                meta.append(f"oversized_count={len(oversized)}")
                meta += [f"oversized_item={item}" for item in oversized]
            platform.write_text(manifest.with_name(manifest.name + ".meta"), "\n".join(meta) + "\n")
        out = [f"Created batch: {batch_id}", f"Selected: {len(selected)} observation(s)"]
        out.append(f"Selected bytes: {total}")
        out += [
            f"  Size: {name} {(pending_dir / name).stat().st_size} bytes"
            for name in selected[:MAX_BATCH_REPORT_ITEMS]
        ]
        if max_bytes is not None:
            out.append(f"Input budget: {max_bytes} bytes")
        shown = oversized[:MAX_BATCH_REPORT_ITEMS]
        out += [f"Skipped oversized: {item}" for item in shown]
        if len(oversized) > len(shown):
            out.append(f"... {len(oversized) - len(shown)} more oversized item(s)")
        print("\n".join(out))
    return 0


def status(content: Path, manifest: Path) -> int:
    pending_dir = content / "observations" / "pending"
    archived_dir = content / "observations" / "archived"
    counts = {"pending": 0, "complete": 0, "deferred": 0, "invalid": 0}
    dispositions = {"incorporated": 0, "duplicate": 0, "ephemeral": 0}
    unrecognized = 0
    destinations: dict[str, int] = {}
    deferred_names: list[str] = []
    sizes: list[tuple[str, int]] = []
    total = 0
    with lock.held(content):
        if not manifest.is_file():
            raise Die(f"batch not found: {manifest.name}")
        for row in batches.rows(manifest):
            path = pending_dir / row.name
            archived = archived_dir / row.name
            existing = path if path.is_file() else archived if archived.is_file() else None
            if existing is not None:
                size = existing.stat().st_size
                total += size
                if len(sizes) < MAX_BATCH_REPORT_ITEMS:
                    sizes.append((row.name, size))
            if row.status == "pending" and path.is_file():
                if _sha(path) != row.sha:
                    print(f"CHANGED: observations/pending/{row.name}")
                    counts["invalid"] += 1
                else:
                    counts["pending"] += 1
            elif row.status == "complete" and not archived.is_file():
                print(f"MISSING ARCHIVE: observations/archived/{row.name}")
                counts["invalid"] += 1
            elif row.status == "deferred" and not path.is_file():
                print(f"MISSING DEFERRED INPUT: observations/pending/{row.name}")
                counts["invalid"] += 1
            elif row.status == "complete":
                counts["complete"] += 1
                if row.disposition in dispositions:
                    dispositions[row.disposition] += 1
                    if row.disposition == "incorporated" and row.destination:
                        destinations[row.destination] = destinations.get(row.destination, 0) + 1
                else:
                    unrecognized += 1
                    counts["invalid"] += 1
            elif row.status == "deferred":
                counts["deferred"] += 1
                if len(deferred_names) < MAX_BATCH_REPORT_ITEMS:
                    deferred_names.append(row.name)
            else:
                print(f"INVALID STATUS: {row.name} ({row.status})")
                counts["invalid"] += 1
    out = [
        f"Batch {manifest.name}: {counts['complete']} complete, {counts['pending']} pending, "
        f"{counts['deferred']} deferred",
        f"  Input bytes: {total}",
    ]
    if sizes:
        out.append("  Item sizes:")
        out += [f"    {name}: {size} bytes" for name, size in sizes]
    meta = manifest.with_name(manifest.name + ".meta")
    if meta.is_file():
        shown = reported = 0
        for line in platform.read_text(meta).split("\n"):
            key, _, value = line.partition("=")
            if key == "max_bytes" and value:
                out.append(f"  Input budget: {value} bytes")
            elif key == "selected_bytes":
                out.append(f"  Selected bytes at creation: {value}")
            elif key == "oversized_count":
                reported = int(value) if value.isdigit() else 0
                out.append(f"  Oversized/deferred at creation: {value} item(s)")
            elif key == "oversized_item" and shown < MAX_BATCH_REPORT_ITEMS:
                out.append(f"  Skipped oversized: {value}")
                shown += 1
        if reported > shown:
            out.append(f"  ... {reported - shown} more oversized item(s)")
    out.append(
        f"  Dispositions: incorporated={dispositions['incorporated']}, "
        f"duplicate={dispositions['duplicate']}, ephemeral={dispositions['ephemeral']}"
    )
    if unrecognized:
        out.append(f"  Dispositions not recognized: {unrecognized}")
    if not destinations:
        out.append("  Destinations: none")
    else:
        out.append("  Destinations:")
        names = list(destinations)
        out += [
            f"    {name} ({destinations[name]} item(s))" for name in names[:MAX_BATCH_REPORT_ITEMS]
        ]
        if len(names) > MAX_BATCH_REPORT_ITEMS:
            out.append(f"    ... {len(names) - MAX_BATCH_REPORT_ITEMS} more destination(s)")
    if not counts["deferred"]:
        out.append("  Deferred work: none")
    else:
        out.append(f"  Deferred work: {counts['deferred']} item(s)")
        out += [f"    - {name}" for name in deferred_names]
        if counts["deferred"] > len(deferred_names):
            out.append(f"    ... {counts['deferred'] - len(deferred_names)} more deferred item(s)")
    print("\n".join(out))
    if counts["invalid"]:
        print(f"Batch requires attention: {counts['invalid']} invalid item(s).", file=sys.stderr)
        return 1
    return 0


def defer(content: Path, manifest: Path, name: str) -> int:
    if "/" in name:
        raise Die(f"not a pending filename: {name}")
    path = content / "observations" / "pending" / name
    with lock.held(content):
        row = batches.member(manifest, name) if manifest.is_file() else None
        if row is None:
            raise Die(f"item is not a member of batch: {name}")
        if row.status != "pending":
            raise Die(f"item is already completed or deferred: {name}")
        if not path.is_file():
            raise Die(f"pending input is missing: {name}")
        if _sha(path) != row.sha:
            raise Die(f"input changed since batch selection: observations/pending/{name}")
        batches.defer(manifest, name)
    print(f"Deferred: {name}")
    return 0


def _manifest(content: Path, batch_id: str) -> Path:
    if not batches.valid_id(batch_id):
        raise Die(f"invalid batch id: {batch_id}")
    return batches.directory(content) / batch_id


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    content = content_dir()
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    try:
        if command == "start":
            return start(content, rest)
        if command == "status":
            if len(rest) != 1:
                raise Die("usage: batch status BATCH_ID")
            return status(content, _manifest(content, rest[0]))
        if command == "defer":
            if len(rest) != 2:
                raise Die("usage: batch defer BATCH_ID FILENAME")
            return defer(content, _manifest(content, rest[0]), rest[1])
        if command in ("-h", "--help"):
            cli.print_help(__doc__)
            return 0
        raise Die("usage: batch {start|status BATCH_ID|defer BATCH_ID FILENAME}")
    except Die as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except lock.LockTimeout as error:
        return lock.report_timeout(error)

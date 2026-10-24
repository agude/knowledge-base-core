"""archive - Move a pending observation to the archive.

Adds its curation metadata to the front matter, then moves the file;
git records the move as a rename when the files are similar enough.

Usage:
  archive FILENAME [FILENAME ...]
  archive [--batch BATCH_ID --disposition TYPE [--destination PATH]] FILENAME
  archive --all

Options:
  --all         Archive all pending observations
  --no-commit   Skip the auto-commit
  --batch       Complete one persisted batch member
  --disposition processed|incorporated|duplicate|ephemeral
                Record the curation result; incorporated requires a destination
  --destination Article path and optional #Heading for incorporated evidence

Examples:
  archive 20260412T000000-0a1b2c3d.md
  archive 20260412T000000-0a1b2c3d.md 20260412T000000-4e5f6a7b.md
  archive --all

`--all` is a manual bulk-maintenance operation. Curation batches must use
explicit filenames and the persisted batch manifest.

Batch completion:
  archive --batch BATCH_ID --disposition incorporated --destination knowledge/x.md#Heading FILENAME
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from kb import batches, cli, frontmatter, git, lock, platform
from kb.content import content_dir

DISPOSITIONS = ("processed", "incorporated", "duplicate", "ephemeral")


def with_metadata(text: str, fields: list[str]) -> str:
    """text with fields added at the end of its front matter.

    A file without front matter gains a block holding only these fields
    (audit A-012). Lines keep their bytes; the result ends with a newline.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    block = [f"{f}\n" for f in fields]
    if lines and lines[0] == "---" and "---" in lines[1:]:
        close = lines.index("---", 1)
        before = "".join(f"{line}\n" for line in lines[:close])
        after = "".join(f"{line}\n" for line in lines[close:])
        return before + "".join(block) + after
    return "---\n" + "".join(block) + "---\n\n" + "".join(f"{line}\n" for line in lines)


def _pending_names(pending: Path) -> list[str]:
    return [
        p.name for p in sorted(pending.rglob("*.md"), key=lambda p: p.as_posix()) if p.is_file()
    ]


def _recover(dst: Path, member: batches.Member, disposition: str, destination: str) -> bool:
    """Whether an existing archive matches this completion exactly."""
    text = platform.read_text(dst)
    return (
        frontmatter.field(text, "original_sha256") == member.sha
        and frontmatter.field(text, "disposition") == disposition
        and (disposition != "incorporated" or frontmatter.field(text, "destination") == destination)
    )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    args = cli.parse(
        argv,
        __doc__,
        values={"--batch": "batch", "--disposition": "disposition", "--destination": "destination"},
        flags={"--all": "all", "--no-commit": "no-commit"},
        positional=True,
    )
    content = content_dir()
    pending = content / "observations" / "pending"
    archived_dir = content / "observations" / "archived"
    names = list(args.positional)
    if "all" in args.flags:
        names += _pending_names(pending)
    batch = args.get("batch")
    disposition = args.get("disposition", "processed")
    destination = args.get("destination")
    if not names:
        print("No files to archive.", file=sys.stderr)
        return 0
    if batch and ("all" in args.flags or len(names) != 1):
        cli.fail("Batch completion requires exactly one explicit filename.")
    if disposition == "incorporated" and not destination:
        cli.fail("Incorporated items require --destination.")
    if disposition != "incorporated" and destination:
        cli.fail("--destination is valid only for incorporated items.")
    if disposition not in DISPOSITIONS:
        cli.fail(f"Unknown disposition: {disposition}")
    manifest = None
    if batch:
        if not batches.valid_id(batch):
            cli.fail(f"Invalid batch id: {batch}")
        manifest = batches.directory(content) / batch
        if not manifest.is_file():
            cli.fail(f"Batch not found: {batch}")
        if disposition == "processed":
            cli.fail(
                "Batch completion requires --disposition incorporated, duplicate, or ephemeral."
            )

    archived = recovered = 0
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            for name in names:
                outcome = _archive_one(
                    name, pending, archived_dir, manifest, disposition, destination
                )
                archived += outcome == "archived"
                recovered += outcome == "recovered"
            if manifest is not None and archived == 1:
                batches.complete(manifest, names[0], disposition, destination)
    except lock.LockTimeout as error:
        return lock.report_timeout(error)
    if archived == 0:
        if recovered:
            return 0
        print("Nothing archived.", file=sys.stderr)
        return 1
    if "no-commit" in args.flags:
        return 0
    try:
        with lock.held(content):
            git.break_stale_index_lock(content)
            return git.commit_paths(
                content, f"Archive: {archived} observation(s)", ["observations/"]
            )
    except lock.LockTimeout as error:
        return lock.report_timeout(error)


def _archive_one(
    name: str,
    pending: Path,
    archived_dir: Path,
    manifest: Path | None,
    disposition: str,
    destination: str,
) -> str:
    """Archive one observation; return archived, recovered, or skipped."""
    # A bare filename, never a path: these commands are auto-approved, so a
    # path could move a file from outside the knowledge base.
    if "/" in name:
        print(f"Not a pending filename: {name}", file=sys.stderr)
        return "skipped"
    src = pending / name
    dst = archived_dir / name
    member = None
    if manifest is not None:
        member = batches.member(manifest, name)
        if member is None:
            print(f"Not a member of batch: {name}", file=sys.stderr)
            return "skipped"
        if member.status != "pending":
            print(f"Already completed or deferred: {name}", file=sys.stderr)
            return "skipped"
    if not src.is_file():
        if member is not None and dst.is_file():
            if _recover(dst, member, disposition, destination):
                batches.complete(manifest, name, disposition, destination)
                print(f"Recovered completed archive: observations/archived/{name}")
                return "recovered"
            print(
                "Archive cannot be recovered: membership, pending state, disposition, "
                "destination, or original hash does not match.",
                file=sys.stderr,
            )
            return "skipped"
        print(f"Not found: observations/pending/{name}", file=sys.stderr)
        return "skipped"
    if dst.exists() or dst.is_symlink():
        print(f"Archive already exists: observations/archived/{name}", file=sys.stderr)
        return "skipped"
    actual = hashlib.sha256(src.read_bytes()).hexdigest()
    if member is not None and actual != member.sha:
        print(f"Input changed since batch selection: observations/pending/{name}", file=sys.stderr)
        return "skipped"
    fields = [f"disposition: {disposition}"]
    if destination:
        fields.append(f"destination: {destination}")
    fields.append(f"original_sha256: {actual}")
    platform.write_text(src, with_metadata(platform.read_text(src), fields))
    src.replace(dst)
    print(f"Archived: observations/pending/{name}")
    return "archived"

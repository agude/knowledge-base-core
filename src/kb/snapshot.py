"""Read publication files from the worktree or the effective Git index."""

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from kb import corpus, git_paths
from kb.errors import KbError


class Content(Protocol):
    """The file operations needed by publication validation."""

    def markdown_files(self) -> list[str]: ...
    def resolve(self, path: str) -> str: ...
    def is_file(self, path: str) -> bool: ...
    def read_bytes(self, path: str) -> bytes: ...


@dataclass(frozen=True)
class Worktree:
    """The pre-staging content used by curation finish."""

    root: Path

    def markdown_files(self) -> list[str]:
        return corpus.markdown_files(self.root, "knowledge")

    def resolve(self, path: str) -> str:
        return (self.root / path).resolve().relative_to(self.root).as_posix()

    def is_file(self, path: str) -> bool:
        return (self.root / self.resolve(path)).is_file()

    def read_bytes(self, path: str) -> bytes:
        return (self.root / self.resolve(path)).read_bytes()


@dataclass(frozen=True)
class GitFiles:
    """Blob bytes and link modes from one Git snapshot, independent of the worktree."""

    root: Path
    files: Mapping[str, tuple[str, bytes]]

    def markdown_files(self) -> list[str]:
        return sorted(
            path
            for path in self.files
            if path.startswith("knowledge/")
            and path.endswith(".md")
            and not any(part.startswith(".") for part in PurePosixPath(path).parts)
        )

    def resolve(self, path: str) -> str:
        pending = list(PurePosixPath(path).parts)
        resolved: list[str] = []
        followed = 0
        while pending:
            part = pending.pop(0)
            if part == "..":
                if not resolved:
                    raise ValueError("path resolves outside the content repository")
                resolved.pop()
                continue
            if part in ("", "."):
                continue
            if part == "/":
                raise ValueError("path resolves outside the content repository")
            resolved.append(part)
            entry = self.files.get("/".join(resolved))
            if entry is None or entry[0] != "120000":
                continue
            followed += 1
            if followed > 40:
                raise ValueError("article symlink cycle")
            target = Path(entry[1].decode("utf-8")).as_posix()
            resolved.pop()
            if Path(target).is_absolute():
                try:
                    target = Path(target).relative_to(self.root).as_posix()
                except ValueError:
                    raise ValueError("path resolves outside the content repository") from None
                resolved = []
            pending = list(PurePosixPath(target).parts) + pending
        return "/".join(resolved)

    def is_file(self, path: str) -> bool:
        return self.resolve(path) in self.files

    def read_bytes(self, path: str) -> bytes:
        resolved = self.resolve(path)
        if resolved not in self.files:
            raise FileNotFoundError(path)
        return self.files[resolved][1]


def read_index(root: Path) -> GitFiles:
    """Read indexed blobs without checkout filters, honoring Git's GIT_INDEX_FILE."""
    prefix = git_paths.repository_prefix(root, "hook")
    listing = subprocess.run(
        ["git", "ls-files", "--stage", "--full-name", "-z", "--", "."],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listing.returncode:
        raise KbError("hook: cannot read the effective index")
    entries: list[tuple[str, str, bytes]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        raw_mode, object_id, stage = metadata.split()
        if stage != b"0":
            raise KbError("hook: cannot validate an unmerged index")
        if raw_mode == b"160000":
            continue
        path = git_paths.to_content_path(name.decode("utf-8"), prefix)
        entries.append((path, raw_mode.decode("ascii"), object_id))
    return _read_blobs(root, entries, "hook")


def read_head(root: Path, command: str) -> GitFiles:
    """Read the committed baseline; an unborn branch has an empty snapshot."""
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=root, capture_output=True, check=False
    )
    if head.returncode:
        branch = subprocess.run(
            ["git", "symbolic-ref", "-q", "HEAD"], cwd=root, capture_output=True, check=False
        )
        if branch.returncode == 0:
            reference = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", branch.stdout.decode().strip()],
                cwd=root,
                capture_output=True,
                check=False,
            )
            if reference.returncode == 1:
                return GitFiles(root, {})
        raise KbError(f"{command}: cannot read publication baseline HEAD")
    prefix = git_paths.repository_prefix(root, command)
    listing = subprocess.run(
        [
            "git",
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            head.stdout.decode().strip(),
            "--",
            prefix or ".",
        ],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listing.returncode:
        detail = listing.stderr.decode("utf-8", errors="replace").rstrip("\n")
        raise KbError(f"{command}: cannot read publication baseline: {detail}")
    entries: list[tuple[str, str, bytes]] = []
    for record in listing.stdout.split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if kind == b"blob":
            path = git_paths.to_content_path(name.decode("utf-8"), prefix)
            entries.append((path, mode.decode("ascii"), object_id))
    return _read_blobs(root, entries, command)


def _read_blobs(root: Path, entries: list[tuple[str, str, bytes]], command: str) -> GitFiles:
    """Read exact blob bytes shared by index and committed-tree snapshots."""
    result = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=b"".join(object_id + b"\n" for _, _, object_id in entries),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise KbError(f"{command}: cannot read snapshot blobs")
    files: dict[str, tuple[str, bytes]] = {}
    offset = 0
    for path, mode, object_id in entries:
        end = result.stdout.find(b"\n", offset)
        fields = result.stdout[offset:end].split()
        if len(fields) != 3 or fields[0] != object_id or fields[1] != b"blob":
            raise KbError(f"{command}: cannot read snapshot blob for {path}")
        size = int(fields[2])
        offset = end + 1
        files[path] = mode, result.stdout[offset : offset + size]
        offset += size + 1
    return GitFiles(root, files)

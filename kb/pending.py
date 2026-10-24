"""The pending queue: which observations a batch or preview selects."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kb import dates, frontmatter, platform


@dataclass
class Selection:
    files: list[Path] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)  # "name:bytes", in selection order
    skipped: list[str] = field(default_factory=list)  # "name:bytes"
    total: int = 0


def top_level(directory: Path) -> list[Path]:
    """Top-level *.md files; batches never select nested ones (audit A-022)."""
    if not directory.is_dir():
        return []
    return [p for p in directory.glob("*.md") if p.is_file()]


def select(directory: Path, max_bytes: int | None = None) -> Selection:
    """Oldest first by `created`, undated last, then by path; within max_bytes.

    An item that does not fit the remaining budget is skipped, and later,
    smaller items may still be selected.
    """

    def order(path: Path) -> tuple[int, int, bytes]:
        created = frontmatter.field(platform.read_text(path), "created") or ""
        epoch = dates.timestamp_epoch(created)
        return (0, epoch, bytes(path)) if epoch is not None else (1, 0, bytes(path))

    selection = Selection()
    for path in sorted(top_level(directory), key=order):
        size = path.stat().st_size
        entry = f"{path.name}:{size}"
        if max_bytes is None or selection.total + size <= max_bytes:
            selection.files.append(path)
            selection.sizes.append(entry)
            selection.total += size
        else:
            selection.skipped.append(entry)
    return selection

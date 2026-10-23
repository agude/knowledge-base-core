"""Golden files: pinned exact output, reviewed as files.

A run without --update-golden never writes a golden file. A missing golden
file is a failure, not an implicit creation.
"""

from __future__ import annotations

import difflib
from pathlib import Path

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "golden"


class Golden:
    def __init__(self, directory: Path, *, update: bool) -> None:
        self.directory = directory
        self.update = update
        self.used: list[Path] = []

    def check(self, name: str, actual: str) -> None:
        path = self.directory / f"{name}.txt"
        if path in self.used:
            raise AssertionError(f"golden file {name!r} checked twice in one test")
        self.used.append(path)
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="")
            return
        if not path.exists():
            raise AssertionError(
                f"missing golden file {_display(path)}; run with --update-golden and review it"
            )
        expected = path.read_text(encoding="utf-8", newline="")
        if actual != expected:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile=_display(path),
                    tofile="actual",
                )
            )
            raise AssertionError(f"output differs from golden file:\n{diff}")


def _display(path: Path) -> str:
    if path.is_relative_to(GOLDEN_ROOT.parent):
        return path.relative_to(GOLDEN_ROOT.parent).as_posix()
    return str(path)


def directory_for(module: str, test: str) -> Path:
    """Return golden/<module>/<test> for a test node."""
    safe = test.replace("[", "-").replace("]", "").replace("/", "_")
    return GOLDEN_ROOT / module / safe

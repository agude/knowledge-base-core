"""Golden files: pinned exact output, reviewed as files.

Two tiers:

- contract(): byte-exact formats that other processes and checkouts read
  (files written to the content repo, session buffers, lock files, hook
  JSON). A mismatch always fails.
- check(): a reference snapshot of the Bash implementation's output. In
  strict mode a mismatch fails; in reference mode it is recorded in the
  reference report and the test continues. Reference mode is the default
  for KB_IMPL=python, so the port is gated on contract goldens and
  semantic assertions, not on reproducing Bash's presentation.

A run without --update-golden never writes a golden file. A missing golden
file is a failure, not an implicit creation.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN_ROOT = Path(__file__).resolve().parents[1] / "golden"

MODES = ("strict", "reference")


@dataclass
class ReferenceReport:
    """Reference-golden mismatches collected in reference mode."""

    entries: list[tuple[str, str]] = field(default_factory=list)

    def add(self, nodeid: str, diff: str) -> None:
        self.entries.append((nodeid, diff))

    def render(self) -> str:
        parts = [f"## {nodeid}\n\n```diff\n{diff}```\n" for nodeid, diff in self.entries]
        return f"# Reference differences ({len(self.entries)})\n\n" + "\n".join(parts)


class Golden:
    def __init__(
        self,
        directory: Path,
        *,
        update: bool,
        mode: str = "strict",
        report: ReferenceReport | None = None,
        nodeid: str = "",
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"golden mode must be one of {MODES}; got {mode!r}")
        self.directory = directory
        self.update = update
        self.mode = mode
        self.report = report if report is not None else ReferenceReport()
        self.nodeid = nodeid
        self.used: list[Path] = []

    def check(self, name: str, actual: str) -> None:
        """Compare with a reference snapshot of the Bash implementation."""
        diff = self._compare(name, actual)
        if diff is None:
            return
        if self.mode == "reference":
            self.report.add(f"{self.nodeid} [{name}]", diff)
            return
        raise AssertionError(f"output differs from golden file:\n{diff}")

    def contract(self, name: str, actual: str) -> None:
        """Compare with a byte-exact contract format; always strict."""
        diff = self._compare(name, actual)
        if diff is not None:
            raise AssertionError(f"output differs from contract golden file:\n{diff}")

    def _compare(self, name: str, actual: str) -> str | None:
        path = self.directory / f"{name}.txt"
        if path in self.used:
            raise AssertionError(f"golden file {name!r} checked twice in one test")
        self.used.append(path)
        if self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(actual, encoding="utf-8", newline="")
            return None
        if not path.exists():
            raise AssertionError(
                f"missing golden file {_display(path)}; run with --update-golden and review it"
            )
        expected = path.read_text(encoding="utf-8", newline="")
        if actual == expected:
            return None
        return "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile=_display(path),
                tofile="actual",
            )
        )


def _display(path: Path) -> str:
    if path.is_relative_to(GOLDEN_ROOT.parent):
        return path.relative_to(GOLDEN_ROOT.parent).as_posix()
    return str(path)


def directory_for(module: str, test: str) -> Path:
    """Return golden/<module>/<test> for a test node."""
    safe = test.replace("[", "-").replace("]", "").replace("/", "_")
    return GOLDEN_ROOT / module / safe

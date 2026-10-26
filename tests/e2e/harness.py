"""Runs kb as a process against a copy of the content fixture.

Tests in this package import nothing from kb. They check stdout, stderr, and
the exit status.
"""

import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

FIXTURE_CONTENT = Path(__file__).resolve().parents[1] / "fixtures" / "content"
TODAY = "2026-10-26"


@dataclass(frozen=True)
class Kb:
    """One test's kb: a home directory, a content repository, and a fixed clock."""

    home: Path
    content: Path

    def environment(self, overrides: Mapping[str, str | None]) -> dict[str, str]:
        """The process environment; a None override removes the variable."""
        env = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "xdg"),
            "KB_CONTENT": str(self.content),
            "KB_TODAY": TODAY,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
        }
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        return env

    def __call__(
        self, *args: str, env: Mapping[str, str | None] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run `kb ARGS` and capture its output."""
        return subprocess.run(
            [sys.executable, "-m", "kb", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            cwd=self.home,
            env=self.environment(env or {}),
            timeout=60,
        )


def make_kb(root: Path) -> Kb:
    """A kb whose home and content repository live under root."""
    home = root / "home"
    (home / "xdg").mkdir(parents=True)
    content = root / "content"
    shutil.copytree(FIXTURE_CONTENT, content)
    return Kb(home=home, content=content)

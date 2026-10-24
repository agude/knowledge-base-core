"""Build subprocess environments from scratch.

Nothing is inherited from the caller's environment. PATH is a per-test bin
directory of selected tools, followed by /usr/bin:/bin, so `#!/usr/bin/env`
shebangs resolve to the selected interpreters and never to `.venv/bin`.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SYSTEM_PATH = "/usr/bin:/bin"

# The fixed clock: freshness is computed against this instant.
TODAY = datetime(2026, 10, 23, tzinfo=UTC)
TODAY_EPOCH = int(TODAY.timestamp())

# Git commit metadata, fixed so commit metadata does not depend on the clock.
GIT_DATE = "2026-10-01T00:00:00Z"
GIT_NAME = "Test"
GIT_EMAIL = "test@test.com"

MIN_BASH = (4, 0)
MIN_PYTHON = (3, 11)


class HarnessError(RuntimeError):
    """The host cannot run the suite as configured."""


@dataclass(frozen=True)
class Tools:
    bash: Path
    python: Path
    git: Path
    jq: Path | None


def _bash_version(path: Path) -> tuple[int, int] | None:
    result = subprocess.run(
        [str(path), "-c", 'printf "%s %s" "${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"'],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": SYSTEM_PATH},
    )
    if result.returncode != 0:
        return None
    major, minor = result.stdout.split()
    return int(major), int(minor)


def _find_bash() -> Path:
    configured = os.environ.get("KB_BASH")
    if configured:
        path = Path(configured)
        version = _bash_version(path)
        if version is None or version < MIN_BASH:
            raise HarnessError(f"KB_BASH={configured} is not bash 4 or newer")
        return path
    for directory in os.environ.get("PATH", SYSTEM_PATH).split(os.pathsep):
        path = Path(directory) / "bash"
        if path.is_file() and os.access(path, os.X_OK):
            version = _bash_version(path)
            if version is not None and version >= MIN_BASH:
                return path
    raise HarnessError("no bash 4 or newer on PATH; set KB_BASH")


def _check_python(path: Path) -> None:
    probe = (
        "import sys\n"
        f"assert sys.version_info >= {MIN_PYTHON!r}, sys.version\n"
        "try:\n"
        "    import pytest\n"
        "except ImportError:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit('pytest is importable: not a standard-library-only interpreter')\n"
    )
    result = subprocess.run(
        [str(path), "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": SYSTEM_PATH},
    )
    if result.returncode != 0:
        raise HarnessError(
            f"interpreter {path} is unusable: {result.stderr.strip() or result.stdout.strip()}"
        )


def _find_python() -> Path:
    configured = os.environ.get("KB_PYTHON")
    # sys._base_executable is the interpreter behind the venv, not the venv's
    # own python, which can import pytest.
    path = Path(configured) if configured else Path(sys._base_executable)
    _check_python(path)
    return path


def _which(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


@functools.cache
def tools() -> Tools:
    """Locate and verify the tools once per session."""
    git = _which("git")
    if git is None:
        raise HarnessError("git is not on PATH")
    return Tools(bash=_find_bash(), python=_find_python(), git=git, jq=_which("jq"))


@functools.cache
def utf8_locale() -> str:
    """Return KB_LOCALE if set, else C.UTF-8 where available, else en_US.UTF-8."""
    configured = os.environ.get("KB_LOCALE")
    if configured:
        return configured
    result = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False)
    names = {line.strip().lower() for line in result.stdout.splitlines()}
    if names & {"c.utf-8", "c.utf8"}:
        return "C.UTF-8"
    return "en_US.UTF-8"


@functools.cache
def python_minor() -> int:
    """The selected interpreter's minor version (3.x)."""
    result = subprocess.run(
        [str(tools().python), "-I", "-c", "import sys; print(sys.version_info[1])"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(result.stdout)


@functools.cache
def system_pythons() -> frozenset[str]:
    """Python executables in the system directories, hidden from every test.

    The Python executables' preamble searches PATH for python3.20 down to
    python3.11 before python3, so a system interpreter would win over the
    selected one.
    """
    return frozenset(
        entry.name
        for directory in SYSTEM_PATH.split(":")
        if Path(directory).is_dir()
        for entry in Path(directory).iterdir()
        if entry.name.startswith("python")
    )


def build_bin(bin_dir: Path, syslog: Path, *, jq: bool = True) -> None:
    """Populate bin_dir with the selected tools and a logger stub."""
    selected = tools()
    bin_dir.mkdir(parents=True, exist_ok=True)
    links = {
        "bash": selected.bash,
        "python3": selected.python,
        f"python3.{python_minor()}": selected.python,
        "git": selected.git,
    }
    if jq:
        if selected.jq is None:
            raise HarnessError("jq is not on PATH")
        links["jq"] = selected.jq
    for name, target in links.items():
        (bin_dir / name).symlink_to(target)
    # logger records its arguments instead of writing to the host's syslog.
    logger = bin_dir / "logger"
    logger.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{syslog}'\n",
        encoding="utf-8",
    )
    logger.chmod(0o755)


def system_bin_without(dest: Path, excluded: frozenset[str]) -> Path:
    """Mirror the system directories into dest, leaving out excluded names.

    A tool in /usr/bin cannot be hidden by an earlier PATH entry, so a
    configuration without it uses this mirror in place of SYSTEM_PATH.
    """
    if dest.exists():
        return dest
    dest.mkdir(parents=True)
    for directory in SYSTEM_PATH.split(":"):
        for entry in Path(directory).iterdir():
            if entry.name in excluded:
                continue
            link = dest / entry.name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(entry)
    return dest


@dataclass(frozen=True)
class Layout:
    """Per-test directories. Every path lives under root."""

    root: Path
    bin: Path
    home: Path
    tmp: Path
    runtime: Path
    config: Path
    sessions: Path
    content: Path
    syslog: Path

    @classmethod
    def under(cls, root: Path) -> Layout:
        return cls(
            root=root,
            bin=root / "bin",
            home=root / "home",
            tmp=root / "tmp",
            runtime=root / "run",
            config=root / "config",
            sessions=root / "run" / "knowledge-sessions",
            content=root / "content",
            syslog=root / "syslog",
        )

    def create(self) -> None:
        for path in (self.home, self.tmp, self.config):
            path.mkdir(parents=True, exist_ok=True)
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)


def base_env(layout: Layout, kb_root: Path, system_path: str = SYSTEM_PATH) -> dict[str, str]:
    """Return the environment every run starts from."""
    locale = utf8_locale()
    return {
        "PATH": f"{layout.bin}:{system_path}",
        "HOME": str(layout.home),
        "TMPDIR": str(layout.tmp),
        "XDG_RUNTIME_DIR": str(layout.runtime),
        "XDG_CONFIG_HOME": str(layout.config),
        "SESSION_DIR": str(layout.sessions),
        "KNOWLEDGE_BASE": str(kb_root),
        "KB_CONTENT_DIR": str(layout.content),
        "FRESHNESS_TODAY_EPOCH": str(TODAY_EPOCH),
        "TZ": "UTC",
        "LANG": locale,
        "LC_ALL": locale,
        # The preamble's fixed directories hold host interpreters.
        "KB_PYTHON_DIRS": "",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": GIT_NAME,
        "GIT_AUTHOR_EMAIL": GIT_EMAIL,
        "GIT_AUTHOR_DATE": GIT_DATE,
        "GIT_COMMITTER_NAME": GIT_NAME,
        "GIT_COMMITTER_EMAIL": GIT_EMAIL,
        "GIT_COMMITTER_DATE": GIT_DATE,
    }


# Variables that must resolve inside the test's root before anything runs.
CONFINED = ("HOME", "TMPDIR", "SESSION_DIR", "XDG_RUNTIME_DIR")


def assert_confined(env: dict[str, str], root: Path) -> None:
    """Fail unless every confined variable resolves inside root."""
    real_root = root.resolve()
    for name in CONFINED:
        value = env.get(name)
        if value is None:
            continue
        resolved = Path(value).resolve()
        if resolved != real_root and real_root not in resolved.parents:
            raise HarnessError(f"{name}={value} resolves outside the test root {root}")

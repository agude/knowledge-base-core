"""doctor - Diagnose knowledge-base runtime and installation requirements.

Usage:
  doctor [--require CAPABILITY ...]

Options:
  --require NAME  Treat a capability failure as fatal. Repeatable.
                  Names: retrieval, capture, curation, sync, development,
                  adapters, or all.
  -h, --help      Show this help message.

The command is read-only with respect to the tooling and content roots. Its
capture smoke test uses a temporary buffer and removes it before returning.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from kb import cli, platform, session
from kb.content import ROOT, content_dir

CAPABILITIES = ("retrieval", "capture", "curation", "sync", "development", "adapters", "all")
ADAPTERS = (
    ("claude", "session-start"),
    ("claude", "session-prompt"),
    ("claude", "session-stop"),
    ("claude", "session-end"),
    ("claude", "pretool-allow"),
    ("codex", "session-start"),
    ("codex", "session-prompt"),
    ("codex", "session-stop"),
    ("codex", "session-end"),
)
CONTENT_DIRS = (
    "knowledge",
    "sources",
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
)
# The Pi adapter is TypeScript and stays in scripts/ through cutover (plan Constraints).
PI_DIR = ROOT / "scripts" / "adapters" / "pi"


class Report:
    def __init__(self, required: list[str]) -> None:
        self.required = required
        self.failures = 0
        self.warnings = 0

    def requires(self, capability: str) -> bool:
        return any(r in ("all", capability) for r in self.required)

    def __call__(self, capability: str, status: str, message: str) -> None:
        if status == "pass":
            print(f"PASS [{capability}] {message}")
        elif status == "warn":
            self.warnings += 1
            print(f"WARN [{capability}] {message}")
        elif self.requires(capability):
            self.failures += 1
            print(f"FAIL [{capability}] {message}")
        else:
            self.warnings += 1
            print(f"WARN [{capability}] {message} (use --require {capability} to make this fatal)")


def _command(report: Report, capability: str, name: str) -> None:
    if shutil.which(name):
        report(capability, "pass", f"{name} is available")
    else:
        report(capability, "fail", f"missing command: {name}")


def runtime(report: Report, executables: Path) -> None:
    """The interpreter the preamble chose, and the one install recorded for it.

    An interpreter below the minimum never reaches this point: _bootstrap
    rejects it first. The preamble tries the recorded interpreter before any
    other, so a record that names some other interpreter is one the preamble
    passed over: missing, not executable, or a version-manager shim.
    """
    major, minor = sys.version_info[:2]
    running = os.path.realpath(sys.executable)
    report("retrieval", "pass", f"Python {major}.{minor} meets the 3.11 minimum: {running}")
    record = ROOT / ".python-interpreter"
    if not record.is_file():
        report(
            "retrieval", "warn", f"{record} does not exist; run install to record the interpreter"
        )
    else:
        recorded = platform.read_text(record).split("\n", 1)[0]
        if recorded and os.path.realpath(recorded) == running:
            report("retrieval", "pass", ".python-interpreter names the running interpreter")
        else:
            report(
                "retrieval",
                "fail",
                f".python-interpreter names an interpreter the preamble cannot use: {recorded}",
            )
    search = executables / "search"
    if search.is_file() and os.access(search, os.X_OK):
        report("retrieval", "pass", f"tooling root is executable: {ROOT}")
    else:
        report("retrieval", "fail", "tooling root or its search executable is unavailable")


def capture_smoke(report: Report) -> None:
    """Append a message with awkward bytes to a temporary buffer and read it back."""
    message = 'doctor capture smoke\nwith a tab\tand quote "'
    try:
        with tempfile.TemporaryDirectory(prefix="knowledge-doctor.") as scratch:
            buffer = Path(scratch) / "session.jsonl"
            buffer.touch()
            session.append(buffer, "user", message.encode("utf-8"))
            record = json.loads(buffer.read_text(encoding="utf-8"))
            ok = record.get("message") == message and record.get("role") == "user"
    except (OSError, ValueError):
        ok = False
    if ok:
        report("capture", "pass", "stdin capture and JSON round-trip smoke test passed")
    else:
        report("capture", "fail", "stdin capture smoke test failed")


def adapters(report: Report, executables: Path) -> None:
    _command(report, "adapters", "node")
    for client, name in ADAPTERS:
        path = executables / "adapters" / client / name
        if path.is_file() and os.access(path, os.X_OK):
            report("adapters", "pass", f"{client} adapter is executable: {name}")
        else:
            report("adapters", "fail", f"{client} adapter is missing or not executable: {name}")
    for name in ("knowledge.ts", "package.json", "package-lock.json"):
        if (PI_DIR / name).is_file():
            report("adapters", "pass", f"Pi adapter file is present: {name}")
        else:
            report("adapters", "fail", f"Pi adapter file is missing: {name}")
    if shutil.which("node"):
        try:
            version = (
                subprocess.run(
                    ["node", "-p", "process.versions.node"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                or "unknown"
            )
        except OSError:
            version = "unknown"
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
        major, minor = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
        if major > 22 or (major == 22 and minor >= 19):
            report("adapters", "pass", f"Node.js {version} supports the Pi adapter")
        else:
            report("adapters", "fail", f"Node.js {version} is below the Pi requirement >=22.19.0")


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str] | None:
    """Run git; None when it cannot be started."""
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError:
        return None


def _git_version(report: Report, capability: str) -> None:
    result = _git("--version")
    version = result.stdout.strip().removeprefix("git version ") if result else ""
    if result and result.returncode == 0 and version:
        report(capability, "pass", f"git is available: {version}")
    else:
        report(capability, "fail", "missing command: git")


def _same(path: Path, expected: Path) -> bool:
    return os.path.realpath(path) == os.path.realpath(expected)


def content(report: Report, executables: Path) -> None:
    root = content_dir()
    if root.is_dir():
        report("curation", "pass", f"content root: {root}")
        for name in CONTENT_DIRS:
            if (root / name).is_dir():
                report("curation", "pass", f"content directory exists: {name}")
            else:
                report("curation", "fail", f"missing content directory: {name}")
        inside = _git("rev-parse", "--is-inside-work-tree", cwd=root)
        if inside and inside.stdout.strip() == "true":
            report("curation", "pass", "content root is a Git work tree")
            status = _git("status", "--porcelain", cwd=root)
            dirty = len(status.stdout.splitlines()) if status else 0
            if dirty == 0:
                report("curation", "pass", "content Git work tree is clean")
            else:
                report("curation", "warn", f"content Git work tree has {dirty} uncommitted path(s)")
        else:
            report("curation", "fail", "content root is not a Git work tree")
    else:
        report("curation", "fail", f"content root does not exist: {root}")
    hook = root / ".git" / "hooks" / "pre-commit"
    expected = executables / "hooks" / "pre-commit"
    if hook.exists() or hook.is_symlink():
        if _same(hook, expected):
            report("curation", "pass", "content pre-commit hook points to the tooling hook")
        else:
            report("curation", "fail", f"content pre-commit hook does not point to {expected}")
    else:
        report("curation", "fail", f"content pre-commit hook is not installed: {hook}")
    home = Path(os.environ.get("HOME", "~")).expanduser()
    for name in ("knowledge-base", "curate"):
        installed = home / ".agents" / "skills" / name
        if installed.exists() or installed.is_symlink():
            if _same(installed, ROOT / "skills" / name):
                report("curation", "pass", f"installed skill target is current: {name}")
            else:
                report("curation", "fail", f"installed skill target is not current: {installed}")
        else:
            report("curation", "fail", f"skill is not installed: {installed}")


def session_directory(report: Report) -> None:
    directory = session.session_dir()
    if not directory.is_dir():
        report("capture", "warn", f"session directory does not exist yet: {directory}")
    elif not platform.owned_by_user(directory):
        report(
            "capture", "fail", f"session directory is not owned by the current user: {directory}"
        )
    else:
        mode = f"{directory.stat().st_mode & 0o777:o}"
        if mode == "700":
            report(
                "capture",
                "pass",
                f"session directory is owned by the current user and mode 700: {directory}",
            )
        else:
            report(
                "capture", "fail", f"session directory must be mode 700: {directory} (mode {mode})"
            )


def main(argv: list[str]) -> int:
    platform.configure_stdio()
    required: list[str] = []
    index = 0
    while index < len(argv):
        word = argv[index]
        if word == "--require":
            if index + 1 >= len(argv):
                cli.fail(f"Option {word} requires an argument")
            required.append(argv[index + 1])
            index += 2
        elif word in ("-h", "--help"):
            cli.print_help(__doc__)
            return 0
        else:
            cli.fail(f"Unknown option: {word}")
    for capability in required:
        if capability not in CAPABILITIES:
            cli.fail(f"Unknown capability: {capability}")
    report = Report(required)
    executables = Path(sys.argv[0]).resolve().parent
    runtime(report, executables)
    capture_smoke(report)
    adapters(report, executables)
    _git_version(report, "curation")
    report("curation", "pass", "a SHA-256 implementation is available")
    _git_version(report, "sync")
    for name in ("shellcheck", "bats", "just", "uv"):
        _command(report, "development", name)
    content(report, executables)
    session_directory(report)
    if report.failures:
        print(
            f"Doctor found {report.failures} required failure(s) and {report.warnings} warning(s).",
            file=sys.stderr,
        )
        return 1
    print(f"Doctor completed with {report.warnings} warning(s).")
    return 0

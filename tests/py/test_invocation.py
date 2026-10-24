"""How a Python executable starts: root lookup, interpreter choice, failure rules.

Plan items 3.1 to 3.4. Each test copies kb/ into a temporary repository,
adds a probe command, and generates probe executables with
kb/executables.py run as a script, so nothing from kb is imported here.
These tests do not depend on KB_IMPL.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from kbtest import env as envmod
from kbtest import impl as implmod

pytestmark = pytest.mark.invocation

PROBE = '''"""Report how this process was started."""

import ast
import json
import os
import sys


def main(argv):
    import kb

    print(json.dumps({
        "argv": argv,
        "executable": sys.executable,
        "isolated": sys.flags.isolated,
        "kb": os.path.dirname(kb.__file__),
        "root": sys.path[0],
    }))
    return 0
'''


@dataclass
class Repo:
    root: Path
    home: Path
    bin: Path
    system: str

    def executable(self, name: str, module: str = "kb.commands.probe") -> Path:
        subprocess.run(
            [
                envmod.tools().python,
                str(self.root / "kb" / "executables.py"),
                "--dest",
                str(self.root / "python"),
                "--name",
                name,
                "--module",
                module,
            ],
            check=True,
        )
        return self.root / "python" / name

    def env(self, **overrides: str) -> dict[str, str]:
        env = {
            "PATH": f"{self.bin}:{self.system}",
            "HOME": str(self.home),
            "LANG": envmod.utf8_locale(),
            "LC_ALL": envmod.utf8_locale(),
            "KB_PYTHON_DIRS": "",
        }
        env.update(overrides)
        return env

    def run(
        self, path: Path, *args: str, cwd: Path | None = None, **env: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(path), *args],
            env=self.env(**env),
            cwd=cwd or self.home,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def link_python(self, directory: Path, name: str) -> Path:
        """A symlink to the harness interpreter; sys.executable reports its path."""
        directory.mkdir(parents=True, exist_ok=True)
        link = directory / name
        link.symlink_to(envmod.tools().python)
        return link


@pytest.fixture
def repo(tmp_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Repo:
    root = tmp_path / "repo"
    shutil.copytree(implmod.REPO / "kb", root / "kb", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(implmod.REPO / "pyproject.toml", root / "pyproject.toml")
    (root / "kb" / "commands" / "probe.py").write_text(PROBE, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # No Python anywhere on PATH except what a test puts in bin_dir.
    pythons = frozenset(
        entry.name
        for directory in envmod.SYSTEM_PATH.split(":")
        for entry in Path(directory).iterdir()
        if entry.name.startswith("python")
    )
    mirror = envmod.system_bin_without(
        tmp_path_factory.getbasetemp() / "sysbin-without-python", pythons
    )
    return Repo(root=root, home=home, bin=bin_dir, system=str(mirror))


def _report(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


# 3.1 Root lookup


@pytest.mark.parametrize("name", ["probe", "a/probe", "a/b/probe"])
@pytest.mark.parametrize("via", ["direct", "absolute-link", "relative-link"])
def test_root_found(repo: Repo, name: str, via: str) -> None:
    repo.link_python(repo.bin, "python3.15")
    target = repo.executable(name)
    path = target
    if via != "direct":
        links = repo.home / "links"
        links.mkdir()
        path = links / "probe"
        path.symlink_to(target if via == "absolute-link" else os.path.relpath(target, links))
    report = _report(repo.run(path, "x", "--y"))
    assert report["root"] == str(repo.root.resolve())
    assert report["kb"] == str((repo.root / "kb").resolve())
    assert report["argv"] == ["x", "--y"]
    assert report["isolated"] == 1


def test_no_root_within_four_levels(repo: Repo) -> None:
    repo.link_python(repo.bin, "python3.15")
    deep = repo.executable("a/b/c/d/probe")
    result = repo.run(deep)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "no repository root" in result.stderr


# 3.2 The preamble is shared byte for byte


def test_executables_carry_the_preamble() -> None:
    preamble = (implmod.REPO / "kb" / "preamble.sh").read_text(encoding="utf-8")
    assert "'''" not in preamble
    executables = sorted(p for p in (implmod.REPO / "python").rglob("*") if p.is_file())
    for path in executables:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh\n''':'\n" + preamble + "'''\n"), path
    check = subprocess.run(
        [envmod.tools().python, str(implmod.REPO / "kb" / "executables.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr


def test_executable_compiles_without_warnings(repo: Repo) -> None:
    source = repo.executable("probe").read_text(encoding="utf-8")
    result = subprocess.run(
        [
            envmod.tools().python,
            "-I",
            "-W",
            "error",
            "-c",
            "import sys; compile(sys.stdin.read(), 'probe', 'exec')",
        ],
        input=source,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# 3.4 Invocation


def test_hostile_python_environment_is_ignored(repo: Repo) -> None:
    repo.link_python(repo.bin, "python3.15")
    probe = repo.executable("probe")
    expected = _report(repo.run(probe))
    hostile = repo.home / "hostile"
    (hostile / "kb").mkdir(parents=True)
    (hostile / "kb" / "__init__.py").write_text(
        "raise SystemExit('hostile kb')\n", encoding="utf-8"
    )
    startup = repo.home / "startup.py"
    startup.write_text("print('startup ran')\n", encoding="utf-8")
    result = repo.run(probe, PYTHONPATH=str(hostile), PYTHONSTARTUP=str(startup))
    assert _report(result) == expected


def test_failing_shim_is_skipped(repo: Repo) -> None:
    shims = repo.home / ".pyenv" / "shims"
    shims.mkdir(parents=True)
    shim = shims / "python3.15"
    shim.write_text("#!/bin/sh\nexit 127\n", encoding="utf-8")
    shim.chmod(0o755)
    real = repo.link_python(repo.home / "real", "python3.15")
    probe = repo.executable("probe")
    report = _report(repo.run(probe, PATH=f"{shims}:{real.parent}:{repo.system}"))
    assert report["executable"] == str(real)


def test_relative_link_chain_finds_python_interpreter_file(repo: Repo) -> None:
    chosen = repo.link_python(repo.home / "chosen", "python-chosen")
    (repo.root / ".python-interpreter").write_text(f"{chosen}\n", encoding="utf-8")
    probe = repo.executable("a/probe")
    first = repo.home / "one"
    second = repo.home / "two" / "three"
    first.mkdir()
    second.mkdir(parents=True)
    (second / "link").symlink_to(os.path.relpath(probe, second))
    (first / "link").symlink_to(os.path.relpath(second / "link", first))
    elsewhere = repo.home / "elsewhere"
    elsewhere.mkdir()
    report = _report(repo.run(first / "link", cwd=elsewhere))
    assert report["executable"] == str(chosen)


def test_python_interpreter_file_wins_over_path(repo: Repo) -> None:
    on_path = repo.link_python(repo.bin, "python3.15")
    chosen = repo.link_python(repo.home / "chosen", "python3.11")
    (repo.root / ".python-interpreter").write_text(f"{chosen}\n", encoding="utf-8")
    report = _report(repo.run(repo.executable("probe")))
    assert report["executable"] == str(chosen) != str(on_path)


def test_one_interpreter_start(repo: Repo) -> None:
    log = repo.home / "starts"
    wrapper = repo.home / "counting-python"
    wrapper.write_text(
        f"#!/bin/sh\necho start >> '{log}'\nexec '{envmod.tools().python}' \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (repo.root / ".python-interpreter").write_text(f"{wrapper}\n", encoding="utf-8")
    _report(repo.run(repo.executable("probe")))
    assert log.read_text(encoding="utf-8") == "start\n"


def test_fixed_directories_are_searched(repo: Repo) -> None:
    directory = repo.home / ".local" / "bin"
    found = repo.link_python(directory, "python3.13")
    del_dirs = repo.env()
    del_dirs.pop("KB_PYTHON_DIRS")
    result = subprocess.run(
        [str(repo.executable("probe"))],
        env=del_dirs,
        cwd=repo.home,
        capture_output=True,
        text=True,
        check=False,
    )
    assert _report(result)["executable"] == str(found)


# 3.3 Failure rules when no interpreter qualifies


def _old_python(repo: Repo) -> None:
    """A python3 that fails the version probe, as Python 3.9 does."""
    fake = repo.bin / "python3"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)


def test_session_context_reports_on_stdout(repo: Repo) -> None:
    _old_python(repo)
    result = repo.run(repo.executable("session-context"))
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert "Python 3.11" in result.stdout and str(repo.bin / "python3") in result.stdout


@pytest.mark.parametrize(
    "name",
    ["session-init", "session-flush", "adapters/claude/session-end", "adapters/codex/session-stop"],
)
def test_session_hooks_exit_silently(repo: Repo, name: str) -> None:
    _old_python(repo)
    result = repo.run(repo.executable(name))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


def test_pretool_allow_fails_open(repo: Repo) -> None:
    _old_python(repo)
    result = repo.run(repo.executable("adapters/claude/pretool-allow"))
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.parametrize("staged", [False, True])
def test_pre_commit_blocks_only_knowledge_commits(repo: Repo, staged: bool) -> None:
    _old_python(repo)
    hook = repo.executable("hooks/pre-commit")
    content = repo.home / "content"
    (content / "knowledge").mkdir(parents=True)
    git_env = {**repo.env(), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=content, env=git_env, check=True)
    (content / "knowledge" / "a.md").write_text("# A\n", encoding="utf-8")
    (content / "notes.txt").write_text("n\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "knowledge/a.md" if staged else "notes.txt"],
        cwd=content,
        env=git_env,
        check=True,
    )
    result = repo.run(hook, cwd=content)
    if staged:
        assert result.returncode == 1 and "Python 3.11" in result.stderr
    else:
        assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == ""


def test_direct_cli_use_fails_with_a_message(repo: Repo) -> None:
    _old_python(repo)
    result = repo.run(repo.executable("search"))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Python 3.11" in result.stderr


def _python39() -> str | None:
    found = subprocess.run(
        ["uv", "python", "find", "--no-project", "3.9"],
        capture_output=True,
        text=True,
        check=False,
    )
    return found.stdout.strip() if found.returncode == 0 else None


@pytest.mark.parametrize("name", ["search", "session-context"])
def test_stale_python_interpreter_file_is_rechecked(repo: Repo, name: str) -> None:
    """A .python-interpreter that now names Python 3.9 fails in Python, by role."""
    old = _python39() if shutil.which("uv") else None
    if old is None:
        if os.environ.get("CI") == "true":
            pytest.fail("CI must install Python 3.9 (just py-sync)")
        pytest.skip("no Python 3.9 interpreter installed (just py-sync)")
    (repo.root / ".python-interpreter").write_text(f"{old}\n", encoding="utf-8")
    result = repo.run(repo.executable(name))
    if name == "search":
        assert result.returncode == 1 and "Python 3.11" in result.stderr
        assert result.stdout == ""
    else:
        assert result.returncode == 0 and "Python 3.11" in result.stdout


def test_bootstrap_parses_under_old_pythons() -> None:
    """kb/__init__.py and kb/_bootstrap.py must compile as Python 3.9."""
    for name in ("__init__.py", "_bootstrap.py"):
        source = (implmod.REPO / "kb" / name).read_text(encoding="utf-8")
        ast.parse(source, name, feature_version=(3, 9))
    assert sys.version_info >= (3, 11)

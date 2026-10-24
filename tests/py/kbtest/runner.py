"""Run executables against a per-test content repository."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from kbtest import env as envmod
from kbtest.impl import Impl
from kbtest.normalize import Normalizer

TRACEBACK = b"Traceback (most recent call last):"


@dataclass(frozen=True)
class Result:
    script: str
    args: tuple[str, ...]
    impl: str
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def out(self) -> str:
        return self.stdout.decode("utf-8", errors="surrogateescape")

    @property
    def err(self) -> str:
        return self.stderr.decode("utf-8", errors="surrogateescape")


@dataclass
class KB:
    """One test's view of the system under test.

    layout: per-test directories; every path the executables see is inside.
    resolve_impl: maps an implementation name to its tree.
    default_impl: KB_IMPL for this run; run(impl=...) overrides it per call.
    session_prefix: prefix for every session ID the test uses.
    """

    layout: envmod.Layout
    resolve_impl: Callable[[str], Impl]
    default_impl: str
    session_prefix: str
    system_path: str = envmod.SYSTEM_PATH
    normalizer: Normalizer = field(default_factory=Normalizer)
    invocations: list[tuple[str, str]] = field(default_factory=list)
    _session_ids: int = 0

    # Setup

    def setup(self) -> None:
        self.layout.create()
        envmod.build_bin(self.layout.bin, self.layout.syslog)
        self.normalizer.add_path(self.layout.content, "<CONTENT>")
        self.normalizer.add_path(self.layout.root, "<ROOT>")
        self._init_content()

    def without_tools(self, names: frozenset[str], mirror_root: Path) -> None:
        """Run every later command with the named tools absent from PATH.

        mirror_root holds one mirror of the system directories per set of
        names, shared across tests.
        """
        for name in names:
            link = self.layout.bin / name
            if link.is_symlink() or link.exists():
                link.unlink()
        mirror = mirror_root / ("without-" + "-".join(sorted(names)))
        self.system_path = str(envmod.system_bin_without(mirror, names))

    def restore_tools(self) -> None:
        """Undo without_tools: the selected tools and the system PATH again."""
        selected = envmod.tools()
        for name, target in (("jq", selected.jq), ("git", selected.git)):
            link = self.layout.bin / name
            if target is not None and not link.exists():
                link.symlink_to(target)
        self.system_path = envmod.SYSTEM_PATH

    def _init_content(self) -> None:
        content = self.layout.content
        for sub in (
            "knowledge",
            "observations/pending",
            "observations/archived",
            "questions/open",
            "questions/resolved",
            "sources",
        ):
            (content / sub).mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")
        (content / ".gitkeep").touch()
        self.git("add", ".gitkeep")
        self.git("commit", "-q", "-m", "init")

    # Running

    def env(self, impl: Impl, overrides: Mapping[str, str | None] | None = None) -> dict[str, str]:
        result = envmod.base_env(self.layout, impl.kb_root, self.system_path)
        for name, value in (overrides or {}).items():
            if value is None:
                result.pop(name, None)
            else:
                result[name] = value
        envmod.assert_confined(result, self.layout.root)
        return result

    def run(
        self,
        script: str,
        *args: str,
        stdin: str | bytes | None = None,
        env: Mapping[str, str | None] | None = None,
        impl: str | None = None,
        cwd: Path | None = None,
        timeout: float = 60,
    ) -> Result:
        tree = self.resolve_impl(impl or self.default_impl)
        if not tree.has(script):
            if tree.name == "python":
                pytest.skip(f"not ported to python: {script}")
            raise AssertionError(f"{tree.name} has no executable {script} in {tree.scripts_dir}")
        self.normalizer.add_path(tree.kb_root, "<KB>")
        # Python's executables live in python/, not scripts/; outputs name either as one.
        self.normalizer.add_path(tree.scripts_dir, "<KB>/scripts")
        self.invocations.append((tree.name, script))
        data = stdin.encode("utf-8") if isinstance(stdin, str) else stdin
        completed = subprocess.run(
            [str(tree.executable(script)), *args],
            input=data if data is not None else b"",
            capture_output=True,
            env=self.env(tree, env),
            cwd=cwd or self.layout.root,
            timeout=timeout,
            check=False,
        )
        if tree.name == "python" and TRACEBACK in completed.stderr:
            pytest.fail(
                f"{script} raised an uncaught exception:\n"
                + completed.stderr.decode("utf-8", errors="replace")
            )
        return Result(
            script=script,
            args=args,
            impl=tree.name,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def git(self, *args: str) -> str:
        """Run git in the content repository with the test environment."""
        completed = subprocess.run(
            ["git", *args],
            cwd=self.layout.content,
            env=self.git_env(),
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout

    def git_env(self) -> dict[str, str]:
        return envmod.base_env(self.layout, self.layout.root, self.system_path)

    def commits(self, repo: Path | None = None) -> list[str]:
        """Every commit hash in repo (default: the content repository)."""
        completed = subprocess.run(
            ["git", "rev-list", "--all"],
            cwd=repo or self.layout.content,
            env=self.git_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stdout.split()

    # Normalizing

    def norm(self, text: str, *, repos: tuple[Path, ...] = ()) -> str:
        """Normalize text; repos adds commit hashes from further repositories."""
        self.normalizer.commits = self._all_commits(repos)
        return self.normalizer(text)

    def norm_err(self, text: str, *, repos: tuple[Path, ...] = ()) -> str:
        self.normalizer.commits = self._all_commits(repos)
        return self.normalizer.stderr(text)

    def transcript(self, *results: Result) -> str:
        """Render runs as one normalized text: command, exit code, stdout, stderr."""
        parts = []
        for result in results:
            command = " ".join([result.script, *result.args])
            parts.append(
                f"$ {command}\nexit {result.returncode}\n"
                f"--- stdout\n{self.norm(result.out)}--- stderr\n{self.norm_err(result.err)}"
            )
        return "\n".join(parts).replace(self.session_prefix, "<SESSION>-")

    def _all_commits(self, repos: tuple[Path, ...]) -> list[str]:
        hashes = self.commits()
        for repo in repos:
            hashes += self.commits(repo)
        return hashes

    def instructions(self) -> str:
        """The tooling repo's AGENTS.md, which session context prints first."""
        path = self.resolve_impl(self.default_impl).kb_root / "AGENTS.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def context_facts(self, text: str) -> str:
        from kbtest import facts

        return self.norm(facts.session_context(text, self.instructions()))

    def placeholder_instructions(self, text: str) -> str:
        """Replace the tooling repo's AGENTS.md, printed verbatim, with a placeholder.

        Session context starts with that file. Goldens pin that it appears
        verbatim without changing whenever the instructions change.
        """
        tree = self.resolve_impl(self.default_impl)
        path = tree.kb_root / "AGENTS.md"
        if not path.is_file():
            return text
        return text.replace(path.read_text(encoding="utf-8"), "<KB AGENTS.md verbatim>\n")

    # Locks

    @contextmanager
    def hold_lock(self) -> Iterator[int]:
        """Hold .observe.lock on behalf of a live process, as a concurrent writer would."""
        holder = subprocess.Popen(["sleep", "600"])
        lockdir = self.layout.content / ".observe.lock"
        try:
            lockdir.mkdir()
            (lockdir / "pid").write_text(f"{holder.pid}\n", encoding="utf-8")
            yield holder.pid
        finally:
            holder.kill()
            holder.wait()

    # Content

    def session_id(self) -> str:
        self._session_ids += 1
        return f"{self.session_prefix}{self._session_ids}"

    def create_article(self, name: str, content: str) -> Path:
        path = self.layout.content / "knowledge" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n", encoding="utf-8", newline="")
        return path

    def create_observation(self, name: str, title: str, body: str) -> Path:
        path = self.layout.content / "observations" / "pending" / name
        path.write_text(
            f'---\ntitle: "{title}"\nsource: session\ncreated: 2026-04-12T00:00:00Z\n---\n\n{body}\n',
            encoding="utf-8",
            newline="",
        )
        return path

    def create_question(self, name: str, title: str, context: str = "") -> Path:
        lines = ["---", f'title: "{title}"', "source: test"]
        if context:
            lines.append(f"context: {context}")
        lines += ["created: 2026-04-12T00:00:00Z", "---"]
        path = self.layout.content / "questions" / "open" / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
        return path

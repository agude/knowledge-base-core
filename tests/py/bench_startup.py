"""Measure Python executable start-up and the SessionEnd hook (plan 3.6).

Builds a temporary tree with a copy of kb/, generated executables, and a
content repository whose installed pre-commit hook is the bash one (the
hook is ported last, in 4.17). Each workload runs once to warm up, then
--runs times; "cold" removes kb's bytecode cache before every run.

Workloads:
  empty            an executable whose main() returns 0: preamble, interpreter, bootstrap
  session-end      python/adapters/claude/session-end flushing a 200-message buffer
  shim             the dotfiles Claude SessionEnd shim, exec-ing a Python session-flush
  bash-session-end the bash adapter, for comparison
  bash-shim        the shim with the bash session-flush, for comparison

Usage: python tests/py/bench_startup.py [--runs N] [--shim PATH]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from bench import Bench, _commit, _percentile

from kbtest import env as envmod
from kbtest import impl as implmod

DEFAULT_SHIM = Path.home() / ".dotfiles/llm/claude/hooks.d/SessionEnd/010.knowledge.sh"
EMPTY = '"""Do nothing."""\n\n\ndef main(argv):\n    return 0\n'


def _build_tree(root: Path) -> Path:
    tree = root / "tree"
    shutil.copytree(implmod.REPO / "kb", tree / "kb", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(implmod.REPO / "pyproject.toml", tree / "pyproject.toml")
    (tree / "kb" / "commands" / "empty.py").write_text(EMPTY, encoding="utf-8")
    # As install will record it: the common path starts one interpreter.
    (tree / ".python-interpreter").write_text(f"{envmod.tools().python}\n", encoding="utf-8")
    for name, module, dest in (
        ("empty", "kb.commands.empty", "python"),
        ("adapters/claude/session-end", "kb.commands.adapters.claude.session_end", "python"),
        ("session-flush", "kb.commands.session_flush", "scripts"),
    ):
        subprocess.run(
            [
                sys.executable,
                str(tree / "kb" / "executables.py"),
                "--dest",
                str(tree / dest),
                "--name",
                name,
                "--module",
                module,
            ],
            check=True,
        )
    return tree


def _measure(runs: int, action: Callable[[], int], before: Callable[[], None]) -> dict[str, object]:
    samples, codes = [], set()
    for index in range(runs + 1):
        before()
        start = time.perf_counter()
        codes.add(action())
        elapsed = (time.perf_counter() - start) * 1000
        if index:
            samples.append(elapsed)
    samples.sort()
    return {
        "p50_ms": round(samples[len(samples) // 2], 1),
        "p95_ms": round(_percentile(samples, 0.95), 1),
        "exit_codes": sorted(codes),
    }


def benchmark(args: argparse.Namespace, scratch: Path) -> dict[str, object]:
    bash = implmod.resolve("bash", scratch / "impl")
    bench = Bench(scratch / "kb", bash)
    bench.load(None, 1, 0)
    tree = _build_tree(scratch)
    head = bench.git("rev-parse", "HEAD").strip()
    cache = tree / "kb"
    buffers: list[Path] = []
    commits: dict[str, set[int]] = {}

    def run(path: Path, stdin: str, env: dict[str, str]) -> int:
        return subprocess.run(
            [str(path)],
            input=stdin,
            text=True,
            env=env,
            cwd=bench.layout.root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode

    def clear_cache() -> None:
        for directory in cache.rglob("__pycache__"):
            shutil.rmtree(directory)

    def end_payload() -> str:
        buffer = bench.prepare_buffer()
        buffers.append(buffer)
        return json.dumps({"session_id": buffer.name[len("session-") : -len(".jsonl")]})

    env_python = {**bench.env, "KNOWLEDGE_BASE": str(tree), "KNOWLEDGE_OBSERVE": "1"}
    env_bash = {**bench.env, "KNOWLEDGE_BASE": str(bash.kb_root), "KNOWLEDGE_OBSERVE": "1"}
    workloads: list[tuple[str, Path, dict[str, str], bool]] = [
        ("empty", tree / "python" / "empty", env_python, False),
        ("session-end", tree / "python/adapters/claude/session-end", env_python, True),
        ("bash-session-end", bash.executable("adapters/claude/session-end"), env_bash, True),
    ]
    if args.shim.is_file():
        workloads += [
            ("shim", args.shim, env_python, True),
            ("bash-shim", args.shim, env_bash, True),
        ]
    results = []
    for name, path, env, flushes in workloads:
        caches = ["warm"] if name.startswith("bash") else ["cold", "warm"]
        for state in caches:
            payload: list[str] = [""]

            def before(
                state: str = state, flushes: bool = flushes, payload: list[str] = payload
            ) -> None:
                if flushes:
                    bench.reset(head)
                    payload[0] = end_payload()
                if state == "cold":
                    clear_cache()

            def action(
                path: Path = path, env: dict[str, str] = env, payload: list[str] = payload
            ) -> int:
                return run(path, payload[0], env)

            record = _measure(args.runs, action, before)
            if flushes:
                made = int(bench.git("rev-list", "--count", f"{head}..HEAD"))
                commits.setdefault(name, set()).add(made)
                record["last_run_commits"] = made
            results.append({"workload": name, "cache": state, **record})
    bench.reset(head)
    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": _commit(),
        "python": str(envmod.tools().python),
        "runs": args.runs,
        "shim": str(args.shim) if args.shim.is_file() else None,
        "results": results,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--shim", type=Path, default=DEFAULT_SHIM)
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="kb-startup-") as scratch:
        report = benchmark(args, Path(scratch))
        if (Path(scratch) / "impl" / "bash-frozen").exists():
            implmod.remove_worktree(Path(scratch) / "impl" / "bash-frozen")
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

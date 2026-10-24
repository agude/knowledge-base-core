"""Time the read commands and the hook workloads against one corpus.

The corpus is a copy of an existing content tree (--content DIR, such as the
live knowledge base) or a synthetic tree from kbtest.corpus (--scale N). The
source tree is copied, never modified. Each command runs once to warm the
caches, then --runs times; the JSON report on stdout holds p50 and p95 wall
times in milliseconds, one record per command.

Hook workloads (docs/python-port.md):
  hook:session-start  session-init with no orphan buffers, then session-context.
  hook:session-end    session-flush of a 200-message buffer: one observation
                      commit with the content repository's pre-commit hook.

Usage: python tests/py/bench.py [--impl NAME] [--scale N | --content DIR]
                                [--seed S] [--runs N] [--query WORD]
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from kbtest import corpus
from kbtest import env as envmod
from kbtest import impl as implmod

TRANSCRIPT_MESSAGES = 200
SYNTHETIC_QUERY = "benchmarkbeta"
LIVE_QUERY = "commit"


class Bench:
    def __init__(self, root: Path, tree: implmod.Impl) -> None:
        self.layout = envmod.Layout.under(root)
        self.tree = tree
        self.layout.create()
        envmod.build_bin(self.layout.bin, self.layout.syslog)
        self.env = envmod.base_env(self.layout, tree.kb_root)
        # The pre-commit hook stamps real dates; freshness uses the real clock too.
        del self.env["FRESHNESS_TODAY_EPOCH"]
        self.sessions = 0

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.layout.content,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def load(self, source: Path | None, scale: int, seed: int) -> None:
        content = self.layout.content
        if source is None:
            corpus.generate(content, scale=scale, seed=seed)
        else:
            shutil.copytree(source, content, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "--no-verify", "-m", "Corpus")
        hooks = content / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        hook = self.tree.executable("hooks/pre-commit")
        if hook.exists():
            (hooks / "pre-commit").symlink_to(hook)

    def run(self, script: str, *args: str) -> int:
        return subprocess.run(
            [str(self.tree.executable(script)), *args],
            env=self.env,
            cwd=self.layout.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode

    def session_id(self) -> str:
        self.sessions += 1
        return f"bench-{self.sessions}"

    def session_start(self) -> int:
        code = self.run("session-init", "--session-id", self.session_id())
        return code or self.run("session-context")

    def prepare_buffer(self) -> Path:
        self.layout.sessions.mkdir(mode=0o700, parents=True, exist_ok=True)
        buffer = self.layout.sessions / f"session-{self.session_id()}.jsonl"
        lines = []
        for index in range(TRANSCRIPT_MESSAGES):
            role = "user" if index % 2 == 0 else "assistant"
            message = f"Message {index}: " + "word " * 40
            lines.append(json.dumps({"role": role, "message": message, "timestamp": index}))
        buffer.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return buffer

    def reset(self, head: str) -> None:
        self.git("reset", "-q", "--hard", head)
        self.git("clean", "-q", "-fd", "observations")
        for path in self.layout.sessions.glob("*"):
            path.unlink()


def _percentile(samples: list[float], fraction: float) -> float:
    """Nearest-rank percentile."""
    ordered = sorted(samples)
    return ordered[max(math.ceil(fraction * len(ordered)) - 1, 0)]


def _measure(
    runs: int,
    action: Callable[[], int],
    before: Callable[[], None] | None = None,
    after: Callable[[], None] | None = None,
) -> dict[str, object]:
    samples = []
    codes = set()
    for index in range(runs + 1):
        if before:
            before()
        start = time.perf_counter()
        codes.add(action())
        elapsed = (time.perf_counter() - start) * 1000
        if after:
            after()
        if index:  # The first run warms the caches.
            samples.append(elapsed)
    return {
        "p50_ms": round(statistics.median(samples), 1),
        "p95_ms": round(_percentile(samples, 0.95), 1),
        "min_ms": round(min(samples), 1),
        "max_ms": round(max(samples), 1),
        "exit_codes": sorted(codes),
    }


def _commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=implmod.REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _counts(content: Path) -> dict[str, int]:
    return {
        kind: sum(1 for _ in (content / path).rglob("*.md"))
        for kind, path in (
            ("articles", "knowledge"),
            ("archived", "observations/archived"),
            ("pending", "observations/pending"),
            ("questions", "questions"),
        )
    }


def benchmark(args: argparse.Namespace, scratch: Path) -> dict[str, object]:
    tree = implmod.resolve(args.impl, scratch / "impl")
    bench = Bench(scratch / "kb", tree)
    bench.load(args.content, args.scale, args.seed)
    query = args.query or (LIVE_QUERY if args.content else SYNTHETIC_QUERY)
    first_article = min(
        path.relative_to(bench.layout.content).as_posix()
        for path in (bench.layout.content / "knowledge").rglob("*.md")
    )
    commands: list[tuple[str, list[str]]] = [
        ("search", [query]),
        ("search", ["--json", query]),
        ("section", ["--file", first_article, "--number", "1"]),
        ("toc", ["--map"]),
        ("status", ["--brief"]),
        ("stale", ["--count"]),
        ("pending", []),
        ("context", []),
        ("session-context", []),
    ]
    results = []
    for script, script_args in commands:
        record = _measure(args.runs, lambda s=script, a=script_args: bench.run(s, *a))
        # The label names no corpus path, so reports from the live tree stay generic.
        label = " ".join([script, *script_args]).replace(first_article, "<first-article>")
        results.append({"command": label, **record})

    results.append({"command": "hook:session-start", **_measure(args.runs, bench.session_start)})

    head = bench.git("rev-parse", "HEAD").strip()
    buffers: list[Path] = []
    commits: set[int] = set()

    def before_end() -> None:
        bench.reset(head)
        buffers.append(bench.prepare_buffer())

    def after_end() -> None:
        commits.add(int(bench.git("rev-list", "--count", f"{head}..HEAD")))

    end = _measure(
        args.runs, lambda: bench.run("session-flush", str(buffers[-1])), before_end, after_end
    )
    # One commit per run shows the workload did what it claims.
    results.append({"command": "hook:session-end", **end, "commits": sorted(commits)})
    bench.reset(head)

    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "commit": _commit(),
        "impl": args.impl,
        "corpus": {
            "source": "copy" if args.content else f"synthetic scale={args.scale} seed={args.seed}",
            **_counts(bench.layout.content),
        },
        "runs": args.runs,
        "query": query,
        "results": results,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--impl", default=implmod.selected_name(), choices=implmod.IMPLEMENTATIONS)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--scale", type=int, default=10)
    source.add_argument("--content", type=Path, help="copy this content tree instead")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--query", help="search term (default depends on the corpus)")
    args = parser.parse_args(argv)
    if args.content is not None and not (args.content / "knowledge").is_dir():
        parser.error(f"{args.content} has no knowledge/ directory")
    with tempfile.TemporaryDirectory(prefix="kb-bench-") as scratch:
        report = benchmark(args, Path(scratch))
        if (Path(scratch) / "impl" / "bash-frozen").exists():
            implmod.remove_worktree(Path(scratch) / "impl" / "bash-frozen")
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Run the suite against the null controls and enforce the null rule.

null0: every executable exits 0 with no output.
null1: every executable exits 1 with no output.

Rule: every test fails under at least one control. A test that passes under
null0 must carry @pytest.mark.null_ok("<reason>"), and a null_ok mark on a
test that fails under null0 is stale. Harness self-tests and fixture-data
checks (markers harness and data) are excluded.

With --contract, reference goldens record instead of failing, so every test
must fail the controls through contract goldens or semantic assertions. That
is the rule the Python port is gated on.

Usage: python tests/py/nullcheck.py [--contract] [pytest args...]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PYTEST_USAGE_ERRORS = {2, 3, 4}


def run_control(
    name: str, report: Path, extra: list[str], golden_mode: str
) -> dict[str, dict[str, object]]:
    env = dict(os.environ, KB_IMPL=name, KB_NULL_REPORT=str(report))
    env.pop("KB_SCRIPTS_DIR", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-m",
            "not harness and not data",
            "--no-header",
            "-n",
            "auto",
            f"--golden-mode={golden_mode}",
            *extra,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode in PYTEST_USAGE_ERRORS:
        sys.stderr.write(completed.stdout + completed.stderr)
        raise SystemExit(f"nullcheck: pytest under {name} exited {completed.returncode}")
    records = {}
    if report.exists():
        for line in report.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            records[record["nodeid"]] = record
    return records


def main(argv: list[str]) -> int:
    # --contract: reference goldens do not fail, so each test must fail the
    # null controls through contract goldens or semantic assertions alone.
    golden_mode = "strict"
    if argv[:1] == ["--contract"]:
        golden_mode, argv = "reference", argv[1:]
    with tempfile.TemporaryDirectory() as scratch:
        null0 = run_control("null0", Path(scratch) / "null0.jsonl", argv, golden_mode)
        null1 = run_control("null1", Path(scratch) / "null1.jsonl", argv, golden_mode)

    if not null0:
        print("nullcheck: no tests ran", file=sys.stderr)
        return 1

    problems = []
    for nodeid, record in sorted(null0.items()):
        passed0 = record["outcome"] == "passed"
        passed1 = null1.get(nodeid, {}).get("outcome") == "passed"
        if passed0 and passed1:
            problems.append(f"passes under both null0 and null1: {nodeid}")
        elif passed0 and not record["null_ok"]:
            problems.append(f"passes under null0 without a null_ok mark: {nodeid}")
        elif not passed0 and record["null_ok"]:
            problems.append(f"stale null_ok mark (fails under null0): {nodeid}")
        if record["outcome"] == "skipped" or null1.get(nodeid, {}).get("outcome") == "skipped":
            problems.append(f"skipped under a null control: {nodeid}")

    for problem in problems:
        print(f"nullcheck: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"nullcheck: {len(null0)} tests each fail under at least one null control")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

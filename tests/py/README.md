# Characterization suite

Black-box tests for the knowledge-base executables. Each test runs an
executable as a subprocess and asserts on its stdout, stderr, exit code, the
files it writes, the Git commits it makes, and the syslog calls it makes. No
test imports implementation code, so the same tests check the Bash runtime
and its Python replacement ([docs/python-port.md](../../docs/python-port.md)).

```bash
just test-py                    # run against Bash
just test-py --update-golden    # rewrite golden files from actual output
just test-py-null               # every test must fail the null controls without reference goldens
KB_IMPL=python just test-py     # run against the Python tree
```

## Selecting an implementation

| Variable | Meaning |
|---|---|
| `KB_IMPL` | `bash` (default), `python`, `null0`, or `null1`. The identity that markers use. |
| `KB_SCRIPTS_DIR` | Directory of executables for the selected implementation. Overrides the location, never the identity. |
| `KB_BASH` | Bash 4 or newer to use. Default: the first one on `PATH`. |
| `KB_PYTHON` | Python 3.11 or newer to use. Default: the base interpreter behind the uv environment (`sys._base_executable`). It must not be able to import pytest, which enforces "standard library only". |

`bash` runs `scripts/` from the working tree until the tag `bash-frozen`
exists; after that it runs a `git worktree` of the tag, one per pytest
worker, and the report header names the tag. `python` runs a per-worker copy
of `kb/`, `python/`, and the files they read, so `install` writing
`.python-interpreter` or bytecode never touches the working tree. The tag was created at the end
of the behavior audit (plan 2.4). `test_harness.py::test_bash_matches_frozen_tag`
fails if `scripts/` drifts from it; a deliberate bash change moves the tag
(`git tag -f -a bash-frozen`). CI checks out tags so it uses the worktree too. `python` runs
`python/`. A test that invokes an executable missing from `python/` is
skipped with the missing name. `run(..., impl="bash")` overrides the
implementation for one call.

`null0` and `null1` are generated trees in which every executable exits 0 or
1 with no output.

## Environment

Every subprocess gets an environment built from scratch. Nothing is
inherited.

- `PATH` is `<root>/bin` followed by a per-session mirror of
  `/usr/bin:/bin` without any `python*` entry. `<root>/bin` holds symlinks
  to the selected `bash`, `git`, and `jq`, the selected interpreter as both
  `python3` and `python3.<minor>`, and a `logger` stub that appends its
  arguments to `<root>/syslog`. `KB_PYTHON_DIRS` is empty. Together these
  make the Python executables' preamble choose `KB_PYTHON`, never a host
  interpreter (`test_harness.py::test_only_the_selected_python_is_visible`).
- The `no_jq` fixture removes `jq`. Because `/usr/bin` can hold `jq`, it
  also replaces `/usr/bin:/bin` with a per-session mirror of those
  directories without `jq`. jq is optional in production, so this is a real
  configuration, not a stub.
- `HOME`, `TMPDIR`, `XDG_RUNTIME_DIR`, `XDG_CONFIG_HOME`, and `SESSION_DIR`
  are inside the test's root. `run()` refuses to start a process when any of
  `HOME`, `TMPDIR`, `SESSION_DIR`, or `XDG_RUNTIME_DIR` resolves outside it.
- `KNOWLEDGE_BASE` is the implementation's root. `KB_CONTENT_DIR` is a fresh
  content repository with the standard tree and one commit.
- `FRESHNESS_TODAY_EPOCH` is fixed at 2026-10-23T00:00:00Z.
- `TZ=UTC`. `LANG` and `LC_ALL` are `KB_LOCALE` when it is set, otherwise
  `C.UTF-8`, or `en_US.UTF-8` where `C.UTF-8` is missing.
- Git author and committer names, emails, and dates are fixed, with
  `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_CONFIG_NOSYSTEM=1`.

## Fixtures

| Fixture | Provides |
|---|---|
| `kb` | A fresh content repository and `run()` for the selected implementation. |
| `no_jq` | `kb` with `jq` absent. |
| `without_tools` | A function: `without_tools("tree")` removes the named tools from `PATH` for `kb`, for host-dependent behavior such as an optional utility. |
| `hooked` | `kb` with the implementation's `hooks/pre-commit` installed in the content repository. It also normalizes the real UTC date to `<TODAY>`, because the hook stamps `updated:` with it. |
| `golden` | Golden-file checks for the current test. |

## Leak check

Every session ID a test uses comes from `kb.session_id()` and starts with
`pytest-<random>-`. After the suite, the run fails if a file containing that
prefix exists in the real session directory
(`${XDG_RUNTIME_DIR:-/tmp}/knowledge-sessions-<uid>`). With `CI=true`, where
no live session runs, the run fails if that directory holds any file at all.
The check detects a leak after the fact; it cannot prevent one.

## Assertion tiers

The suite separates what the Python port must reproduce from what it may
change:

| Tier | How | Gates `KB_IMPL=python`? |
|---|---|---|
| Contract formats | `golden.contract(name, text)`: byte-exact goldens for formats other processes read (files written to the content repository, session buffers, locks, hook JSON, commit messages). | Yes |
| Behavior | Semantic assertions: parsed JSON values, which files or sections are returned and in what order where ranking is the point, files and commits made, exit codes, budget invariants. | Yes |
| Reference | `golden.check(name, text)`: snapshots of the Bash output (presentation, wording, ordering details). | No |

Reference goldens are strict by default and under `KB_IMPL=bash`, so a Bash
change still fails. `just test-py` runs tests in parallel (`-n auto`); the
reference report is collected in one process, so pass `-n 0` and the
`tests/py` path (the option is defined in its conftest) with
`--reference-report`. With `--golden-mode=reference` (the default under
`KB_IMPL=python`), a mismatch is listed in the terminal summary, and
`--reference-report FILE` writes the diffs to a Markdown file for the
behavior audit.

A test that the behavior audit marks `xfail_bash` (`kbtest/marks.py`)
expects behavior bash does not have. Its contract and reference goldens
hold the expected output, written by hand, not a bash snapshot.
`--update-golden` leaves the goldens of an active `xfail` alone.

`just test-py-null` runs the null controls with reference goldens disabled.
A test it reports depends only on reference goldens: it needs a contract
golden or a semantic assertion before it can gate the port.

## Golden files

Golden files live under `golden/<module>/<test>/`. A run without
`--update-golden` never writes one, and a missing golden file is a failure.
Review every golden diff as part of the change that produced it.

## Normalization rules

`kb.norm()` applies these rules to output; `kb.norm_err()` applies them and
the stderr rules.

| Rule | Replacement |
|---|---|
| The test's content directory | `<CONTENT>` |
| The test's root directory | `<ROOT>` |
| The implementation's executables directory (`scripts/` or `python/`) | `<KB>/scripts` |
| The implementation's root (`KNOWLEDGE_BASE`) | `<KB>` |
| Observation file names, `YYYYMMDDTHHMMSS-<8 lowercase hex>.md` | `<OBS-n>.md`, numbered by first appearance. A name of that shape that breaks the format fails the test. |
| Batch IDs, `YYYYMMDDTHHMMSS-<pid>.tsv` | `<BATCH-n>.tsv`, numbered by first appearance |
| `created: <UTC timestamp>` lines | `created: <TIMESTAMP>` |
| `"timestamp":` values in session buffers, integer or float | `"timestamp":<EPOCH>` |
| Prefixes of 7 or more hex digits of any commit in the content repository | `<COMMIT-n>`, numbered by first appearance |
| stderr: lines starting `fatal:`, `error:`, `warning:`, or `hint:` (git) | `<git fatal>` and so on |
| stderr: lines starting `jq: ` | `<jq message>` |

Paths are replaced longest first.

`kbtest.normalize.report()` normalizes an `evaluate-retrieval` JSON report:
every value whose key contains `latency_ms` becomes `"<MS>"`, `measured_at` becomes
`"<TIMESTAMP>"`, and `latency_clock`, which names the implementation's clock
source, becomes `"<CLOCK>"`.

## Markers

| Marker | Meaning |
|---|---|
| `harness` | A self-test of the harness. It runs no implementation, and the null controls skip it. |
| `data` | A check of committed fixture data, such as retrieval fixtures. It runs no implementation, and the null controls skip it. |
| `null_ok("reason")` | The test passes under `null0` by design, such as a command whose contract is a silent exit 0. Reviewed in the behavior audit. |
| `audit("A-NNN")` | Pinned behavior that looks wrong or accidental; see `audit.md`. |

## Null controls

`just test-py-null` runs the suite under `null0` and `null1`. Every test must
fail under at least one. A test that passes under `null0` needs a `null_ok`
mark, and a `null_ok` mark on a test that fails under `null0` is reported as
stale. Under `KB_IMPL=python`, any stderr containing a Python traceback fails
the test, because an uncaught exception also exits 1.

## Benchmarks

`just bench [args]` runs `bench.py`. It copies a content tree (`--content
DIR`) or generates a synthetic one (`--scale N --seed S`, default 10× the
live knowledge base), times each read command and the two hook workloads
from `docs/python-port.md`, and prints a JSON report with p50 and p95 in
milliseconds. The source tree is never modified.

`kbtest/corpus.py` generates the synthetic tree. Its counts and size
quantiles were measured on the live knowledge base; the text is
pseudo-words, and a seed always produces the same bytes. Three marker words
appear in 50%, 5%, and 0.5% of articles, so searches have known hit rates.

`just bench-smoke` runs one pass against `null0` and is part of `just check`.
`just bench-startup` times Python start-up and the SessionEnd hook, cold
and warm, through the repo adapter and the dotfiles Claude shim.
Results for the Bash implementation are in `BASELINE.md`.

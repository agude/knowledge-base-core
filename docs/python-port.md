# Python port decision

Status: accepted, 2026-10-23. Work happens on the `python` branch.

## Decision

Replace the bash runtime (`scripts/`, about 7k lines of bash, awk, and jq)
with Python 3.11 or later, using the standard library only.

This reverses the standing constraint that the runtime and quality gate stay
independent of Python, and the earlier exclusion of "a broad shell-to-Python
rewrite" from the memory-system plan.

## Reasons

1. **Speed.** Retrieval and session start are slow on the live knowledge
   base (210 articles), measured 2026-10-23 as the mean of 5 runs:

   | Command | Bash |
   |---|---:|
   | `search --json python` | 4652 ms |
   | `search python` | 1764 ms |
   | `session-context` (mostly `status --brief` → `stale --count`) | 1262 ms |
   | `toc --map` | 125 ms |
   | `section --number 1` | 85 ms |

   Python start-up is 13 ms (`python3 -I -c pass`), 15 ms through the `sh`
   preamble. The slow commands spend their time spawning processes per file
   and per section, which in-process Python does not need.
2. **Portability.** The bash runtime depends on GNU and BSD variants of
   `date`, `stat`, `sort`, `readlink`, and awk, and on Bash 4, which macOS
   does not ship. `portability-lint` and the `doctor` probes exist only to
   manage those differences. Python removes that class of defect and makes
   Windows support possible.
3. **Maintainability.** `search` builds JSON and enforces byte budgets by
   hand, and ranking runs in embedded awk. Both are short, testable code in
   Python.
4. **Retrieval.** Ranking improvements (BM25, optional embeddings) are
   impractical in awk.

## Scope

- Minimum Python version: 3.11. Debian 12 ships 3.11 and Ubuntu 24.04 ships
  3.12. macOS ships 3.9 with the Command Line Tools, so macOS hosts need a
  separately installed interpreter (uv, Homebrew, or python.org).
- Runtime dependencies after the port: a Python 3.11+ interpreter and `git`,
  plus `pgrep` on Linux and macOS, where the base system ships it. Stale
  index-lock breaking uses it to keep a lock that a running git process
  holds; on Windows that check is age-only (audit A-003). `session-flush`
  logs dropped transcripts through the standard `syslog` module on Unix and
  not at all on Windows, so `logger` is no longer called (audit A-004).
- Test tooling: uv, pytest, ruff, hypothesis.
- Platforms: Linux and macOS are required at cutover. Windows follows after
  cutover. All platform-specific calls go through one module
  (`kb/platform.py`) from the first ported script, so Windows support does
  not require reworking ported code.
- Host registration stays outside this repository (README, "Host-specific
  registration remains outside `scripts/install`"). Hosts reach the
  executables by path, by symlink, or through shims, so no entry point can
  pass an interpreter argument. Each executable therefore selects its own
  interpreter: a POSIX `sh` preamble resolves its own symlinks, finds a
  3.11+ interpreter, and runs the script with it before any Python starts.
  Lookup order: the path recorded by `install` in
  `<repo>/.python-interpreter`; then `python3.20` down to `python3.11` in
  every `PATH` directory and in `/opt/homebrew/bin`, `/usr/local/bin`, and
  `~/.local/bin` (`KB_PYTHON_DIRS` replaces that list); then `python3` in the
  same places. Every `PATH` directory is checked, not just the first match,
  so a shim first on `PATH` does not hide a real interpreter after it.
  Version-manager shims (`*/shims/*`) are never candidates. Only the
  unversioned `python3` is probed by running it, so the common path starts
  one interpreter. The preamble is `kb/preamble.sh`; `kb/executables.py`
  generates every executable in `python/` from it.

## Spawn graph

Which bash executables start which siblings (plan item 3.8, measured at
`bash-frozen`). Python calls the same logic in-process through `kb`, so
each port unit must come after the units of everything it uses.

| Executable | Starts |
|---|---|
| `adapters/claude/session-start`, `adapters/codex/session-start` | `session-init`, `session-context` |
| `adapters/claude/session-prompt`, `-stop`; `adapters/codex/session-prompt`, `-stop` | `session-append` |
| `adapters/claude/session-end`, `adapters/codex/session-end` | `session-file`, `session-flush` |
| `session-init` | `session-flush` (orphan sweep) |
| `session-flush` | `observe` |
| `session-context` | `toc`, `status` |
| `context` | `toc` |
| `status` | `stale` |
| `hooks/pre-commit` | `lint` |
| `init` | `install` |
| `install` | links `hooks/pre-commit` and the Claude adapters; starts none |
| `evaluate-retrieval` | `search`, `section` (kept as subprocesses; see the plan's constraints) |
| `doctor` | none in Python: the capture smoke test calls `kb.session` in process; bash probes `search`, `session-append`, and `hooks/pre-commit` |
| every other executable | none |

## Cutover criteria

Measured on the live knowledge base and on a synthetic corpus ten times its
size, on CI hardware and on the slowest host that runs agent sessions.

- **Correctness.** The full characterization suite passes against Python on
  Linux and macOS, at Python 3.11 and the latest release.
- **Command speed.** At the 95th percentile, no command is slower than its
  bash baseline. `search`, `search --json`, and `session-context` each take
  at most 250 ms on the live knowledge base and 1 s on the 10× corpus.
- **Hook speed.** Defined workloads, each within 50% of the tightest host
  budget (Codex SessionEnd: 1 s default) at the 95th percentile:
  - SessionStart: `session-init` with no orphan buffers, plus
    `session-context`.
  - SessionEnd: flush of a 200-message buffer, producing one observation
    commit with the installed content-repo `pre-commit` hook running.
  The orphan sweep in `session-init` has no upper bound (one commit per
  orphan) and is interruptible by design. Its per-orphan cost is reported,
  not gated.
- **Retrieval quality.** `evaluate-retrieval` shows no regression against
  each committed baseline: `retrieval-v1`, `retrieval-question-v1`,
  `retrieval-question-comparison-v1`, and
  `retrieval-question-pre-change-v1`.
- **Dependencies.** No runtime dependency beyond the Python interpreter and
  `git`, except any the behavior audit explicitly allows.

## Claude hook shims

The dotfiles Claude hooks (`~/.dotfiles/llm/claude/hooks.d/*/010.knowledge.sh`)
re-implement the repo adapters instead of calling them, and have drifted:
the Stop and UserPromptSubmit shims pass the message through `$(...)`,
which drops trailing newlines, and hide append failures; SessionEnd builds
the buffer path itself. The in-process design needs one Python process per
hook, so at cutover (step 7) each shim body becomes a single line,

```bash
exec "$KNOWLEDGE_BASE/scripts/adapters/claude/<event>"
```

where `<event>` is `session-start`, `session-prompt`, `session-stop`, or
`session-end`. The repo adapters already carry both behaviors the shims
add: an empty message records nothing, and `KNOWLEDGE_SESSION_FILE` takes
precedence over the session ID. The switch is a change to the live
dotfiles, so it is made at cutover and verified there with one live Claude
session that captures and flushes (plan 4.8).

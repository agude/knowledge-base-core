# Behavior audit log

Behaviors pinned by the characterization suite that look wrong, accidental,
or platform-dependent. Each entry is decided in the behavior audit (step 2 of
the port plan). A test that pins an entry carries
`@pytest.mark.audit("A-NNN")`.

Classes: intended, bug, accidental (relied on), accidental (unused),
platform artifact, bash-only.

## A-001: observe's file-name comment disagrees with the code

Script: `observe`  Test: `test_smoke.py::test_observe_writes_and_commits`
Observed: the comment at `observe:93` says `YYYYMMDDTHHMMSS-<4 random
chars>.md`; the code writes 8 lowercase hex digits from 4 random bytes.
Expected: the comment matches the code.
Class: undecided
Decision:

## A-002: session-append writes two buffer formats

Script: `session-append`  Test: (1c.2)
Observed: with jq on `PATH`, DEL is escaped as `\u007f`, invalid UTF-8 is
replaced with U+FFFD, and the timestamp is a float. Without jq, DEL and
invalid bytes are written raw (not strict JSON) and the timestamp is an
integer.
Expected: unknown. Decide which format Python writes, and confirm that the
reader accepts both.
Class: undecided
Decision:

## A-003: stale index-lock breaking depends on pgrep

Script: `_lib.sh` (`break_stale_git_lock`, line 251)  Test: (1b.7)
Observed: a stale `.git/index.lock` is kept while `pgrep -f "git.*<repo>"`
finds a process. The standard library has no process listing on macOS.
Expected: unknown. Options: an age-only check, or `pgrep` as a Unix-only
dependency.
Class: undecided
Decision:

## A-004: session-flush writes to syslog

Script: `session-flush` (line 92)  Test: (1b.10)
Observed: dropping a short transcript runs `logger -t knowledge`.
Expected: unknown. Options: drop it, write to a log file, or keep syslog on
Unix only.
Class: undecided
Decision:

## A-005: output order follows the user's collation

Scripts: `toc`, `stale`, `pending`, `archive`, `questions`, `lint`
Test: (1d.4)
Observed: 12 `sort -z`/`sort -V` calls run without `LC_ALL=C`, so output
order depends on the locale. Python's `sorted()` uses code-point order.
Expected: one canonical order.
Class: undecided
Decision:

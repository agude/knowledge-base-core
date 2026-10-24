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
The help examples of `archive`, `questions`, and `resolve` use names such
as `20260412T000000-abcd.md`, which no command produces
(`test_help.py::test_help`).
Expected: the comment and help examples match the code.
Class: intended
Decision: the 8-hex-digit suffix is deliberate: the comment at `observe:95`
gives the reason (collision avoidance, `od` over `xxd`), and it replaced the
4-character form that older archived observations still carry. The line-93
comment and the help examples are stale text, not behavior. Python writes
8-hex-digit names, and its comments and help examples show them. Readers
accept any `*.md` name, including the old 4-character form. Bash is left
unchanged; `test_help.py` compares help text through reference goldens only,
so no test changes.

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
Test: `test_locale.py::test_order_follows_collation`
Observed: 12 `sort -z`/`sort -V` calls run without `LC_ALL=C`, so output
order depends on the locale. Python's `sorted()` uses code-point order.
Articles or observations named `B`, `_x`, `a-c`, `a`, `ab` list in that
order under C.UTF-8 and as `a`, `ab`, `a-c`, `B`, `_x` under en_US.UTF-8,
in both `toc` and `pending`. The full suite under
`KB_LOCALE=en_US.UTF-8` (2026-10-24, 953 tests, strict goldens) shows no
other golden difference: its file names are lowercase, date-stamped, and
order the same under both collations.
Expected: one canonical order.
Class: undecided
Decision:

## A-006: install reports removing skill links it recreates

Script: `install`  Test: `test_install.py::test_install_is_idempotent`
Observed: every re-run prints `Removed 2 prior skill symlink(s).`, because
it deletes every skill link into the repo and then recreates the same links.
Expected: unknown. A re-run with nothing to change may report nothing.
Class: undecided
Decision:

## A-007: skill link targets end in a slash

Script: `install`  Test: `test_install.py::test_install_fresh`
Observed: `~/.agents/skills/<name>` links to `<repo>/skills/<name>/`, with a
trailing slash, because the target comes from the glob `skills/*/`.
Expected: unknown. Hosts resolve both forms.
Class: undecided
Decision:

## A-008: init --path installs the hook into the wrong repository

Script: `init`  Test: `test_init.py::test_init_with_path`
Observed: `init --path DIR` creates and commits DIR, then runs `install`,
which links `pre-commit` into `$KB_CONTENT_DIR`, not DIR. DIR gets no
hook. `install`'s comment says "init calls this again after creating it",
which implies DIR was meant to get the hook.
Expected: DIR gets the `pre-commit` hook.
Class: undecided
Decision:

## A-009: commit fails on files outside the content areas

Script: `commit`  Test: `test_commit.py::test_commit_ignores_files_outside_content_areas`
Observed: `commit` decides there is work from `git status --porcelain` over
the whole repository but stages only `knowledge/`, `observations/`,
`questions/`, and `sources/`. An untracked file elsewhere makes it run
`git commit` with nothing staged: exit 1, git's status text on stdout, and
`locked_commit_index: commit failed (1)` on stderr. Git's status also lists
`.observe.lock/` as untracked; the content repository does not ignore it.
Expected: unknown. Probably "Nothing to commit." when nothing in the four
areas changed.
Class: undecided
Decision:

## A-010: a rejected commit leaves its paths staged

Script: `commit`  Test: `test_commit.py::test_commit_lint_failure`
Observed: when the pre-commit hook rejects the commit, the paths `commit`
staged stay in the index (`A  knowledge/bad.md`), although the hook prints
"nothing modified".
Expected: unknown.
Class: undecided
Decision:

## A-011: archive's header says it uses git mv

Script: `archive`  Test: `test_archive.py::test_archive_one`
Observed: the header says "Moves the file with git mv so history is
preserved"; the code rewrites the file and uses plain `mv`, and the
commit records an add and a delete (or a rename only when git detects
one).
Expected: the header matches the code.
Class: undecided
Decision:

## A-012: archive metadata placement depends on a `---` line

Script: `archive`  Test: `test_archive.py::test_archive_without_front_matter`
Observed: archive inserts `disposition:` and `original_sha256:` before the
first `---` line after line 1. An observation without front matter gets no
metadata. One without front matter whose body has a `---` thematic break
gets the metadata inserted into the body, before the break.
Expected: unknown. Probably add front matter, or leave such files
unchanged.
Class: undecided
Decision:

## A-013: questions --path matches string prefixes, not path segments

Script: `questions`  Test: `test_questions.py::test_questions_path_filter`
Observed: `--path knowledge/deploys` also lists a question whose context is
`knowledge/deploys-old/x.md`, because the filter is a plain string prefix.
Expected: unknown. Probably match whole path segments.
Class: undecided
Decision:

## A-014: ask and resolve drop text that looks like an echo option

Scripts: `ask` (`--body`), `resolve` (`--answer`)
Test: `test_questions.py::test_ask_body_that_looks_like_an_echo_option`
Observed: the text is written with `echo "$BODY"`, so a body of `-n` (or
`-e`, `-E`) is taken as an option and the file gets an empty body line.
Expected: the text is written verbatim.
Class: undecided
Decision:

## A-015: context ignores unknown arguments

Script: `context`  Test: `test_status_context.py::test_context_unknown_option`
Observed: `context --bogus` prints the normal report and exits 0. Every
other command rejects an unknown option with exit 1.
Expected: unknown. Probably exit 1 with `Unknown option: --bogus`.
Class: undecided
Decision:

## A-016: context's script list comes from the directory listing

Script: `context`  Test: `test_status_context.py::test_context_empty`
Observed: the `Scripts:` line lists every executable file in `scripts/`
except `_*`, `session-*`, `pretool-allow`, and `install`, in glob order. It
includes the development tool `portability-lint`, which retires with bash,
so the list changes at cutover.
Expected: unknown. Probably a fixed list of the agent-facing commands.
Class: undecided
Decision:

## A-017: a hashes-only heading becomes an empty section

Script: `toc` (and the shared heading parser)
Test: `test_fences.py::test_hashes_only_heading`
Observed: `## ##` is listed as section `1. ` with an empty name, and shifts
the numbering of the following sections. The bats test "a heading of only
hashes does not become a heading name" never included such a line.
Expected: unknown. CommonMark treats `## ##` as an empty H2; the bats test
name implies it should not be listed.
Class: undecided
Decision:

## A-018: toc and section do not validate numeric arguments

Scripts: `toc`, `section`
Tests: `test_toc.py::test_toc_argument_errors`, `test_section.py::test_section_number`
Observed: `toc --depth x` aborts with Bash's `x: unbound variable` (including
the script's absolute path) after printing a file header, exit 1. `toc
--depth 0` prints file headers with no headings, exit 0. `section --number
x` aborts with the same unbound-variable error.
Expected: reject a non-positive or non-numeric depth with a usage error.
Class: undecided
Decision:

## A-019: toc --dirs output depends on whether `tree` is installed

Script: `toc`  Test: `test_toc.py::test_toc_dirs`
Observed: with the `tree` utility on `PATH`, `--dirs` prints `tree`'s
box-drawing output with an absolute root, including empty directories.
Without it, a `find` fallback prints an indented list with a different
format.
Expected: one format on every host.
Class: undecided
Decision:

## A-020: pre-commit stamps through a symlinked article

Script: `hooks/pre-commit`  Test: `test_pre_commit.py::test_symlinked_article_stays_a_link`
Observed: for a staged `knowledge/link.md` that is a symlink to
`../real.md`, the hook keeps the symlink but rewrites `updated:` in the
target, a file outside `knowledge/`.
Expected: unknown. The hook may skip symlinked articles, or stamp only
targets inside `knowledge/`.
Class: undecided
Decision:

## A-021: adapters retry a failed append, so failures print twice

Scripts: `adapters/claude/session-{prompt,stop}`, `adapters/codex/session-{prompt,stop}`
Test: `test_adapters.py::test_buffer_creation_failure`
Observed: each adapter runs `session-append` a second time when the first
call fails, so one failure prints its error twice. The retry covers a
transient failure before the record is written; after the record is
written, a retry duplicates it (see the NOT_PORTED rows for
`adapters.bats`). The in-process Python design (plan 3.5) has no
subprocess to retry.
Expected: unknown. Decide whether the retry stays, and whether a failure
reports once.
Class: undecided
Decision:

## A-022: pending lists nested observations that batches never select

Script: `pending`  Test: `test_pending.py::test_nested_observations`
Observed: the listing, `--count`, and `--full` include files in
subdirectories of `observations/pending/`; `--preview` and `batch start`
consider only top-level files. A nested observation is counted as pending
but can never be curated through a batch. The bats test name ("keeps
recursive listing and bounds preview selection") suggests this is
deliberate.
Expected: unknown. Confirm, or make the two views agree.
Class: undecided
Decision:

## A-023: stale accepts a non-numeric --days

Script: `stale`  Test: `test_stale.py::test_stale_argument_errors`
Observed: `stale --days x` prints `No stale articles.` and exits 0, as if no
threshold applied. `KNOWLEDGE_LOCK_WAIT` and `--max-bytes` elsewhere reject
non-numbers.
Expected: a usage error, exit 1.
Class: undecided
Decision:

## A-024: stale's header says it groups by severity; it sorts by path

Script: `stale`  Test: `test_stale.py::test_stale_report`
Observed: the header says "Articles are grouped by staleness severity";
the report lists stale, undated, and badly dated articles together in path
order.
Expected: the header matches the output, or the output groups by severity.
Class: undecided
Decision:

## A-025: batch status measures input bytes from current files

Script: `batch status`  Test: `test_batch.py::test_batch_snapshot_complete_defer`
Observed: `Input bytes` and `Item sizes` read each member's current file,
pending or archived. Archiving adds metadata, so the reported size grows
after completion (a 73-byte observation reports 178 bytes once archived),
and the total no longer matches `Selected bytes` from `batch start`.
Expected: unknown. Probably sizes at selection.
Class: undecided
Decision:

## A-026: items over the remaining budget are reported as oversized

Scripts: `batch start`, `pending --preview`
Test: `test_batch.py::test_batch_excludes_arrivals`
Observed: an item excluded because earlier items used the budget is
reported as `Skipped oversized`, even when it alone fits (`z-excluded.md:78`
under `--max-bytes 78`). `batch status` labels the same set
`Oversized/deferred at creation`.
Expected: unknown. Distinguish "larger than the budget" from "did not fit
the remainder".
Class: undecided
Decision:

## A-027: lint reports a missing file as outside the content root

Script: `lint`  Test: `test_lint.py::test_lint_argument_errors`
Observed: `lint --file missing.md` prints `Path outside content root:
missing.md` and exits 1. The file does not exist; it is not outside the
root.
Expected: a not-found message, as `toc --path` and `stale --path` print.
Class: undecided
Decision:

## A-028: a malformed verified date is reported twice

Script: `lint`  Test: `test_lint.py::test_lint_structure` (case `bad-verified`)
Observed: `verified: last Tuesday` yields two errors: `verified is not a
YYYY-MM-DD date` and `section metadata invalid: invalid verification date`.
Expected: unknown. Probably one error.
Class: undecided
Decision:

## A-029: an ambiguous path lists matches in filesystem order

Script: `_lib.sh` (`resolve_path`), through `ask --context`, `toc`, and
`section`  Test: `test_lib.py::test_context_resolution` (case `ambiguous`)
Observed: `Ambiguous match for 'dup.md' — 2 files found:` lists matches in
the order `find` returns them, which depends on the filesystem, then also
prints `Not found: dup.md`.
Expected: sorted matches and one message.
Class: undecided
Decision:

## A-030: an option takes the next word even when it is another option

Scripts: every script using `need_arg`
Test: `test_lib.py::test_option_arguments`
Observed: `need_arg` checks only that a word follows, so `observe --title
--body B` sets the title to `--body` and then rejects `B` as an unknown
option; `observe --title --no-commit` sets the title to `--no-commit`.
Expected: unknown. Values that begin with `--` are legitimate for `--body`
and `--answer`.
Class: undecided
Decision:

## A-032: session-flush with no buffer argument exits 0 silently

Script: `session-flush`  Test: `test_session_core.py::test_flush_without_argument`
Observed: `session-flush` with no arguments prints nothing and exits 0, the
same as for a buffer that does not exist. Other commands reject a missing
required argument with a usage error.
Expected: unknown. A missing argument is a caller bug; a missing buffer is
a normal race with the orphan sweep.
Class: undecided
Decision:

## A-033: search and section JSON has irregular whitespace

Scripts: `search`, `section` (`--json`)
Test: `test_search.py::test_match_in_article`
Observed: the JSON is assembled by hand. Most of it is compact, but some
objects carry spaces (`"field_scopes":{ "status":"article" }`). Byte budgets
(`--max-bytes`) count these exact bytes, so the goldens pin them.
Expected: unknown. Probably compact JSON throughout; budgets then shift by
the removed bytes.
Class: undecided
Decision:

## A-034: some entry points do not parse options

Scripts: `hooks/pre-commit`, `session-context`, `session-flush`, `context`,
and the Claude and Codex adapters  Test: `test_help.py`
Observed: `--help` and unknown options are ignored: the hooks run as if
invoked by their host, `session-context` and `context` print the context,
and `session-flush` takes `--help` as the buffer path and exits 0 because
no such buffer exists. Every other command prints help or rejects the
option.
Expected: unknown. Hook entry points need not parse options; `session-flush`
and `context` probably should.
Class: undecided
Decision:

## A-035: a missing knowledge directory is an error for some commands only

Scripts: `toc`, `stale`, `lint` versus `search`, `pending`, `status`
Test: `test_edge_input.py::test_edge` (case `empty`)
Observed: with no `knowledge/` directory, `toc`, `stale`, and `lint` exit 1
with `Not found: <content>/knowledge`; `search`, `pending`, `status`,
`context`, and `session-context` treat it as empty and exit 0.
Expected: one behavior. An empty knowledge base is a normal state after
`init`.
Class: undecided
Decision:

## A-036: one unreadable article breaks or garbles reading commands

Scripts: `search`, `toc`, `context`, `lint`
Test: `test_edge_input.py::test_edge` (case `unreadable`)
Observed: with one article at mode 000, `search` fails as a whole (`Search
failed while reading the selected corpus`, exit 1) and returns none of the
readable matches; `toc`, `context`, and `lint` print raw Bash errors with
script line numbers (`scripts/toc: line 168: ...: Permission denied`).
Expected: unknown. Probably skip the file with one clear warning.
Class: undecided
Decision:

## A-037: a lock directory without a pid file is never broken

Script: `_lib.sh` (`acquire_lock`)  Test: `test_concurrency.py::test_lock_without_pid_is_never_broken`
Observed: a stale lock is broken only when its `pid` file names a dead
process. A writer killed between `mkdir` and writing its pid leaves
`.observe.lock/` with no pid file; every later writer waits
`KNOWLEDGE_LOCK_WAIT` seconds and fails, until someone removes the
directory by hand.
Expected: unknown. Probably break a pid-less lock older than a bound.
Class: undecided
Decision:

## A-038: lock waits poll once a second

Script: `_lib.sh` (`acquire_lock`)  Test: `test_concurrency.py::test_concurrent_observe_loses_nothing`
Observed: a writer that finds the lock held sleeps a whole second before
retrying, so five concurrent `observe` calls take about four seconds,
almost all of it waiting.
Expected: unknown. A shorter retry interval keeps the same safety.
Class: undecided
Decision:

## A-039: observe and ask outside a git repository write, then fail

Scripts: `observe`, `ask`  Test: `test_git.py::test_content_dir_is_not_a_repository`
Observed: with `KB_CONTENT_DIR` pointing at a directory that is not a git
repository, both write their file, then the commit fails: exit 128 (git's
code) with git's own `fatal:` message. The file stays. `commit` and `sync`
check first and exit 1 with `Not a git repository`.
Expected: unknown. Probably check first, like `commit`, or keep the file
and exit 1 with one clear message.
Class: undecided
Decision:

## A-040: the Claude session-end hook prints observe's output

Script: `adapters/claude/session-end`  Test: `test_hook_contracts.py::test_hook_protocol`
Observed: when the flush writes an observation, the hook's stdout carries
`Wrote: observations/pending/<name>.md`, passed through from `observe`.
Claude does not read SessionEnd stdout. The Codex session-end hook
discards the same output and prints only `{}`.
Expected: unknown. Probably print nothing.
Class: undecided
Decision:

## A-041: breaking a stale lock can delete a live owner's lock

Script: `_lib.sh` (`acquire_lock`; every writer)
Test: `test_concurrency.py::test_stale_lock_race_loses_nothing`,
`test_concurrency.py::test_concurrent_observe_loses_nothing`
Observed: a waiter reads the owner's pid from `.observe.lock/pid`, then
checks it with `kill -0`, then runs `rm -rf .observe.lock`. When the owner
exits between the read and the check and a second waiter takes the lock in
that window, the first waiter deletes the second waiter's live lock. Two
writers then run git together: one fails with `fatal: Unable to create
'.git/index.lock'` (exit 128), or `echo $$ > pidfile` fails with `No such
file or directory` and the writer proceeds without a lock. With a stale
lock and 8 concurrent `observe` runs, 14 of 40 runs failed (2026-10-24).
Without a stale lock it needs load: 1 failure in the 20 five-writer runs of
one full parallel suite run, 0 in 200 runs alone. Both tests are non-strict
`xfail` under bash.
Expected: every writer commits; a lock is broken only if it still holds
the pid that was found dead (for example, rename the lock away atomically
and recheck).
Class: undecided
Decision:

## Coverage note (plan item 1b.11)

kcov is not installed on the development host or in CI, so no line-coverage
report of the Bash scripts under the pytest suite exists. Uncovered branches
were looked for by hand through `SURFACE.md` instead. kcov cannot see inside
the embedded awk and jq programs in any case, so no "dead code" claim is
made from coverage.

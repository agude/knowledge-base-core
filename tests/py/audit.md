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

Script: `session-append`
Test: `test_shared_state.py::test_buffer_bytes`,
`test_shared_state.py::test_buffer_round_trips_through_flush`,
`test_mixed.py::test_jq_free_buffer_is_flushed_intact`
Observed: with jq on `PATH`, DEL is escaped as `\u007f`, invalid UTF-8 is
replaced with U+FFFD, and the timestamp is a float. Without jq, DEL and
invalid bytes are written raw (not strict JSON) and the timestamp is an
integer.
Expected: one format, the jq one, in every configuration.
Class: platform artifact
Decision: Python writes the jq format whether or not jq is installed:
strict JSON, `\u007f` for DEL, U+FFFD for invalid UTF-8, and a float
timestamp. Both configurations of `test_buffer_bytes` now compare against
one contract golden (`golden/test_shared_state/buffer_format`), and the
no-jq case is a strict `xfail` under bash. The reader accepts both formats,
because buffers written by bash without jq survive an upgrade: the
round-trip and mixed tests pin that a raw-byte buffer flushes without losing
its messages. Bash is not changed.

## A-003: stale index-lock breaking depends on pgrep

Script: `_lib.sh` (`break_stale_git_lock`, line 251)
Test: `test_git.py::test_stale_index_lock_is_removed`,
`test_git.py::test_index_lock_kept_while_git_runs`
Observed: a stale `.git/index.lock` is kept while `pgrep -f "git.*<repo>"`
finds a process. The standard library has no process listing on macOS.
Expected: as observed on Linux and macOS.
Class: intended
Decision: the function comment names both checks (age and a running git
process), and the process check is the only guard against removing the lock
of a git command the user or an editor is running in the content
repository, which `.observe.lock` does not serialize. Python keeps it:
`kb/platform.py` runs `pgrep -f` on Linux and macOS, where it ships with the
base system, and falls back to the age check alone on Windows. `pgrep`
becomes a declared Unix runtime dependency in `docs/python-port.md`. Audit
marks removed.

## A-004: session-flush writes to syslog

Script: `session-flush` (line 92)
Test: `test_session_flow.py::test_session_end_drops_one_exchange`,
`test_session_core.py::test_flush_threshold`,
`test_session_core.py::test_flush_without_jq`
Observed: dropping a short transcript runs `logger -t knowledge`.
Expected: the drop is logged to syslog under the tag `knowledge`; the
mechanism is free.
Class: intended
Decision: commit 7ec353a added the line with the threshold, as the only
trace of a dropped transcript, best-effort (`|| true`). Nothing in this
repository, the pi adapter, the skills, or the knowledge base reads it.
Python sends the same message, with the same tag, through the standard
`syslog` module on Linux and macOS, and logs nothing on Windows; it never
runs `logger`. The harness observes `logger` through a stub, which cannot
see `syslog(3)`, so the three `syslog` goldens moved from contract to
reference.

## A-005: output order follows the user's collation

Scripts: `toc`, `stale`, `pending`, `archive`, `questions`, `lint`
Test: `test_locale.py::test_order_is_code_point`
Observed: 12 `sort -z`/`sort -V` calls run without `LC_ALL=C`, so output
order depends on the locale. Python's `sorted()` uses code-point order.
Articles or observations named `B`, `_x`, `a-c`, `a`, `ab` list in that
order under C.UTF-8 and as `a`, `ab`, `a-c`, `B`, `_x` under en_US.UTF-8,
in both `toc` and `pending`. The full suite under
`KB_LOCALE=en_US.UTF-8` (2026-10-24, 953 tests, strict goldens) shows no
other golden difference: its file names are lowercase, date-stamped, and
order the same under both collations.
Expected: one canonical order.
Class: platform artifact
Decision: file lists are in code-point order of their paths under every
locale, the order C.UTF-8 gives today and Python's `sorted()` gives on
`str`. `test_order_is_code_point` asserts it for `toc` and `pending` under
both locales; the en_US case is a strict `xfail` under bash. The two
`sort -V` calls in `stale` and `lint` order section locators numerically,
which is not collation, and Python keeps that version order. Bash is not
changed, although the difference is live: dirac runs agent sessions under
`LANG=en_US.UTF-8`, and kebab-case article names that share a prefix
(`home-x.md`, `home.md`, `homey.md`) list in a different order there. Only
listing order changes; no reader depends on it.

## A-006: install reports removing skill links it recreates

Script: `install`  Test: `test_install.py::test_install_is_idempotent`
Observed: every re-run prints `Removed 2 prior skill symlink(s).`, because
it deletes every skill link into the repo and then recreates the same links.
Expected: a re-run with nothing to change may report nothing.
Class: accidental (unused)
Decision: the message is a side effect of remove-then-recreate, and
nothing reads install's stdout. `test_install_is_idempotent` already
compares stdout through a reference golden and the links through a
contract, so Python may print only what changed. Audit mark removed.

## A-007: skill link targets end in a slash

Script: `install`  Test: `test_install.py::test_install_fresh`
Observed: `~/.agents/skills/<name>` links to `<repo>/skills/<name>/`, with a
trailing slash, because the target comes from the glob `skills/*/`.
Expected: either form; hosts resolve both.
Class: accidental (unused)
Decision: the slash comes from the `skills/*/` glob. The links contract in
`test_install.py` now strips a trailing slash from link targets, so both
forms pass; Python writes the target without one. Audit mark removed.

## A-008: init --path installs the hook into the wrong repository

Script: `init`  Test: `test_init.py::test_init_with_path`
Observed: `init --path DIR` creates and commits DIR, then runs `install`,
which links `pre-commit` into `$KB_CONTENT_DIR`, not DIR. DIR gets no
hook. `install`'s comment says "init calls this again after creating it",
which implies DIR was meant to get the hook.
Expected: DIR gets the `pre-commit` hook; `$KB_CONTENT_DIR` is untouched.
Class: bug
Decision: the three `init --path` tests now expect the hook in DIR and no
hook in the configured repository, and are strict `xfail` under bash. The
unhooked repository only loses `updated:` stamping and lint until `install`
runs with `KB_CONTENT_DIR` set to it, so bash is not fixed.

## A-009: commit fails on files outside the content areas

Script: `commit`  Test: `test_commit.py::test_commit_ignores_files_outside_content_areas`
Observed: `commit` decides there is work from `git status --porcelain` over
the whole repository but stages only `knowledge/`, `observations/`,
`questions/`, and `sources/`. An untracked file elsewhere makes it run
`git commit` with nothing staged: exit 1, git's status text on stdout, and
`locked_commit_index: commit failed (1)` on stderr. Git's status also lists
`.observe.lock/` as untracked; the content repository does not ignore it.
Expected: "Nothing to commit." and exit 0 when nothing in the four areas
changed; the loose file stays untracked.
Class: bug
Decision: the header says commit stages the four areas, so a change
elsewhere is not its work. The test now expects the clean-tree outcome and
is a strict `xfail` under bash. Python decides from the status of the four
areas only, so `.observe.lock/` showing as untracked does not matter to it.
A failed curation commit is recoverable by hand, so bash is not fixed.

## A-010: a rejected commit leaves its paths staged

Script: `commit`  Test: `test_commit.py::test_commit_lint_failure`
Observed: when the pre-commit hook rejects the commit, the paths `commit`
staged stay in the index (`A  knowledge/bad.md`), although the hook prints
"nothing modified".
Expected: as observed.
Class: intended
Decision: git itself leaves the index as it was when a pre-commit hook
rejects a commit, and the hook's "nothing modified" refers to the working
tree, which it does not change. A rerun after the fix stages again. The
status contract stays; audit mark removed.

## A-011: archive's header says it uses git mv

Script: `archive`  Test: `test_archive.py::test_archive_one`
Observed: the header says "Moves the file with git mv so history is
preserved"; the code rewrites the file and uses plain `mv`, and the
commit records an add and a delete (or a rename only when git detects
one).
Expected: the header matches the code.
Class: intended
Decision: archive must rewrite the file to add its metadata, so a
byte-preserving `git mv` cannot apply; git records a rename when the
similarity is high enough. Only the header text is stale. Python's header
describes the rewrite. Bash is left unchanged; audit mark removed.

## A-012: archive metadata placement depends on a `---` line

Script: `archive`  Test: `test_archive.py::test_archive_without_front_matter`
Observed: archive inserts `disposition:` and `original_sha256:` before the
first `---` line after line 1. An observation without front matter gets no
metadata. One without front matter whose body has a `---` thematic break
gets the metadata inserted into the body, before the break.
Expected: an observation without front matter gets a new front-matter
block holding only `disposition:` and `original_sha256:`, then a blank line
and the original bytes unchanged.
Class: bug
Decision: `search` and `section` read `disposition` from archived front
matter as provenance, so a missing block loses it and a block inserted into
the body corrupts the observation. The contract goldens for both files now
hold the expected output; the test is a strict `xfail` under bash. Pending
observations come from `observe` and `session-flush`, which always write
front matter, so bash is not fixed.

## A-013: questions --path matches string prefixes, not path segments

Script: `questions`  Test: `test_questions.py::test_questions_path_filter`
Observed: `--path knowledge/deploys` also lists a question whose context is
`knowledge/deploys-old/x.md`, because the filter is a plain string prefix.
Expected: a context matches when it equals the filter or lies under it as
a directory (`knowledge/deploys/...`), not when it merely starts with the
same characters.
Class: bug
Decision: the help says "whose context falls under PATH", which is
containment. The test now asserts the sibling is not listed and is a strict
`xfail` under bash. The extra match only adds a question to a listing, so
bash is not fixed.

## A-014: ask and resolve drop text that looks like an echo option

Scripts: `ask` (`--body`), `resolve` (`--answer`)
Test: `test_questions.py::test_ask_body_that_looks_like_an_echo_option`,
`test_questions.py::test_resolve_answer_that_looks_like_an_echo_option`
Observed: the text is written with `echo "$BODY"`, so a body of `-n` (or
`-e`, `-E`) is taken as an option and the file gets an empty body line.
Expected: the text is written verbatim.
Class: bug
Decision: text the user passed is lost. The `ask` contract golden now holds
`-n` as the body, a new `resolve` test expects `-n` as the answer, and both
are strict `xfail` under bash. Only bodies that are exactly an echo option
are affected, so bash is not fixed.

## A-015: context ignores unknown arguments

Script: `context`  Test: `test_status_context.py::test_context_unknown_option`
Observed: `context --bogus` prints the normal report and exits 0. Every
other command rejects an unknown option with exit 1.
Expected: exit 1, no stdout, and `Unknown option: --bogus` on stderr.
Class: bug
Decision: every other command rejects unknown options, and no caller passes
`context` arguments. The test now expects the rejection and is a strict
`xfail` under bash; its goldens are removed. Harmless in practice, so bash
is not fixed.

## A-016: context's script list comes from the directory listing

Script: `context`  Test: `test_status_context.py::test_context_empty`
Observed: the `Scripts:` line lists every executable file in `scripts/`
except `_*`, `session-*`, `pretool-allow`, and `install`, in glob order. It
includes the development tool `portability-lint`, which retires with bash,
so the list changes at cutover.
Expected: a fixed list of the agent-facing commands.
Class: accidental (unused)
Decision: the line is generated from the directory only because that was
easy in shell. Python prints a fixed alphabetical list: `archive`, `ask`,
`batch`, `commit`, `context`, `doctor`, `evaluate-retrieval`, `init`,
`lint`, `observe`, `pending`, `questions`, `resolve`, `search`, `section`,
`stale`, `status`, `sync`, `toc`; `portability-lint` is dropped. The line is
compared only through reference goldens, so no test changes; audit mark
removed.

## A-017: a hashes-only heading becomes an empty section

Script: `toc` (and the shared heading parser)
Test: `test_fences.py::test_hashes_only_heading`
Observed: `## ##` is listed as section `1. ` with an empty name, and shifts
the numbering of the following sections. The bats test "a heading of only
hashes does not become a heading name" never included such a line.
Expected: a heading with an empty name is not a section: it is not listed
and does not shift the numbering; its lines belong to the section above.
Class: bug
Decision: the bats test name states the intent; its fixture lost the
`## ##` line. The facts contract now lists only `1. Real Section`, and the
test is a strict `xfail` under bash. Python's shared heading parser applies
the same rule to `section`, `search`, and `lint`, so numbering agrees
across commands. The heading is malformed input, so bash is not fixed.

## A-018: toc and section do not validate numeric arguments

Scripts: `toc`, `section`
Tests: `test_toc.py::test_toc_argument_errors`, `test_section.py::test_section_number`
Observed: `toc --depth x` aborts with Bash's `x: unbound variable` (including
the script's absolute path) after printing a file header, exit 1. `toc
--depth 0` prints file headers with no headings, exit 0. `section --number
x` aborts with the same unbound-variable error.
Expected: reject a non-positive or non-numeric depth with a usage error.
Class: bug
Decision: `toc --depth x`, `toc --depth 0`, and `section --number x` now
expect exit 1 with no output and no `unbound variable` message; the three
cases are strict `xfail` under bash. Only agent typos reach these paths, and
bash already exits nonzero for two of them, so bash is not fixed.

## A-019: toc --dirs output depends on whether `tree` is installed

Script: `toc`  Test: `test_toc.py::test_toc_dirs`
Observed: with the `tree` utility on `PATH`, `--dirs` prints `tree`'s
box-drawing output with an absolute root, including empty directories.
Without it, a `find` fallback prints an indented list with a different
format.
Expected: one format on every host.
Class: platform artifact
Decision: the `find` fallback's format: relative names, two-space indent,
`/` after directories, empty directories included. It needs no external
tool. Both renderer cases compare stdout, stderr, and exit code against one
contract (`golden/test_toc/toc_dirs`), and the `tree` case is a strict
`xfail` under bash. Bash is not changed.

## A-020: pre-commit stamps through a symlinked article

Script: `hooks/pre-commit`  Test: `test_pre_commit.py::test_symlinked_article_stays_a_link`
Observed: for a staged `knowledge/link.md` that is a symlink to
`../real.md`, the hook keeps the symlink but rewrites `updated:` in the
target, a file outside `knowledge/`.
Expected: as observed.
Class: intended
Decision: commit bf879fe ("Fix five ways the pre-commit hook damaged
files") writes the stamp back through the existing inode on purpose, so a
symlinked article stays a link and keeps its mode. The stamp belongs to the
article's content wherever it lives. Python writes through the link the
same way. Contract goldens stay; audit mark removed.

## A-021: adapters retry a failed append, so failures print twice

Scripts: `adapters/claude/session-{prompt,stop}`, `adapters/codex/session-{prompt,stop}`
Test: `test_adapters.py::test_buffer_creation_failure`
Observed: each adapter runs `session-append` a second time when the first
call fails, so one failure prints its error twice. The retry covers a
transient failure before the record is written; after the record is
written, a retry duplicates it (see the NOT_PORTED rows for
`adapters.bats`). The in-process Python design (plan 3.5) has no
subprocess to retry.
Expected: one append attempt; a failure reports once.
Class: bash-only
Decision: the retry exists because the bash adapters call `session-append`
as a subprocess. The Python adapters append in-process (plan 3.5), so there
is nothing to retry and no duplicate record after a late failure. The test
compares the messages through a reference golden and asserts only the exit
code, a nonempty stderr, and the stdout protocol, so it already allows one
report; audit mark removed. The four `adapters.bats` retry rows in
`NOT_PORTED.md` are confirmed in 2.3.

## A-022: pending lists nested observations that batches never select

Script: `pending`  Test: `test_pending.py::test_nested_observations`
Observed: the listing, `--count`, and `--full` include files in
subdirectories of `observations/pending/`; `--preview` and `batch start`
consider only top-level files. A nested observation is counted as pending
but can never be curated through a batch. The bats test name ("keeps
recursive listing and bounds preview selection") suggests this is
deliberate.
Expected: as observed.
Class: intended
Decision: commit 6484f37 ("Preserve pending file discovery") restored the
recursive listing and count on purpose and limited only preview selection
to top-level files, to match `batch start`. Python keeps both halves. Tests
unchanged; audit mark removed.

## A-023: stale accepts a non-numeric --days

Script: `stale`  Test: `test_stale.py::test_stale_argument_errors`
Observed: `stale --days x` prints `No stale articles.` and exits 0, as if no
threshold applied. `KNOWLEDGE_LOCK_WAIT` and `--max-bytes` elsewhere reject
non-numbers.
Expected: a usage error, exit 1.
Class: bug
Decision: a typo silently disables the threshold. The case now expects
exit 1 and no report, and is a strict `xfail` under bash. `--days 0`
stays valid (`test_stale_days`). Bash is not fixed.

## A-024: stale's header says it groups by severity; it sorts by path

Script: `stale`  Test: `test_stale.py::test_stale_report`
Observed: the header says "Articles are grouped by staleness severity";
the report lists stale, undated, and badly dated articles together in path
order.
Expected: the header matches the output.
Class: intended
Decision: path order is the pinned report contract and what readers of
`stale` see today; only the header text is stale. Python's header
describes path order. Tests unchanged; audit mark removed.

## A-025: batch status measures input bytes from current files

Script: `batch status`  Test: `test_batch.py::test_batch_snapshot_complete_defer`
Observed: `Input bytes` and `Item sizes` read each member's current file,
pending or archived. Archiving adds metadata, so the reported size grows
after completion (a 73-byte observation reports 178 bytes once archived),
and the total no longer matches `Selected bytes` from `batch start`.
Expected: either; nothing reads the figure.
Class: accidental (unused)
Decision: the manifest records no sizes, so current files are the only
source, and `batch status` already prints `Selected bytes at creation` from
the batch metadata. Adding a size column would change the manifest that
both implementations read during the trial. Python measures current files
as bash does. The lines are compared only through reference goldens; audit
mark removed.

## A-026: items over the remaining budget are reported as oversized

Scripts: `batch start`, `pending --preview`
Test: `test_batch.py::test_batch_excludes_arrivals`
Observed: an item excluded because earlier items used the budget is
reported as `Skipped oversized`, even when it alone fits (`z-excluded.md:78`
under `--max-bytes 78`). `batch status` labels the same set
`Oversized/deferred at creation`.
Expected: the text distinguishes "larger than the budget" from "did not
fit the remainder".
Class: accidental (unused)
Decision: the label is report wording that nothing parses. Python prints
`Skipped oversized` only for an item larger than the whole budget and
`Skipped, over remaining budget` for the rest. The batch metadata keys
`oversized_count` and `oversized_item` keep holding both kinds, so a batch
started by either implementation reads the same. The labels are compared
only through reference goldens, so no test changes.

## A-027: lint reports a missing file as outside the content root

Script: `lint`  Test: `test_lint.py::test_lint_argument_errors`
Observed: `lint --file missing.md` prints `Path outside content root:
missing.md` and exits 1. The file does not exist; it is not outside the
root.
Expected: a not-found message, as `toc --path` and `stale --path` print.
Class: bug
Decision: the message names the wrong cause. The case now asserts that
stderr names the file and does not say "outside"; it is a strict `xfail`
under bash. The exit code is already right, so bash is not fixed.

## A-028: a malformed verified date is reported twice

Script: `lint`  Test: `test_lint.py::test_lint_structure` (case `bad-verified`)
Observed: `verified: last Tuesday` yields two errors: `verified is not a
YYYY-MM-DD date` and `section metadata invalid: invalid verification date`.
Expected: one error per malformed date.
Class: bug
Decision: the second message comes from the section-metadata parser
re-reporting the same field, and the doubled count misstates the summary.
The `bad-verified` case's lint contract now expects one error; it is a
strict `xfail` under bash. Only the count is wrong, so bash is not fixed.

## A-029: an ambiguous path lists matches in filesystem order

Script: `_lib.sh` (`resolve_path`), through `ask --context`, `toc`, and
`section`  Test: `test_lib.py::test_context_resolution` (case `ambiguous`)
Observed: `Ambiguous match for 'dup.md' — 2 files found:` lists matches in
the order `find` returns them, which depends on the filesystem, then also
prints `Not found: dup.md`.
Expected: sorted matches and one message.
Class: accidental (unused)
Decision: the message is for a person or agent to read; no caller parses
it, and the exit code and the absence of a question file are the contract.
Python prints the matches in code-point order (A-005) and omits the
trailing `Not found:` line. The test already sorts the match lines and
compares stderr through a reference golden; audit mark removed.

## A-030: an option takes the next word even when it is another option

Scripts: every script using `need_arg`
Test: `test_lib.py::test_option_arguments`
Observed: `need_arg` checks only that a word follows, so `observe --title
--body B` sets the title to `--body` and then rejects `B` as an unknown
option; `observe --title --no-commit` sets the title to `--no-commit`.
Expected: as observed: an option's value is the next word, whatever it
starts with.
Class: intended
Decision: one simple rule that lets text values begin with dashes
(`--body "--flag explained"`, `--answer -`). Python's option parsing
follows it rather than `argparse`'s, which rejects values that look like
options. A mistyped command still fails, as `flag-as-value` shows, because
the displaced value is then an unknown option. Tests unchanged; audit mark
removed.

## A-031: a signal to session-flush alone waits for its child

Script: `session-flush`
Test: `test_session_core.py::test_flush_signal_to_process_only`
Observed: SIGTERM sent to the `session-flush` process only, not its process
group, while its `observe` child waits for a held lock, takes effect only
when the child gives up (`KNOWLEDGE_LOCK_WAIT`, 3 s in the test). Bash runs
a trap only after the foreground child exits. The flush then exits 130,
prints `session-flush: interrupted, keeping <buffer>`, and keeps the buffer.
(Entry written in step 2; commit 3b1244d named it but did not add it.)
Expected: the outcome as observed; when the signal takes effect is free.
Class: bash-only
Decision: the delay is how Bash defers traps, not a designed behavior.
Python acts on the signal when it arrives. The test keeps the exit-code
contract and the kept-buffer and no-observation assertions, and drops the
`deferred` contract golden; audit mark removed.

## A-032: session-flush with no buffer argument exits 0 silently

Script: `session-flush`  Test: `test_session_core.py::test_flush_without_argument`
Observed: `session-flush` with no arguments prints nothing and exits 0, the
same as for a buffer that does not exist. Other commands reject a missing
required argument with a usage error.
Expected: a missing argument is a usage error (exit 1, usage on stderr); a
missing buffer stays a silent exit 0, because it is a normal race with the
orphan sweep.
Class: bug
Decision: every caller (the adapters and the orphan sweep) passes a path,
so a missing argument is a caller bug that should be visible. The test now
expects exit 1 and a message, is a strict `xfail` under bash, and loses its
`null_ok` mark. The missing-buffer case is unchanged. Bash is not fixed.

## A-033: search and section JSON has irregular whitespace

Scripts: `search`, `section` (`--json`)
Test: `test_search.py::test_match_in_article`
Observed: the JSON is assembled by hand. Most of it is compact, but some
objects carry spaces (`"field_scopes":{ "status":"article" }`). Byte budgets
(`--max-bytes`) count these exact bytes, so the goldens pin them.
Expected: compact JSON throughout.
Class: accidental (unused)
Decision: the spaces come from hand assembly; every consumer parses the
JSON. The search and section tests compare JSON by parsed value and check
`--max-bytes` as an invariant on the bytes actually printed, and the byte
transcripts are reference goldens, so no test pins the spaces. Python
writes compact JSON (`separators=(",", ":")`), and its budgets count its
own bytes. Audit mark removed.

## A-034: some entry points do not parse options

Scripts: `hooks/pre-commit`, `session-context`, `session-flush`, `context`,
and the Claude and Codex adapters  Test: `test_help.py`
Observed: `--help` and unknown options are ignored: the hooks run as if
invoked by their host, `session-context` prints the context, `context`
prints help for `--help` but the normal report for an unknown option,
and `session-flush` takes `--help` as the buffer path and exits 0 because
no such buffer exists. Every other command prints help or rejects the
option.
Expected: host entry points ignore options; `context` and `session-flush`
print help for `--help` and reject unknown options with exit 1.
Class: intended (host entry points); bug (`context`, `session-flush`)
Decision: hosts and git invoke the hooks, the adapters, and
`session-context` without options, and ignoring arguments keeps them from
failing on an unexpected one; Python keeps that, and those cases keep their
`null_ok` marks. `context` and `session-flush` are commands a person or the
curator runs, and every other such command parses options (see A-015 and
A-032). Their `test_unknown_option` cases and `session-flush`'s `test_help`
case now expect a rejection or help, with hand-written goldens, and are
strict `xfail` under bash. Bash is not fixed.

## A-035: a missing knowledge directory is an error for some commands only

Scripts: `toc`, `stale`, `lint` versus `search`, `pending`, `status`
Test: `test_edge_input.py::test_edge` (case `empty`)
Observed: with no `knowledge/` directory, `toc`, `stale`, and `lint` exit 1
with `Not found: <content>/knowledge`; `search`, `pending`, `status`,
`context`, and `session-context` treat it as empty and exit 0.
Expected: a missing `knowledge/` is an empty knowledge base for every
command.
Class: bug
Decision: `init` creates the directory, but a fresh clone of a content
repository with no articles has no `knowledge/` (git does not track empty
directories without a `.gitkeep`), and five of eight commands already treat
it as empty. The `empty` cases of `toc`, `stale`, and `lint` now expect
exactly the output bash gives for an empty `knowledge/` directory (exit 0),
and are strict `xfail` under bash. Bash is not fixed.

## A-036: one unreadable article breaks or garbles reading commands

Scripts: `search`, `toc`, `context`, `lint`
Test: `test_edge_input.py::test_edge` (case `unreadable`)
Observed: with one article at mode 000, `search` fails as a whole (`Search
failed while reading the selected corpus`, exit 1) and returns none of the
readable matches; `toc`, `context`, and `lint` print raw Bash errors with
script line numbers (`scripts/toc: line 168: ...: Permission denied`).
Expected: every reading command skips the unreadable article, names it
once on stderr, and processes the rest; `lint` also counts it as an error
and exits 1. No command prints a shell or awk diagnostic.
Class: bug
Decision: one bad file must not hide the readable ones, and `stale` must
not report an article it could not read as undated. `test_edge` now asserts
that no case prints a shell diagnostic, and for the `unreadable` case of
`search`, `toc`, `stale`, `context`, and `lint` it asserts the rule above in
place of goldens (whose expected bytes no implementation has produced
yet). Those five cases are strict `xfail` under bash. Bash is not fixed:
articles are written by the curator and are readable in practice.

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

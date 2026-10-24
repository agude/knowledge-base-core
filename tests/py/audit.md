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

## A-018: toc does not validate --depth

Script: `toc`  Test: `test_toc.py::test_toc_argument_errors`
Observed: `--depth x` aborts with Bash's `x: unbound variable` (including the
script's absolute path) after printing a file header, exit 1. `--depth 0`
prints file headers with no headings, exit 0.
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

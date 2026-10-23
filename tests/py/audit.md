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

# knowledge-base

`kb` lets LLM agent sessions read and search a knowledge base: curated
articles and source documents, and the observations and questions behind them.
`recall`, `read`, `map`, `questions`, and `evidence` are read-only. `kb observe`
records an observation, `kb gap` records an open question, and `kb sync` can
record finished Claude Code and Codex transcripts. Curation is handled by
other tools.

## Usage

```sh
kb recall QUERY...    # find the curated sections that answer a query
kb read LOCATOR...    # print the text that each locator names
kb map [PATH]         # list the articles under PATH, with their sections
kb questions [--context PATH] [--all] [--limit N]
kb evidence QUERY... [--kind KIND] [--since DATE] [--until DATE] [--limit N]
kb observe --title TITLE --body TEXT  # record an observation and commit it
kb gap --title TITLE --body TEXT --context PATH  # record a question and commit it
kb sync [--status | --no-push | --dry-run]  # harvest transcripts and sync content
kb --help             # every command
```

Locators look like `knowledge/infra/nas.md#2` (an H2 section), `#1.1` (an H3
section), `#top` (the prose before the first H2), `#title`, or a bare path. Every
locator that `recall` and `map` print is accepted by `read` unchanged.

The content repository comes from the `KB_CONTENT` environment variable, or
from `content = "PATH"` in `config.toml`. That file is
`$XDG_CONFIG_HOME/kb/config.toml`, or `~/.config/kb/config.toml` without
`XDG_CONFIG_HOME`, and `%LOCALAPPDATA%\kb\config.toml` on Windows.

### `kb recall` matching

`kb recall` ranks curated sections by BM25. A curated result can include
matching pending observations and open questions under `Uncurated (pending,
not yet verified)`. It does not scan archived observations or resolved
questions on that path. When there is no curated result, recall searches all
observations and questions and shows the best matches as evidence. Each row
shows its locator, date, kind, and title or excerpt. An addressable harvested
message uses `PATH#N`; older transcripts without addressable messages keep a
file locator.

`--in PATH` scopes curated files and observations by their content paths. If
the scope is under `knowledge/` or `sources/`, questions are selected by
context instead: a question matches when its context is the same area, an
ancestor, or a descendant. Other scopes filter questions by their storage
paths. Observation scope continues to use storage paths, so `--in
knowledge/infra` can include a question about that area but excludes stored
observations.

Query words and curated section words are matched the same way:

- Words are lowercased, and English stopwords are dropped.
- Dates, paths, flags, and negation words such as `not` are kept.
- Other words are Porter-stemmed, so `backups` matches `backup`.
- A derived noun maps to its base verb before stemming, so `retention` matches
  `retained`. The table is in `src/kb/derivations.py`.
- A flag such as `--rename` is indexed under the whole flag and under its bare
  word, so a query for `rename` finds it.
- A numeric identifier such as `50-59` or `192.168.1.10` is matched whole, and
  its parts also match. A query for `50-59` finds only sections that contain
  that identifier, and a query for `50 59` finds sections that contain the parts.

### `kb questions`

`kb questions` lists open questions by default. `--all` includes resolved
questions, and `--limit N` selects how many rows to print (default 20). The
header reports the total number of matches before the limit. Rows show the
question locator, creation date, status, stored context, and title; use
`kb read LOCATOR` to inspect the question body.

`--context PATH` selects questions whose context is that area or one of its
descendants. A shorthand such as `infra` is read as `knowledge/infra`. Contexts
may name an area that does not exist yet, including a deleted article. Deleted
paths remain visible and filterable as stored; the command does not infer a
moved article's new location. Missing or unsafe stored contexts display as `-`
and appear only in an unfiltered listing. Existing question files are not
rewritten. Rows sort by creation date, newest first, then by content-relative
path; invalid or missing dates sort last.

```sh
kb questions
kb questions --context infra --limit 10
kb questions --context knowledge/projects/shapez2/routing.md --all
```

### `kb evidence`

`kb evidence` searches pending and archived observations, transcripts, and
open and resolved questions, even when curated knowledge matches. Kinds are
`observation`, `transcript`, `open-question`, and `resolved-question`;
`--kind` restricts the search to one. Date bounds use strict `YYYY-MM-DD`
values and include both endpoints. Files use the valid date portion of
`created`. Addressable harvested messages use the message timestamp's UTC
date. Records with unknown dates are excluded when a date bound is present.

Kind and date filters are applied before ranking, so they change BM25 corpus
statistics and can change result order. No order is promised to stay the same
across different filters. Results are limited to five by default; `--limit N`
accepts any positive count. Each result is a file locator or, for a qualifying
addressable transcript message, `PATH#N`. `kb read` accepts the printed locator
unchanged. Legacy transcripts that lack addressable message metadata keep file
locators.

```sh
kb evidence "backup disk"
kb evidence --kind transcript --since 2026-10-01 --until 2026-10-31 "session transcript"
```

### `kb gap`

`kb gap` records an attributed question in
`questions/open/<YYYYmmddTHHMMSS>-<8 hex digits>.md` and commits only that
file with subject `Ask: TITLE`. The commit exists before the command reports
success. Other staged files stay staged, and unstaged files remain untouched.
The question stores `title`, `context`, `source: session`, `project`, `host`,
and `created` fields in that order.

All three options are required. Title and body follow the same rules as
`kb observe`; `--body -` reads UTF-8 text from standard input. `--context` is
the best-known area that lacks knowledge. No `kb map` call is required, and the
area need not exist. Bare names resolve under `knowledge/`; content-relative
paths and unique filenames are accepted under `knowledge/` or `sources/`. Paths
use `/` separators, and the writer rejects blank, absolute or drive-letter,
traversal, fragmented, or control-character contexts. A missing or deleted path
is kept as a normalized literal; a shorthand is stored under `knowledge/`. The
context is metadata: the writer does not open context targets, and it stores an
external symlink as a literal path.

Before writing, `kb gap` checks the title, body, and canonical context for
possible secrets. A refusal identifies the detector and field (or body line)
without printing the secret; there is no override. The generated project, host,
timestamp, and random ID fields are not scanned. Locking uses the shared
`KB_LOCK_WAIT` policy documented for `kb observe`.

If the command is hard-terminated after publishing but before its commit,
inspect the content repository's `git status` before retrying. Deliberately
retain and commit, or remove, the uncommitted question first. The command does
not deduplicate retries.

```sh
kb gap --title "Where is the backup disk?" \
  --body "The backup disk location is not recorded." \
  --context knowledge/infra
kb questions --context infra
kb evidence --kind open-question "backup disk location"
kb read questions/open/20261027T120000-0123abcd.md  # use the file printed by kb gap
```

On success stdout is `Wrote: questions/open/<file>` and the exit status is 0.
Usage errors print the usage line. Other failures print nothing to stdout, use
the `gap:` prefix on stderr, and exit 1.

### `kb map` output

`kb map` prints each article as `PATH | Title`, followed by its sections as full
locators that `kb read` accepts. This example is the first two articles of the
output of `KB_CONTENT=tests/fixtures/content uv run kb map --depth 3`:

```text
knowledge/infra/backups.md | Backups
  knowledge/infra/backups.md#1 | Schedule
knowledge/infra/nas.md | NAS
  knowledge/infra/nas.md#1 | Restart order
  knowledge/infra/nas.md#2 | Power loss
```

### `kb observe`

`kb observe` records one observation. It writes
`observations/pending/<YYYYmmddTHHMMSS>-<8 hex digits>.md` in the content
repository and commits only that file, with the subject `Observe: TITLE`.
Anything else that is staged stays staged.

```sh
kb observe --title "DNS caching" --body "The resolver caches answers for an hour."
kb observe --title "Meeting notes" --body - < notes.txt
```

- `--title` is one line and must contain text. `--body` must contain text. `-`
  reads the body from standard input to its end.
- On success, stdout is `Wrote: observations/pending/<file>` and the exit status
  is 0. A usage error prints the usage line and exits 1. Any other failure prints
  nothing to stdout, prints a message that begins `observe:` to stderr, and exits 1.
- The file records `project`, the absolute path of the git top level where the
  command ran (or that directory, outside a repository), and `host`, the host name
  up to its first dot.
- Before anything is written, the title and body are checked for possible secrets
  with detect-secrets' default plugins and filters. Each finding prints a line such
  as `observe: refused: possible secret (Secret Keyword) at body line 4`, then
  `observe: remove or redact it, then run kb observe again`. The secret itself is
  never printed, and there is no override. The generated fields are not checked.
- A write waits for the content repository's lock for `KB_LOCK_WAIT` seconds, a
  non-negative integer that defaults to 30. If the lock is still held, the command
  prints `observe: content repository is busy (waited <N>s for the lock)`, writes
  nothing, and exits 1.

The write takes two locks, in this order. The kernel lock is an exclusive lock on
`<git dir>/kb.lock`, which the kernel releases when the process exits. The second
is the lock that the old scripts in `~/Knowledge/scripts` take: the directory
`<content>/.observe.lock` with a `pid` file. Taking it lets `kb observe` and those
scripts exclude each other while both are in use. A `pid` file that names a process
which is no longer running is stale, and the lock is removed. This second lock is
POSIX only, and it is removed at cutover, along with the old scripts. Until then,
`kb observe` waits for a lock that the old scripts hold, up to `KB_LOCK_WAIT`.

Temporary files for a write live in `<git dir>/kb-tmp` and are removed on every
path.

### `kb sync`

`kb sync` harvests finished Claude Code and Codex transcripts, commits the
resulting observations, then fetches and rebases from `origin` and pushes local
commits. Transcript harvesting is **off** until `harvest_since` is set in
`config.toml`; `kb` does not install or enable the timer.

```toml
content = "~/Knowledge/content"
harvest_since = 2026-10-20T00:00:00Z
```

`harvest_since` is a time-zone-aware TOML datetime; use UTC. Messages before
it are ignored.
Claude transcripts are read from `$CLAUDE_CONFIG_DIR/projects` (default
`~/.claude/projects`), including subagents. Codex rollouts are read from
`$CODEX_HOME/sessions` (default `~/.codex/sessions`), including subagent
threads.

Harvest keeps user text, assistant text, and shell commands. It drops tool
output, reasoning, injected context, and user `<system-reminder>` spans. A
session is ready after it has been idle for 60 minutes and its transcript ends
on a complete line. Idle time uses the newest record timestamp or file
modification time, whichever is later. Ready sessions are processed oldest
first, up to 50 per run. Each transcript part becomes an observation; resumed
sessions create later parts. When transcripts share a message prefix, the
first session to harvest those message IDs owns them. If the later session has
messages to record, its observation names the owner of the shared prefix.

The title excerpt and message text are checked for possible secrets. A matching
message line is replaced with `[redacted: <detector>]`; when the title excerpt
matches, the title omits it. A session is skipped and reported on stderr if
redaction or observation validation cannot finish safely. The exit status is
then 1.

Harvest progress is reconstructed from committed observations in `HEAD`. If a
run stops before its observation commit, the next run removes that run's
uncommitted transcript observations and temporary scanner files, then retries
from the source transcripts. Re-running after a successful harvest does not
duplicate committed messages.

Options:

- `--status` fetches `origin` and reports `Ready`, `Waiting`, `Ahead`, and
  `Behind` counts. It does not harvest or change the branch, index, or working
  tree; the fetch may update remote-tracking refs.
- `--no-push` harvests and commits, then fetches and rebases, but does not push.
- `--dry-run` lists each planned part as
  `<app> <session> part <n>: <m> messages, <bytes> bytes, <k> redacted lines`,
  followed by totals. It does not lock, fetch, or change Git state. Its
  temporary scanner files are removed before exit.

`--status` and `--dry-run` cannot be combined with another option. With
harvesting enabled, a regular run prints `Harvested: <n> session transcript(s)`
and, when there are messages, `Harvest totals: <n> messages, <n> bytes, <n>
redacted lines`. Regular runs and dry runs may also print `Redacted by
detector: ...` and, when transcript records were discarded, `Skipped transcript
records: <n> malformed line(s), <n> duplicate message ID(s)`. With harvesting
disabled, a regular run does not print a harvest line. Successful Git actions
print `Pulled: <n> commit(s)`, `Pushed: <n> commit(s)`, or
`Already in sync with origin/<branch>.` Status prints `Ready: <n> session(s)`,
`Waiting: <n> session(s)`, `Ahead: <n> commit(s)`, and
`Behind: <n> commit(s)`. A dry run prints one line per planned part and
`Totals: <n> sessions, <n> messages, <n> bytes, <n> redacted lines`.

Successful runs exit 0. `--help` prints the usage text and exits 0. Extra
arguments, invalid option combinations, and an invalid `KB_LOCK_WAIT` print
`Usage: kb sync [--status] [--no-push] [--dry-run]` and exit 1. An unknown
option prints `Unknown option: <option>` and exits 1. Other runtime failures
and skipped sessions go to stderr with the `sync:` prefix and exit status 1.
A dirty working tree prints `sync: uncommitted changes in <root>; not
pulling or pushing` and up to 10 paths; that notice alone exits 0 and leaves
pull and push for a later run.

#### Install the user timer

The timer files are examples in `contrib/systemd/`; `kb` does not install or
enable them. After installing `kb` and setting its configuration, copy and
enable the files for your user:

```sh
mkdir -p ~/.config/systemd/user
cp contrib/systemd/kb-sync.service contrib/systemd/kb-sync.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kb-sync.timer
```

The service defaults to `%h/.local/bin/kb`. Edit `ExecStart` in the copied
service file if `kb` is installed elsewhere. The timer runs every 15 minutes
and catches up after the machine was off.

## Development

Requires [uv](https://docs.astral.sh/uv/) 0.13 or newer and [just](https://just.systems/).

The `.python-version` file selects Python 3.15. uv 0.13 or newer can
download its final release. The lower uv minimum in `pyproject.toml` lets
Dependabot update the lock on Python 3.11; CI tests that minimum.

```sh
just sync           # Install the locked development environment.
just hooks-install  # Install the pre-commit hook, which runs `just lint`.
just check          # Run lint, type-check, and test.
just eval           # Score retrieval against the question sets under tests/fixtures.
just test-compat    # Run the observe compatibility tests against ~/Knowledge.
```

Run `just` to list every recipe.

## Releasing

```sh
just release patch  # Or minor or major. Runs `just check`, then commits and tags.
git push origin HEAD vX.Y.Z
```

## License

[CC0 1.0 Universal](LICENSE.md)

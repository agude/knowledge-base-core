# knowledge-base

`kb` lets LLM agent sessions read and search a knowledge base: curated
articles and source documents, and the observations and questions behind them.
`recall`, `read`, `map`, `questions`, and `evidence` are read-only. `kb observe`
records an observation, `kb gap` records an open question, and `kb sync` can
record finished Claude Code and Codex transcripts. `kb lint`, `kb verify`, and
`kb resolve` provide curator checks and explicit updates. `kb curate` runs
resumable batches: `start` synchronizes with `origin`, and `finish` validates a
batch, commits it once, and pushes it. The content pre-commit hook,
`kb hook pre-commit`, checks every content commit. `kb setup` configures a
machine and installs that hook, and `kb doctor` names each problem with its
fix.

## Usage

```sh
kb recall QUERY...    # find the curated sections that answer a query
kb read LOCATOR...    # print the text that each locator names
kb map [PATH]         # list the articles under PATH, with their sections
kb questions [--context PATH] [--all] [--limit N]
kb evidence QUERY... [--kind KIND] [--since DATE] [--until DATE] [--limit N]
kb lint [PATH...] [--require-ttl]  # check articles before publication
kb verify ARTICLE [--ttl TTL]      # record an explicit verification
kb resolve QUESTION --answer TEXT [--destination LOCATOR | --obsolete]
kb curate {start,status,next,complete,defer,drop,finish} ...
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
observations. Evidence files excluded by storage path are not read; questions
selected by context must be read to inspect that field.

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
not deduplicate retries. A handled staging or commit failure removes only the
new question and its staging, including edits made by a rejecting hook. If Git
prevents rollback, the command reports the failure and retains the question.
Inspect both its staged and working-tree contents before deciding to commit or
remove it, then retry.

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

### Curation commands

`kb lint`, `kb verify`, and `kb resolve` are curator commands. They do not
commit. `kb lint` is read-only: it does not write files, take locks, run Git,
or make network calls. `kb verify` and `kb resolve` edit the content repository
under the shared writer lock. They wait according to `KB_LOCK_WAIT`, which is
a non-negative number of seconds and defaults to 30.

#### `kb lint`

```sh
kb lint [PATH...] [--require-ttl]
```

With no path, `kb lint` checks every Markdown article under `knowledge/`. A
path can name one article or a directory under `knowledge/`; paths outside
that directory are refused. The command reports errors for missing or invalid
front matter, H1 and code-fence problems, invalid section metadata, bad
`supersedes` references, missing local source or Markdown-link targets, and
unresolved fragments. It warns when an H2 is longer than 50 lines or repeats
another H2 in the same article. External URLs, `mailto:`, and absolute paths
are not checked. A local link that escapes the content repository is an error.

`updated` and `verified` must be valid `YYYY-MM-DD` dates. A present `ttl` must
be `people`, `status`, `process`, `domain`, or a positive day count no greater
than 1,000,000. Without `--require-ttl`, `ttl` may be absent; with the option,
every checked article must have one. Freshness uses a 60-day default when an
article has no `ttl`.

Each finding is printed as `PATH:LINE: error|warning: MESSAGE`, followed by a
summary such as `Lint: 2 errors, 1 warning in 4 file(s)`. A clean run prints
`Lint: 0 errors, 0 warnings in N file(s)`. The command exits 1 when it finds
an error or cannot read its input; warnings alone exit 0. Usage errors print
the usage line.

#### `kb verify`

```sh
kb verify ARTICLE [--ttl TTL]
```

`ARTICLE` must resolve to one file under `knowledge/` and must not include a
fragment. The command sets `verified` to today's date. Supply `--ttl` when the
article has no valid TTL; a supplied value replaces or adds `ttl`. Values are
the named TTLs `people`, `status`, `process`, and `domain`, or a positive day
count up to 1,000,000.

Before writing, `kb verify` builds the proposed article in memory and checks it
with `kb lint --require-ttl`, including local references. It refuses an
unrelated lint error, `conflict: unresolved`, section-level `verified`
metadata, unsafe front matter, or a possible secret in the TTL. A missing or
invalid `verified` date is repaired. When the date and TTL already match, the
command succeeds without rewriting the article. Otherwise it replaces the
article atomically. It leaves the change uncommitted.

Success prints `Verified: PATH (ttl TTL)`. Failures print nothing to stdout,
use the `verify:` prefix on stderr, and exit 1. A usage error prints the usage
line.

#### `kb resolve`

```sh
kb resolve QUESTION --answer TEXT --destination LOCATOR
kb resolve QUESTION --answer - --destination LOCATOR
kb resolve QUESTION --answer TEXT --obsolete
```

`QUESTION` must resolve to one file under `questions/open/`. Supply exactly
one of `--destination` and `--obsolete`. An answered question's destination
must be a locator that `kb read` resolves under `knowledge/`, including a
valid section fragment. The command stores its canonical content-relative
locator. `--obsolete` marks a question that no longer needs an answer and does
not store a destination. `--answer -` reads UTF-8 text from standard input;
the answer must contain non-whitespace text.

The resolved copy keeps the open question's filename under
`questions/resolved/`. It preserves the original text and appends `resolved`
and `resolution` front matter fields, plus a quoted `destination` field for
answered questions. It then adds `## Resolution (YYYY-MM-DD)` and the answer.
The command scans the destination and answer for possible secrets. A refusal
names the detector and either `at destination` or `at answer line N`, without
printing the secret.

`kb resolve` refuses a question outside `questions/open/`, an invalid
destination, or an existing resolved copy. It publishes the resolved file
atomically, then removes the open file. A handled failure rolls back the
resolved copy and keeps the open question unchanged. If the process is hard
terminated between publication and removal, both files remain and another
`kb resolve` refuses the existing resolved copy. Inspect the resolved copy,
then remove the duplicate open file manually before continuing.

Success prints
`Resolved: questions/open/<file> -> questions/resolved/<file>`. Failures print
nothing to stdout, use the `resolve:` prefix on stderr, and exit 1. A usage
error prints the usage line.

Example gap-to-resolution flow:

```sh
kb gap --title "Where is the backup disk?" \
  --body "The backup disk location is not recorded." \
  --context knowledge/infra
# Replace this example path with the Wrote path returned above.
kb resolve questions/open/REPLACE_WITH_FILE.md --answer "The disk is stored on the NAS." \
  --destination knowledge/infra/nas.md#1
kb questions --context infra
kb questions --context infra --all
```

#### `kb curate`

The batch commands select a fixed set of pending observations, show one at a
time with relevant context, record each outcome in a JSON manifest, and publish
the result as one commit. `start` synchronizes with `origin` first. `finish`
validates the batch's changes, commits them once, and pushes. Between those
commands, the curator edits articles directly in the working tree.

```sh
kb curate start --max-bytes 65536 [FILENAME...]
kb curate start --no-sync --max-bytes 65536 [FILENAME...]
kb curate status RUN
kb curate next RUN [--query TEXT]
kb curate complete RUN FILENAME --disposition incorporated LOCATOR...
kb curate complete RUN FILENAME --disposition duplicate LOCATOR...
kb curate complete RUN FILENAME --disposition ephemeral --reason TEXT
kb curate defer RUN FILENAME --reason TEXT
kb curate drop RUN FILENAME --reason TEXT
kb curate finish RUN [--no-push]
```

`start` requires a byte budget. It counts each observation's original UTF-8
bytes, including front matter, and selects ordinary Markdown files directly
under `observations/pending/`. It snapshots the chosen filenames, sizes, and
hashes in `observations/batches/RUN.json`. A clean Git worktree is required
when the batch starts. Automatic selection proceeds by creation date; explicit
filenames preserve their supplied order. If an observation is larger than the
budget, `start` prints a command that selects that file alone with its own
size as the budget.

Before it selects anything, `start` takes the writer lock once and runs the same
recovery and harvest as `kb sync`, when `harvest_since` is set. It then fetches,
rebases onto `origin/BRANCH`, and pushes local commits. It prints `Pulled: N
commit(s)`, `Pushed: N commit(s)`, or `Already in sync.` It creates no batch
when there is no `origin`, HEAD is detached, the fetch fails, the rebase
conflicts (the rebase is aborted and local commits are kept), or the push
fails. The message names the failing step and says `no batch created`. Use
`--no-sync` for offline work. It creates an unpublished local batch and prints
`Not synchronized: local batch`. The manifest records `synchronized` and
`base_commit`, the HEAD the batch started from. Version 1 manifests load as
unsynchronized batches with no base commit; the next change rewrites them as
version 2.

The RUN below came from an isolated fixture repository. A real run prints its
own RUN; use that value for every later command.

```text
$ kb curate start --max-bytes 65536
Already in sync.
Created batch: 20261026T120000-8664e45f
Selected: 2 observation(s)
Selected bytes: 456
Eligible pending observations: 2
Input budget: 65536 bytes
Open questions: 1
Related stale articles: 0
Related stale knowledge: none

$ kb curate status 20261026T120000-8664e45f
$ kb curate next 20261026T120000-8664e45f
```

`status` and `next` take no locks and write nothing. `status` reads local Git
refs to report whether the batch is committed and published; it never contacts
`origin`. `next` prints the full
observation, up to three matching curated sections, and up to five related open
questions. The byte budget limits only the original observations; these
sections and question rows add to the context shown for each item. `--query`
replaces the observation title when another query better describes the work.

Edit knowledge articles directly. Before completing an incorporated item,
add its future archived locator to the article's `sources`. For example, use
`observations/archived/FILENAME.md#1` when citing its first numbered section.
The reference is temporarily missing until completion publishes the archive.
`kb verify` will refuse it while missing. After completion, run `kb lint` and
use `kb verify` only when the archived evidence supports the claim. Resolve
questions with `kb resolve` when evidence supports an answer.

`incorporated` accepts a whole knowledge article or a readable section.
`duplicate` requires a numbered section. Both can name multiple destinations;
the manifest stores each canonical locator and its current heading. `ephemeral`
accepts no destination and requires a single-line reason. Completion adds the
batch identifier, the original file's hash, and an ephemeral reason to the
archived observation. The manifest keeps the disposition, the full destination
list, and the archived file's hash. It does not change article dates or stage
or commit files.
The command scans supplied destinations and ephemeral reasons for possible
secrets before reporting validation errors. Successful completion prints the
pending-to-archived path; failures use the `curate:` prefix and exit 1.

If completion stops after saving its archive intent, repeat the exact
`complete` command printed by `status`. Recovery checks the recorded hashes:

| Files present | Recovery |
|---|---|
| Original pending file only | Rebuild and publish the recorded archive. |
| Original and expected archive | Remove only the unchanged pending copy. |
| Expected archive only | Mark the member complete. |
| Neither copy, changed input, or conflicting archive | Stop and inspect the files manually. |

`defer` keeps an unchanged pending file for a later batch. `drop` records a
reason when another writer removed or changed that file; it leaves the file as
found. Both scan the reason for possible secrets. Identical retries succeed.
Dropping an unchanged input or deferring a changed or missing input is refused.

`finish RUN` publishes a settled batch. It refuses before it writes anything
when the batch has pending work, an interrupted archive, a detached HEAD, no
`origin` (unless `--no-push`), staged changes already in the index, or a
worktree path outside the batch. The publication set is:

- changes under `knowledge/`, `sources/`, and `questions/`;
- each completed member's new archive and removed pending file;
- each dropped member's removed pending file, when it was deleted;
- the batch manifest.

Anything else is listed, up to eight paths and then a count, and finish
refuses. A pending observation that arrived after `start` is never swept in;
the next batch that selects it handles it.

Finish validates the publication set before it stages anything. A changed
article must lint with a required `ttl` and decode as UTF-8. Every article's
references are checked, so a change that removes a target breaks each citation
to it. Blocking findings refuse finish and are printed. Findings that already
existed in unchanged articles print under `Preexisting (not blocking):` with
their count and do not stop publication.

Finish stages exactly the publication set, checks the staged paths against it,
and commits once. The message lists the counts, each article changed, every
outcome with its locator or reason, and each question resolved. The commit runs
the content hook. If the commit fails, finish unstages only the paths it staged
and leaves every file as it was. After the commit, finish fetches, rebases, and
pushes. A rebase conflict or a failed push exits 1 with `Committed locally; not
published`. Resolve the cause, then run `kb sync` or repeat `kb curate finish
RUN`; the repeat pushes the existing commit and makes no other. `--no-push`
stops after the commit. Success prints the commit hash and `Published:
origin/BRANCH`. A repeated finish after publication prints `Already published`.

`kb curate status` reports the publication state from local refs: unpublished,
committed locally, or published as the commit that holds the manifest.

### Content pre-commit hook

`kb hook pre-commit` is the content repository's Git pre-commit hook. Git runs
it with the content repository as the working directory. `kb setup` installs a
three-line script that calls this command by its absolute path. See
[`kb setup`](#kb-setup).

- A commit that stages no article, and no removal or move under `knowledge/`,
  `sources/`, or an archive, exits at once without output.
- An article staged with unstaged worktree changes refuses the commit. Stage or
  discard the other changes first.
- Staged articles are validated as `kb curate finish` validates them. Blocking
  findings reject the commit and modify nothing.
- After validation, `updated` is set to today's UTC date on each staged article
  whose value differs, and the article is staged again. A missing `updated` is
  not added, and `verified` and `ttl` are never changed.
- A commit made through a temporary index, as `git commit -- PATH` does, is
  validated but not stamped. The hook reports each article that keeps its older
  value.
- The hook takes no writer lock. Commands that already hold the lock can commit
  through it without waiting.

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

The write takes one lock: an exclusive kernel lock on `<git dir>/kb.lock`, which the
kernel releases when the process exits.

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

A regular `kb sync` also records its outcome in `<git dir>/kb/sync-state.json`,
in the common Git directory, where Git never commits it. The record names the
run's outcome (`ok`, `dirty`, or `error`), the time of the last successful
exchange with `origin`, and the first line of any failure, unredacted. That
line may contain a local path. The record stays in the common Git directory and
is never committed. `kb sync --status` and `kb sync --dry-run` write nothing.
`kb doctor` reads this record.

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

## Setup and diagnosis

### `kb setup`

`kb setup` configures one machine. It sets the config file's `content` key,
installs the content repository's pre-commit hook, and can create a content
repository. It prints one line per resource: `Config:`, `Hook:`, and `Skill:`
(and `Init:` with `--init`; `Capture:` with `--enable-capture`). It exits 1 when
it refused any resource, and a refusal does not stop the other resources.

```text
kb setup [--content PATH] [--kb PATH] [--enable-capture]
kb setup --init PATH [--origin URL] [--kb PATH]
kb setup --print {instructions|allow-claude|allow-codex}
```

- `--content PATH` sets `content` to the absolute path and installs the hook
  in that repository. Without it, setup installs the hook in the configured
  repository and leaves the config file unchanged.
- The config edit changes only the top-level `content` line. It keeps every
  other byte, and the result must parse as TOML with no other key changed. A
  file that does not parse, starts with a byte order mark, or has a `content`
  key that is not a single-line basic string is refused, and the message names
  the file.
- `--kb PATH` names the `kb` that the hook calls. Without it, setup uses the
  `kb` on `PATH`. The path is made absolute without resolving symbolic links,
  and it must print `kb` followed by a version. A path with a single quote, a
  line break, or NUL is refused.
- The hook is a POSIX `sh` script. Setup writes it through the Git directory's
  `kb-tmp`, under the writer lock, and it honors `core.hooksPath`. Setup
  rewrites its own script when the bytes differ, for example after `kb` moves.
- A hook that kb did not write, including a symbolic link, is refused and left
  unchanged.
- Setup copies the packaged `knowledge-base` and `curate` skills into
  `$CLAUDE_CONFIG_DIR/skills/` (default `~/.claude/skills/`) and
  `~/.agents/skills/`. A `.kb-managed` marker records
  the package version. Setup updates only directories with that marker; it
  refuses foreign directories and symbolic links, and leaves their targets
  unchanged.
- `--init PATH` creates a content repository. It refuses a path that exists and
  is not an empty directory, and it refuses when `kb` cannot be found; both
  refusals come before anything is created. It writes the layout, with a
  `.gitkeep` in each empty directory, `.gitattributes` with
  `* text=auto eol=lf`, and an `AGENTS.md` policy stub. Then it runs
  `git init -b main`, installs the hook, and makes one commit,
  `Initialize knowledge base content`. When the hook is refused or the commit
  fails, setup removes what it created, leaves the config unchanged, and exits
  1, so `--init` can run again. `--origin URL` adds `origin` and pushes `main`.
  A failed push keeps the local repository, exits 1, and prints the
  `git push --set-upstream origin main` command that recovers. `kb sync` cannot
  make the first push, because it fetches `origin/main` first.
- `--enable-capture` writes top-level `harvest_since` at the current UTC second
  when the setting is unset; an existing cutoff stays unchanged. It does not
  run `kb sync` or enable the timer. Setup never enables the timer or edits host
  settings or instruction files.

### `kb setup --print`

`kb setup --print` writes host text to stdout and changes nothing. The
dotfiles install this text.

- `instructions` writes the instruction block between `<!-- kb:begin -->` and
  `<!-- kb:end -->`. Its content policy line imports the content repository's
  `AGENTS.md`. Claude Code loads the import, and Codex reads the same line as
  a path, because the dotfiles install one file for both hosts. The line needs
  a content path, from `KB_CONTENT` or the config file.
- `allow-claude` writes a settings fragment with `permissions.allow` set to
  `Bash(kb COMMAND *)` for each working-agent command.
- `allow-codex` writes a rules file with one `prefix_rule` per working-agent
  command, each with `decision = "allow"`. Install it as a regular file under
  `$CODEX_HOME/rules/`. Codex 0.165.0 skips a symlinked rules file.

The working-agent commands are `recall`, `read`, `map`, `questions`,
`evidence`, `observe`, and `gap`. No rule approves another `kb` command or a
bare `kb`. Codex matches a rule against a command's argument list, so an agent
must call `kb` by name. The Codex matcher does not unwrap a shell wrapper such
as `bash -c`.

The dotfiles install the instruction block in each host's global file:
`CLAUDE.md` under `CLAUDE_CONFIG_DIR` (default `~/.claude`), and `AGENTS.md`
under `CODEX_HOME` (default `~/.codex`). They install the Claude rules in the
`permissions.allow` list of `settings.json` in the same directory, and the
Codex rules as a copied regular file, `rules/kb.rules`, under `CODEX_HOME`.
They install the timer
units in `~/.config/systemd/user/`, as the install section below describes.

### `kb doctor`

`kb doctor` prints one line per check, `PASS`, `WARN`, or `FAIL`, with the
check's name and message. Each `WARN` or `FAIL` line is followed by a `fix:`
line. Doctor exits 1 when a check fails. It only reads: it takes no lock, sets
`GIT_OPTIONAL_LOCKS=0`, never fetches, and writes no file. A check that cannot
gather its facts reports why, and the other checks still run.

| Check | Passes when | Warns when | Fails when |
|---|---|---|---|
| `version` | always | | |
| `config` | the content root resolves | | there is no content setting, the file does not parse, or the root is not a directory |
| `content` | a Git repository on a branch, with `origin`, a clean tree, and level with the last fetched `origin` | the tree is dirty, or the branch is ahead or behind | it is not a repository, HEAD is detached, or there is no `origin` |
| `gitattributes` | `* text=auto eol=lf` is in effect | the attributes differ | |
| `hook` | kb installed it, and its `kb` runs `--version` | | the hook is absent or foreign, or its `kb` is missing |
| `curation` | no unsettled batch | a batch is unsettled, or committed but not published | |
| `sync` | the last exchange was within 60 minutes | the last run ended `dirty` or `error`, or the exchange is older | there is no record |
| `scheduler` | on Linux, `kb-sync.timer` is enabled and active | it is not enabled or not active; elsewhere, `not checked on PLATFORM` | |
| `capture` | `harvest_since` is set, the transcript roots are readable, and no ready transcript is older than 20 days | capture is disabled, a root is unreadable, or old ready transcripts exist | |
| `instructions` | each host's global file has the canonical block, with or without its content policy line | a block is missing or differs | |
| `skills` | both packaged skills at both host destinations match the package | a skill is missing, differs, or is unmanaged | |
| `allow-rules` | each host has every working-agent rule and no broader `kb` rule | a rule is missing, a broader rule exists, or a Codex rules file is a symbolic link | |

- `capture` reports Claude Code's `cleanupPeriodDays`, which defaults to 30.
  Codex retention is reported as `unknown`, because its configuration documents
  no retention setting.
- `scheduler` asks `systemctl --user` whether `kb-sync.timer` is enabled and
  active. A missing `systemctl` produces a warning.

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
```

Run `just` to list every recipe.

## Releasing

```sh
just release patch  # Or minor or major. Runs `just check`, then commits and tags.
git push origin HEAD vX.Y.Z
```

## License

[CC0 1.0 Universal](LICENSE.md)

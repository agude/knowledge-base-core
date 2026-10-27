# knowledge-base

`kb` lets LLM agent sessions read and search a knowledge base: curated
articles and source documents, and the observations and questions behind them.
The read commands never write. `kb observe` is the one command that writes: it
records an observation and commits it to the content repository. Curation is
handled by other tools.

## Usage

```sh
kb recall QUERY...    # find the curated sections that answer a query
kb read LOCATOR...    # print the text that each locator names
kb map [PATH]         # list the articles under PATH, with their sections
kb observe --title TITLE --body TEXT  # record an observation and commit it
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

`kb recall` ranks sections by BM25. Query words and section words are matched
the same way:

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

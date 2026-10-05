# knowledge-base-core

**Knowledge-Base-Core** is an external memory and context layer for LLM agent
sessions. Scripts, portable skills, and host adapters operate on a separate
content repo.

The knowledge base stores curated articles about systems, domain knowledge,
preferences, and tooling that the LLM learns as it goes.

## Quick start

```bash
# Clone this repo
git clone https://github.com/agude/knowledge-base-core.git
cd knowledge-base-core

# The tooling checkout is the script and adapter root
export KNOWLEDGE_BASE="$PWD"

# Point the tooling at a separate content repo
export KB_CONTENT_DIR="$HOME/my-knowledge-base"

# Initialize that content repo and install its hook
scripts/init --path "$KB_CONTENT_DIR"

# Capture something
scripts/observe --title "NAS restart order" --body "Traefik first, then Syncthing, then Plex"

# Search
scripts/search "syncthing"

# List topics
scripts/toc
scripts/toc --depth 2

# Check status
scripts/status
```

## Architecture

Two git repos: this one (infra/tooling) and a content repo (your knowledge
articles).

```
knowledge-base-core/    # this repo
├── scripts/            # CLI tools
├── skills/             # Portable Agent Skills
├── tests/              # bats tests
├── scripts/adapters/   # Host-specific protocol adapters
└── .agents/skills      # shared skill installation location

content/                # separate git repo, gitignored by this one
├── knowledge/          # curated articles (organized by topic)
├── observations/
│   ├── pending/        # raw observations, uncurated
│   └── archived/       # processed observations (provenance)
├── questions/
│   ├── open/           # known gaps, one file each
│   └── resolved/
└── sources/            # local copies of external reference documents
```

The content repo can live anywhere. `KNOWLEDGE_BASE` identifies this tooling
checkout so adapters can find its scripts. `KB_CONTENT_DIR` selects the
content repo; when it is unset, content defaults to `./content` inside this
checkout. Do not set `KNOWLEDGE_BASE` to the content repo. `content/` is
gitignored here so the two git repos can coexist in one tree.

### The two-root pattern

Scripts distinguish two roots, and that split is what lets the tooling be
public while the data stays private:

- **`REPO_ROOT`** (this repo) — finding sibling scripts, reading the infra
  `AGENTS.md`, display in `status` and `context`.
- **`CONTENT_DIR`** (the content repo) — every data path, `resolve_path`,
  lock-file placement, and `locked_commit`, which cds in and runs git there.
  Set by `_lib.sh`; defaults to `$REPO_ROOT/content`, overridable with
  `KB_CONTENT_DIR`.

The environment names map to those roots as follows:

- **`KNOWLEDGE_BASE`** — the tooling checkout used by host adapters.
- **`KB_CONTENT_DIR`** — the content repo selected by `_lib.sh`.

Output paths strip `$CONTENT_DIR/`, so users see and pass relative paths like
`knowledge/topic.md`. **Every commit made by a script goes to the content
repo.**

### Pluggable instruction files

`session-context` concatenates this repo's `AGENTS.md` (how the knowledge base
works) with `content/AGENTS.md` (project-specific policy) when the latter
exists. `CLAUDE.md` is accepted as a compatibility name when `AGENTS.md` is
absent.

**Order matters:** the content file comes second, so its rules take precedence
— later instructions override earlier ones. Policy like "we never record X"
belongs in `content/AGENTS.md`, not here.

### Three layers of instruction

| Layer | Loaded | Holds |
|---|---|---|
| `AGENTS.md` (infra + content) | Every session, injected | Script table, observation trigger rules, pointer to the skills |
| `knowledge-base` skill | On invoke | Lookup workflow, observation practices, attribution, freshness thresholds |
| `curate` skill | On invoke | Curation workflow, article conventions, voice, frontmatter |

Observation *trigger* rules stay in `AGENTS.md` because an agent has to observe
spontaneously — it cannot load a skill to learn that it should. The detailed
"how to write a good observation" guidance lives in the skill.

### Heading numbering

`toc --depth 3` shows dot-numbered H3s (1.1, 1.2, …) and `section --number 2.1`
extracts one. **H4 and deeper are intentionally not addressable:** if content
follows the 10–50 line H2 guideline, an H4 is small enough to load via its
parent H3.

The hierarchy is directories → files → H2 → H3: three levels of filesystem,
two of heading. When an H2 grows past ~50 lines, split it into several H2s;
when a file accumulates too many H2s, split the file; when related files
accumulate, promote them to a subdirectory.

## Content structure

Knowledge articles live in `knowledge/`, organized into topic subdirectories.

```yaml
---
title: "Sync Topology"
updated: 2026-04-12
verified: 2026-04-12
ttl: domain
sources:
  - observations/archived/20260412T101500-a1b2.md
---

Standard markdown content. Links use [normal syntax](other-page.md).
```

- `updated` — date of the last edit. Stamped by the content repo's
  pre-commit hook; do not set it by hand.
- `verified` — date the content was last confirmed accurate. Set only by a
  curator who actually looked. This is the field that decides how much a
  reading session should trust the article, so nothing automatic touches it.
- `ttl` — how fast the article rots: `people`/`status` (14 days),
  `process` (60), `domain` (180), or a number. `stale` reads it; absent
  means 60. Numeric days are decimal, including leading zeroes. Numeric values
  above 106751991167300 days are invalid because their seconds would overflow.
- `sources` — the observation files that fed the article. Append on update.
- `aliases` — optional routing phrases for question-mode search. Store one
  phrase per list item, for example `- "production tunnel"`.

Sections may override article metadata with an HTML comment immediately after
an H2 or H3 heading. Blank lines may separate the heading and comment. The
comment must start on its own line before body content; inline and fenced
examples do not set metadata. Misplaced standalone comments are reported as
invalid without applying their values. Metadata comments are excluded from
search evidence:

```markdown
## Restart the API

<!-- kb-section: verified=2026-09-01; ttl=process; effective=2026-08-01; status=current; sources=observations/archived/restart.md -->
The current procedure.
```

Section metadata inherits omitted fields from article frontmatter. Metadata
comments stand alone, including the closing line of a multiline comment.
Prose following `-->` makes the comment an inline example; it does not set
live metadata, and the prose remains searchable. Supported
fields are `verified` (or `synced` for source documents), `ttl`, `effective`,
`status` (`current`, `superseded`, or `unresolved`), `supersedes` (a backward
link from the newer section to the older H2/H3 numeric locator), and
comma-separated `sources`. A historical section uses `status=superseded` and
does not carry the link. `section`, `search`, and
`stale --sections` expose the section locator and metadata. `lint` validates
dates, effective-date ordering, status transitions, supersession locators, and
section-scoped source references.

`lint` validates relative Markdown links and `.md` entries in `sources:`.
External URLs and examples inside fenced or inline code are ignored; external
URLs are never fetched. Use `lint --batch BATCH_ID` while a selected
observation is still pending but its future `observations/archived/` path is
already referenced. Run lint again without `--batch` after archiving so the
final content has no broken references. The linter does not mass-repair
existing content; compatibility findings require a separate curation pass.

When a source reference is missing, search both pending and archived paths in
content Git history. Restore the original evidence when available. Otherwise
review the affected claims before replacing or removing the reference, and
record any unresolved evidence gap. Passing lint confirms reference validity;
it does not establish that a source supports a claim. Keep strict validation
enabled and run full content lint after the repair.

## Scripts

| Script | Purpose |
|---|---|
| `init [--path DIR]` | Initialize a content repo |
| `observe --title "..." --body "..."` | Capture an observation to observations/pending/ |
| `pending [--full] [--count] [--preview] [--max-bytes N]` | List observations or preview a byte-bounded curation queue |
| `archive FILENAME [FILENAME ...]` | Archive explicit observations |
| `archive --batch ID --disposition TYPE [--destination PATH] FILENAME` | Complete one persisted batch member |
| `batch start [--max-bytes N] [--files FILENAME ...]|status|defer` | Persist and resume a byte-bounded curation batch |
| `search <term> [term ...] [--query TEXT] [--relax] [--explain] [--max-bytes N] [--json\|--text-only] [--path PATH] [--topic NAME] [--corpus TYPE]` | Search ranked sections with freshness, provenance, and optional question normalization |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT \| --top \| --title) [--max-bytes N] [--json\|--text-only]` | Extract a section or search fallback with freshness and provenance |
| `section --file FILE --references [--json]` | Return the complete provenance reference list |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `stale [--days N] [--path DIR] [--sections]` | List articles or sections needing re-verification |
| `lint [--path DIR] [--strict] [--batch ID]` | Check articles, links, source references, and structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status] [--no-push]` | Pull and push the content repo |
| `status` | Summary stats |
| `evaluate-retrieval --fixture FILE [--max-bytes N]` | Measure retrieval against a versioned question fixture |
| `context` | Compact summary for session injection |
| `session-context` | Produce context for a host adapter |
| `session-init` | Create a session buffer |
| `session-file` | Resolve a session ID to its buffer path |
| `session-append` | Append one message to a session buffer; use `--message -` for stdin |
| `session-flush` | Convert a buffer into an observation |
| `doctor [--require CAPABILITY]` | Diagnose runtime, roots, hooks, skills, and capture setup |

All scripts support `--help`.

### Runtime requirements and diagnosis

The core runtime uses Bash 4 or newer, standard POSIX-style utilities, and
Git for the content repository. `stat` must support either GNU `-c` or BSD
`-f`; freshness parsing supports both GNU and BSD `date`. Batch manifests need
`sha256sum` or `shasum`. Retrieval does not require Python, uv, Node, a
database, or a network service.

JSON retrieval and the capture fallback encoder require `od` and AWK.
`jq` is required when a command must parse JSON: session flushing, host adapter
protocols, and retrieval evaluation. `session-append` can encode messages
without jq, using `od` and AWK to preserve control characters and exact trailing
newlines without encoder scratch files. `session-flush` will retain the
source buffer when JSON parsing fails or jq is unavailable. Development checks
add ShellCheck, Bats, and just; the Pi adapter has its separate npm and Node
requirements documented below.

#### Utility compatibility

The shell runtime uses these non-uniform utility features:

| Feature | Use | Compatibility rule |
|---|---|---|
| `readlink -f` | Resolve entrypoint locations before loading shared code | Required by core entrypoints; the shared `canonicalize` and portability-lint paths include manual symlink walking for BSD `readlink`. |
| `sort -z` | Keep NUL-delimited filenames safe during recursive scans | Required by retrieval, curation, and archive ordering; no text-line fallback is safe for arbitrary filenames. |
| `sort -V` | Order numeric section locators | Required for section metadata output; callers on systems without version sort must use GNU-compatible sort. |
| `find -maxdepth` | Limit top-level queue, batch, and topic scans | Required for bounded directory scans; the scripts do not emulate it with a second traversal. |
| `stat -c` / `stat -f` | Read byte counts and permissions | Either GNU `-c` or BSD `-f` is accepted. |
| `date -d` / `date -j` | Parse freshness and creation timestamps | Either GNU `-d` or BSD `-j -f` is accepted. |
| `sha256sum` / `shasum -a 256` | Hash batch inputs | Either implementation is accepted. |

Bash 4 or newer is required for associative arrays and `mapfile`. These are
host requirements for the default shell runtime; Python, uv, Node, npm,
SQLite, and network services remain outside that gate. Node and npm are only
needed for the optional Pi development checks.

Run the read-only diagnostic after installation. With
`--require retrieval`, it also probes the required `sort -z`, `sort -V`,
`find -maxdepth`, and `readlink -f` behaviors using temporary fixtures:

```bash
scripts/doctor
scripts/doctor --require retrieval --require capture --require curation
```

Without `--require`, unavailable optional capabilities are reported as
warnings. A requested capability returns nonzero when it fails. The doctor
checks the two roots, content Git state, installed hook and skills, configured
session directory, command availability, and a temporary stdin-capture smoke
test. It does not install anything, contact a network, or write a real
observation. A missing, failed, or interrupted flush leaves the original
session buffer in place; retry `session-flush PATH` after repairing the
reported dependency or destination. A rejected observation commit also
leaves the generated pending observation and source buffer available for
recovery.

Large or multiline messages must be sent through stdin so they never become a
process argument:

```bash
printf '%s' "$message" |
  scripts/session-append --file "$buffer" --role user --message -
scripts/session-flush "$buffer"
```

`--message` accepts exactly one input form. Use either an argument or `-` for
stdin; repeating the option, including mixing both forms, fails before a
record is written. Empty input is a no-op, while non-empty stdin preserves
Unicode and trailing newlines.

An uninitialized session remains a no-op. When enabled capture cannot create
its session buffer, append returns nonzero with a diagnostic so the host adapter
can retry and report failure. Codex retains its required `{}` stdout response.

### Retrieval output

`search` and `section` include retrieval metadata by default. `--text-only`
returns metadata-free text output for callers that cannot consume metadata;
search results remain one line per ranked section. `--json` returns structured
output and keeps diagnostics on stderr. The two modes cannot be combined.

Metadata classifies each result as a curated article, source document, pending
observation, question, or archive. Open and resolved questions use the
`question` corpus with `provenance.state` set to `open` or `resolved`; they are
knowledge gaps or question records, not evidence. Curated articles use
`verified` and their applicable `ttl`; source documents use `synced`. Missing
dates are `unknown`, malformed dates are `invalid`, and neither is reported as
fresh. Stale results remain available and are labeled `stale`.

Articles with an unresolved contradiction must set `conflict: unresolved` in
frontmatter. Retrieval exposes this independently as `conflict.status`, so a
recently verified article cannot make an unresolved conflict appear settled.

Curated article `sources` are exposed as article-level references. They identify
the evidence associated with the article and are not claim-level citations.
The default output displays at most five references and reports
`reference_count` and `references_truncated` in JSON. The complete list remains
in the file's `sources:` frontmatter; retrieve it with
`section --file FILE --references [--json]`. Pending and archived observations
are labeled uncurated or archived evidence. Source documents expose their
`canonical` reference when present.

`search --json` returns an object with a bounded `results` array plus
`total_files`, `total_lines`, `returned`, and `truncated`. Each result is one
ranked Markdown section and contains `path`, `corpus`, `locator`, `freshness`,
`conflict`, `provenance`, `match_count`, and a query-focused `text` excerpt.
`match_count`
is the number of distinct evidence lines retained for that section; identical
lines count once. `--files` returns one file result with the number of matching
sections in `match_count` and a null locator. `--limit` bounds result sections,
and `--per-file` bounds sections from each file.

`--max-bytes N` bounds all search stdout bytes, including JSON syntax and
metadata. JSON candidates are serialized before selection, remain complete
records, and retain ranking order. The response reports `max_bytes`,
`omitted_results`, and `truncated`; stderr reports byte usage. A cap smaller
than the minimum valid JSON envelope fails. Text output retains complete lines
and appends an explicit truncation marker. Omit the option for the existing
unbounded behavior.

Byte-budget contract:

- `N` is a non-negative decimal byte count. Leading zeroes are normalized as
  decimal, and values outside the supported integer range fail before any
  search, section retrieval, preview, or batch manifest work.
- Retrieval budgets cover stdout only, including JSON envelopes, metadata,
  newlines, and truncation markers. Stderr diagnostics do not consume the
  budget. An exact fit succeeds; a one-byte-short cap either emits a smaller
  complete response with an omission marker or fails when no complete record
  and marker can fit.
- `search` rejects a cap below its minimum valid JSON envelope or below one
  complete text record plus its marker. `section` applies the same rule to
  its metadata envelope and complete-line prefix. A first record or line that
  is too large is not clipped or skipped in favor of a later result; the
  command reports that the cap cannot represent a safe response. Section
  truncation closes an open Markdown fence before its marker.
- `section --references --max-bytes N` requires the complete references
  response to fit. `--max-bytes 0` therefore fails for retrieval output even
  when the selected content has no body; an empty search scope still returns
  the valid JSON envelope when the cap permits it.
- Batch and preview budgets apply to source-file bytes, including frontmatter.
  Zero selects no automatic batch items: `pending --preview` reports an empty
  selection, while `batch start` fails without creating a manifest. An
  explicit list must fit in full or is rejected before manifest creation.
  Automatic selection uses valid creation timestamps first, then filename for
  ties; missing or invalid timestamps sort after valid timestamps by filename.
  An exact fit is selected, and excluded or newly arrived files remain
  pending and outside the batch manifest.

Search terms must occur somewhere in the same file. Complete term coverage is
the primary ranking tier for actual sections, so a section containing all terms
ranks above sections that provide only file-level fallback evidence when terms
are split across sections. An exact frontmatter-title result remains the
strongest title result. Title and heading evidence receives more weight than
body evidence within a coverage tier. Repeated evidence is capped, and
excerpts contain up to two highest-value matching lines.

Use literal mode for exact terms and commands:

```bash
scripts/search -- "systemctl restart kb-api"
```

Use question mode for prose questions. It removes grammatical stopwords while
preserving dates, paths, flags, and negation words, then requires all retained
terms in strict mode:

```bash
scripts/search --query "How do I restart --no-verify on 2026-10-03 from /srv/backups/kb"
```

`--relax` permits a second, explicitly labeled any-term pass only when strict
question search has no result. Frontmatter `aliases` can produce a synthetic
routing result naming the matched phrase. `--explain` writes the retained
terms, alias matches, scope, candidate counts, and no-hit or truncation reason
to stderr; JSON remains valid on stdout. The modes cannot be combined.

Search section locators are directly usable with `section`: H2 and H3 results
expose `locator.number` in JSON and append `[section-number=N]` or
`[section-number=N.M]` in normal output. Duplicate H2 headings are therefore
unambiguous. Results for prose before the
first H2 use `locator.command: "--top"` and results synthesized from
frontmatter use `locator.command: "--title"`; retrieve them with
`section --top` or `section --title`.

The default search corpora are `knowledge`, `sources`, and `pending`.
`--archive` adds `archive` and `questions`. `--corpus TYPE` selects one or more
of `knowledge`, `sources`, `pending`, `archive`, or `questions`; repeat the
flag to combine them. `--path PATH` accepts a content-relative file or
directory. `--topic NAME` is a directory under `knowledge/`, such as
`--topic projects`; both filters can be combined and are intersected.
`section --json` returns one object with `path`, `corpus`, `locator`,
`freshness`, `conflict`, `provenance`, and the multiline `content`. Its
`locator.number`
is null for `--top` and `--title`, and its `locator.level` is also null for
those synthetic results.

When a result addresses an H2 or H3 with section metadata, JSON also includes
`section_metadata`. Normal output labels its status, effective date,
superseded locator, and invalid fields. `stale --sections` preserves the
article-level default and adds an opt-in review that reports affected locators
such as `knowledge/operations.md#2`.

`section --max-bytes N` preserves its metadata envelope and emits complete
content lines from the section start. JSON adds `content_truncated` and
`omitted_content_bytes`; text output appends a truncation marker. Retrieve the
section again without the cap when the marker is present. The cap covers
serialized JSON, metadata, and the trailing newline.

Budget serializer measurements on the review host used synthetic Markdown
with a 100 MiB search cap and an 8 KiB section cap. The search comparison used
one matching preamble record per file; the section comparison used one section
with the listed number of body lines, so its cap forced bounded selection in
both JSON and text modes. These are single-run wall-clock measurements, not
portable performance guarantees:

| Command and size | Before | After |
| --- | ---: | ---: |
| `search`, 10 files | 1.70 s | 1.71 s |
| `search`, 100 files | 17.69 s | 17.31 s |
| `section --json --max-bytes 8192`, 100 lines | 0.29 s | 0.29 s |
| `section --json --max-bytes 8192`, 1,000 lines | 3.67 s | 3.54 s |
| `section --text-only --max-bytes 8192`, 100 lines | 0.09 s | 0.09 s |
| `section --text-only --max-bytes 8192`, 1,000 lines | 2.79 s | 1.01 s |

The budget paths now cache serialized search-record byte sizes, account for
the selected prefix incrementally, and serialize that prefix once. Section
selection accounts for escaped JSON lines incrementally, while text selection
appends complete lines and tracks fence state in one pass before serializing
the final candidate once. The measurements show that shell parsing and
metadata traversal dominate these small runs; the output contracts and byte
bounds remain unchanged.

The streaming encoder and selective metadata-cache cleanup were measured on
2026-10-04 against `62d4593`. Each value below is the median of three serial
runs on the same host, after the validation workloads completed. Every paired
before/after stdout response matched byte-for-byte.

The cache corpus used one article with 10 or 100 matching H2 sections and
returned three results with `--text-only --limit 3 --per-file 3`. The JSON search
corpus used 10 or 100 files with one matching preamble per file, unlimited
result/per-file counts, and `--max-bytes 8192`. Section runs used 100 or 1,000
numbered lines containing Unicode, quotes, and backslashes; both sizes forced
truncation at 8,192 bytes. Article verification dates and TTLs were identical.

| Command and size | Before cleanup | After cleanup |
| --- | ---: | ---: |
| Cached search, 10 sections | 0.64 s | 0.19 s |
| Cached search, 100 sections | 5.47 s | 0.88 s |
| Budgeted JSON search, 10 files | 1.81 s | 1.09 s |
| Budgeted JSON search, 100 files | 15.81 s | 8.67 s |
| Budgeted JSON section, 100 lines | 1.82 s | 1.25 s |
| Budgeted JSON section, 1,000 lines | 3.33 s | 1.76 s |
| Budgeted text-only section, 100 lines | 0.33 s | 0.34 s |
| Budgeted text-only section, 1,000 lines | 0.63 s | 0.69 s |

Metadata cache mappings now use direct shell lookups, and cached search restores
only the selected locator. JSON escaping streams checked `od` output through
AWK without encoder scratch files. Text section output did not improve in this
comparison. These timings describe this host and synthetic corpus.

The metadata-loading, string-byte-counting, and rendering simplifications were
measured on 2026-10-05 from `85302cb` to `d838afb`, before the subsequent CRLF
metadata compatibility fix. These are medians of three serial runs after
validation finished, on Linux x86_64 with Bash 5.2.21. Each paired run matched
exit status, stdout, and stderr exactly.

One article contained 10 or 100 matching H2 sections for
`search --text-only --limit 0 --per-file 0 needle`. The file corpus contained
10 or 100 articles with one matching preamble each for
`search --json --limit 0 --per-file 0 --max-bytes 8192 needle`. Bodies contained
Unicode, quotes, and backslashes. All articles used `verified: 2026-10-04` and
`ttl: domain`, with `FRESHNESS_TODAY_EPOCH=1792022400` fixed for both versions.

| Command and size | Before simplification | After simplification |
| --- | ---: | ---: |
| Text search, 10 sections | 0.257 s | 0.186 s |
| Text search, 100 sections | 2.700 s | 1.863 s |
| Budgeted JSON search, 10 files | 1.024 s | 0.978 s |
| Budgeted JSON search, 100 files | 8.561 s | 8.976 s |

Multi-section searches improved in this comparison. The 100-file JSON case was
5% slower. These local measurements do not establish a portable speed guarantee.

### Retrieval evaluation

`evaluate-retrieval` measures whether `search` returns expected evidence. It
uses a versioned JSON fixture and reports per-case status, distinct-section
top-five evidence coverage, first relevant rank, alias routing success,
response bytes, and search latency. Alias routing results are tracked
separately from evidence recovery. The runner performs no model calls and
does not modify the content repository.

Run the public synthetic evaluation from the tooling repository:

```bash
scripts/evaluate-retrieval \
  --fixture tests/fixtures/retrieval-v1/retrieval-v1.json \
  --content-dir tests/fixtures/retrieval-v1/content \
  --baseline tests/fixtures/retrieval-v1/retrieval-v1.baseline.json \
  --json
```

The fixture format is `knowledge-base-retrieval-evaluation` version `1`. The
optional root `evaluation_role` identifies `pre_change`,
`post_implementation`, or `comparison` artifacts; omitted roles are
`unspecified`. Each case contains `query`, optional `query_mode` (`literal` or
`question`), optional `relax`, optional `comparison_group`, `expected_sections`
(content-relative `path` and search `section` locators),
`requires_all_sections`, and `unanswerable`. Question-mode cases exercise the
same normalization and strict/relaxed matching path as `search --query`.

Expected sections are required evidence: the report always records both
whether any and whether all expected sections appear in the top five distinct
sections. A case passes when any expected section is present, unless
`requires_all_sections` is true. An unanswerable case is reported as
`unanswerable` and is excluded from
answerable retrieval scores. If an unanswerable query still returns a ranked
section, its status is `false_positive`, `false_positive_retrieval` is true,
and the aggregate false-positive count/rate and failure entry are reported.
This is a retrieval signal, not an answer-quality judgment.

Before retrieval starts, every answerable expected path and section is checked
against the selected corpus. A missing file or renamed heading is an invalid
fixture, not a retrieval failure.

The evaluator runs two section searches per case. The full-ranking search uses
`--limit 0 --per-file 0` to establish the distinct-section ranking and first
relevant rank. The bounded search uses `--limit 5 --per-file 0` to measure the
response an agent would consume. Full-ranking section count, response bytes,
latency, and first relevant rank describe the first search. Evidence coverage
and `top_five_section_count` use distinct locators from the bounded response;
routing results therefore occupy real display slots. `top_five` is a compact
view of that bounded response, while `bounded_raw_results` preserves its raw
section excerpts.

Pass `--max-bytes N` to run both searches under the same stdout budget. The
report records the budget and omitted result-record counts alongside coverage,
response bytes, and latency. Run without the option to retain the unlimited
baseline comparison.

The committed baseline contains ranked locators and outcome metrics from the
pre-ranking-change implementation, including deterministic response-size
metrics. Generate a replacement only after reviewing the corpus and fixture
changes:

```bash
scripts/evaluate-retrieval \
  --fixture tests/fixtures/retrieval-v1/retrieval-v1.json \
  --content-dir tests/fixtures/retrieval-v1/content \
  --write-baseline tests/fixtures/retrieval-v1/retrieval-v1.baseline.json
```

The report records `fixture_id`, `corpus_id`, `evaluation_role`, and SHA-256
identities for the fixture and Markdown corpus. `--baseline` compares those
identities and lists
changed cases, regressions, and improvements. A regression is a pass-to-fail
outcome, a new false-positive unanswerable retrieval, a loss of any/all
evidence, a lower matched-evidence count, or a first relevant result moving to
a higher-numbered rank. Use `--fail-on-regression` in
a manual ranking experiment;
it does not make evaluation part of the fast Bats suite.

Cases sharing `comparison_group` are paired for strict-versus-relaxed
evaluation. The summary reports discovery-gain groups separately from groups
that add a false positive for an unanswerable query. The committed
`retrieval-question-comparison-v1.json` fixture uses the same
`synthetic-question-corpus-v1` corpus as the ten-case question fixture and
freezes its comparison baseline separately. The separate
`retrieval-question-pre-change-v1.json` fixture uses that same corpus and the
same ten question strings with literal search, freezing the original
pre-question-interface control. The existing
`retrieval-question-v1.baseline.json` remains the explicitly labeled
post-implementation question-mode baseline and is not replaced by either
artifact.

Run the paired comparison with:

```bash
scripts/evaluate-retrieval \
  --fixture tests/fixtures/retrieval-question-v1/retrieval-question-comparison-v1.json \
  --content-dir tests/fixtures/retrieval-question-v1/content \
  --baseline tests/fixtures/retrieval-question-v1/retrieval-question-comparison-v1.baseline.json \
  --json
```

Run the same-corpus pre-change control with:

```bash
scripts/evaluate-retrieval \
  --fixture tests/fixtures/retrieval-question-v1/retrieval-question-pre-change-v1.json \
  --content-dir tests/fixtures/retrieval-question-v1/content \
  --baseline tests/fixtures/retrieval-question-v1/retrieval-question-pre-change-v1.baseline.json \
  --json
```

The public fixture is synthetic. Private question sets may be supplied with
`--fixture` from a separately configured location and must not be committed to
this public repository. When fixture articles change, update expected section
locators in the same change, rerun the evaluator, and review the resulting
baseline before replacing it.

The committed question-mode fixture at
`tests/fixtures/retrieval-question-v1/` contains ten synthetic cases covering
normalization, paraphrase, punctuation, alias routing, current and historical
claims, unresolved conflict, and abstention. Its
`temporal-judgments.json` file is a separate manual-answer annotation: it
records the expected current claim, retained historical claim, supporting
section, and abstention condition. Retrieval coverage and current-claim
selection are evaluated separately; a retrieved superseded section does not
count as a correct current answer.

Retrieval metrics do not establish answer correctness. Perform answer
evaluation manually using the retrieved sections:

1. Record the answer generated from the case's top-five sections and cite each
   supporting `path` and `section` locator.
2. Mark answerable cases `correct`, `partially correct`, or `incorrect` after
   checking the cited sections against the corpus.
3. For `unanswerable` cases, mark whether the answer abstained and whether the
   abstention was correct. An unsupported confident answer fails the case.
4. Store private answers, annotations, and adjudication outside this tooling
   repository. Do not infer answer quality from retrieval scores alone.

Record each manual judgment with this schema in the separately configured
private evaluation location:

```json
{
  "case_id": "cross-article-01",
  "correctness": "correct",
  "supporting_citations": [
    {"path": "knowledge/operations.md", "section": "Restart order"}
  ],
  "abstained": false,
  "abstention_correct": null,
  "notes": "The answer cites both required sections."
}
```

Use `correctness` values `correct`, `partially correct`, or `incorrect` for
answerable cases. For unanswerable cases, set `correctness` to `null`, record
whether the answer abstained, and set `abstention_correct` to `true` or
`false`.

`sync` verifies a successful fetch and an available `origin/<branch>` tracking
ref before reporting counts. Normal and `--status` runs return nonzero when
remote state cannot be verified; they do not report cached counts as current.

## Capture → curate pipeline

1. **Capture.** Call `scripts/observe` during a session (or drop a markdown
   file into `observations/pending/`). Observations are timestamped and
   auto-committed.

2. **Curate.** Have the curator select a bounded set of observations, then
   create its manifest with `scripts/batch start --files FILENAME ...`, review
   them, and merge them into knowledge articles. With no `--files` argument,
   `scripts/batch start` retains its compatibility behavior and selects every
   top-level pending file. Use
   `scripts/pending --preview` for an explicit, bounded view of the
   batch-selectable queue showing age, observation/transcript counts, byte
   volume, metadata warnings, and lexical topic hints. Preview and
   `scripts/batch start` operate on top-level pending files; normal `pending`
   listing, counting, and `--full` access remains recursive. Topic hints are
   suggestions only and do not call an LLM; the curator agent makes the
   selection. Complete items with explicit `scripts/archive --batch ... FILENAME`
   commands; deferred and newly arrived observations remain pending.
   `scripts/batch status BATCH_ID` reports disposition totals, incorporated
   destinations, and deferred filenames from the persisted batch manifest.
   The `curate` skill handles this, or do it manually.

3. **Archive.** Processed items move to `observations/archived/` for
   provenance. **Never delete an observation** — the archive is the complete
   record of everything the base has ever seen.

Topic preview matches explicit `topic:` metadata directly. Otherwise it samples
the title and at most 8 KiB of file content, excluding frontmatter, numeric-only
tokens, and generic words. A topic with multiple meaningful words needs two
distinct matches; a one-word topic needs one. Hints remain suggestions, not
batch selections.

For stale articles, prioritize a stale article that the current curation run
just retrieved when it is related to a pending topic hint or an incorporated
batch destination. Keep a short working list of those paths because the core
does not record access telemetry. Run `scripts/stale` to check the article's
freshness, review the claims that need verification, and change `verified` only
after that review; retrieval alone never refreshes it.

## Host integration

### Skills

| Skill | Scope | Purpose |
|---|---|---|
| `knowledge-base` | Project | Search, browse, observe |
| `curate` | Project | Process observations into articles |

Skills use the Agent Skills `SKILL.md` format. Provider-specific metadata is
kept outside the portable file and provider-specific behavior belongs in a
host adapter.

### Session adapters

The neutral core exposes `session-context`, `session-init`, `session-file`,
`session-append`, and `session-flush`. Adapters translate each host's event
payload and output protocol into those commands. This repository includes
Claude and Codex shell adapters under `scripts/adapters/` and a Pi TypeScript
extension at `scripts/adapters/pi/`.

Host-specific registration remains outside `scripts/install`. That command
installs shared skills and the content-repository hook; it does not install or
configure the Pi extension. Run `scripts/portability-lint` to reject
host-specific details from the shared surface. Use `--client claude`,
`--client codex`, or `--client pi` to verify an adapter exists.

#### Pi installation

Pi support uses the official `@earendil-works/pi-coding-agent` extension API.
Install the local package with Pi:

```bash
export KNOWLEDGE_BASE="$HOME/src/knowledge-base-core"
pi install "$KNOWLEDGE_BASE/scripts/adapters/pi"
```

Pi records the local package path in its settings; no copying or symlinking is
required. `KNOWLEDGE_BASE` must be exported in the environment that launches
Pi so the extension can find the neutral-core commands. The current Pi
package and the adapter package require Node.js `>=22.19.0`. Running the
optional adapter development checks additionally requires npm; the shell core
and `just check` remain independent of them.

The Pi adapter maps its lifecycle to the neutral core as follows:

| Pi event | Adapter behavior |
|---|---|
| `session_start` | Initializes a buffer. `new`, `resume`, and `fork` recover `previousSessionFile`; `reload` recovers the current session file before starting a new buffer. Persistent sessions use stable identities, while ephemeral sessions use generated identities. |
| `message_end` | Appends textual user and assistant messages only. Tool results, unsupported roles, image-only content, and empty text are ignored. A failed append is retried once. |
| `before_agent_start` | Loads `session-context` lazily, caches successful output, and appends it to the current system prompt. |
| `session_shutdown` | Awaits `session-flush`. In-memory state is cleared only after success, so a failed flush leaves the durable buffer available for recovery. |

Pi replaces the extension instance during session replacement and reload
flows. The recovery rules above allow `new`, `resume`, `fork`, and `/reload` to
retain eligible transcripts without depending on in-memory state from the old
instance.

Automatic Pi capture is enabled when `KNOWLEDGE_OBSERVE` is unset or set to
`1`. Set `KNOWLEDGE_OBSERVE=0` to disable capture; the adapter then creates no
buffer and makes no capture calls. A successful duplicate `message_end`
delivery is ignored within one extension instance. Append persistence remains
at least once: if `session-append` writes a line and then reports failure, the
adapter's retry can create a duplicate raw transcript line. A failed shutdown
flush retains the buffer for a later extension instance.

#### Pi development and SDK updates

The Pi checks are optional. From the repository root, use:

```bash
just check       # ShellCheck, portability lint, and Bats; no Node/npm
just pi-check    # Clean Pi dependency install, type-check, and tests
just check-all   # Both independent gates
```

To update the pinned Pi SDK, first confirm the release and its engine
requirement. Inspect the candidate package's extension documentation and
exported declarations before changing `package-lock.json`:

```bash
npm view @earendil-works/pi-coding-agent version engines --json
candidate_dir="$(mktemp -d)"
npm pack --pack-destination "$candidate_dir" \
  "@earendil-works/pi-coding-agent@<version>"
tar -xzf "$candidate_dir"/*.tgz -C "$candidate_dir"
grep -nE 'ExtensionAPI|session_start|message_end|before_agent_start|session_shutdown|previousSessionFile|targetSessionFile' \
  "$candidate_dir/package/dist/core/extensions/types.d.ts" \
  "$candidate_dir/package/docs/extensions.md"
rm -rf "$candidate_dir"

cd scripts/adapters/pi
npm install --save-dev --save-exact @earendil-works/pi-coding-agent@<version>
npm ci
npm run check
```

Review the inspection output before running `npm install`. Stop if the
lifecycle or context contracts have changed; update the adapter and tests
first. The install command then updates the exact development pin and the
lockfile.

Review and commit both `scripts/adapters/pi/package.json` and
`scripts/adapters/pi/package-lock.json`. Do not add npm metadata at the
repository root. The SDK pin must be checked against the current Pi extension
API before the lockfile is updated.

## Testing

The default check gate runs ShellCheck, portability lint, and the Bats suite.
The Pi gate runs separately because it requires Node.js and npm. CI runs both
jobs.

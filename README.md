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
  means 60.
- `sources` — the observation files that fed the article. Append on update.

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
| `pending [--full] [--count] [--preview]` | List observations or preview the curation queue |
| `archive FILENAME [FILENAME ...]` | Archive explicit observations |
| `archive --batch ID --disposition TYPE [--destination PATH] FILENAME` | Complete one persisted batch member |
| `batch start [--files FILENAME ...]|status|defer` | Persist and resume a curator-selected batch |
| `search <term> [term ...] [--json\|--text-only] [--path PATH] [--topic NAME] [--corpus TYPE]` | Search ranked sections with freshness and provenance |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT \| --top \| --title) [--json\|--text-only]` | Extract a section or search fallback with freshness and provenance |
| `section --file FILE --references [--json]` | Return the complete provenance reference list |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `lint [--path DIR] [--strict] [--batch ID]` | Check articles, links, source references, and structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status] [--no-push]` | Pull and push the content repo |
| `status` | Summary stats |
| `evaluate-retrieval --fixture FILE` | Measure retrieval against a versioned question fixture |
| `context` | Compact summary for session injection |
| `session-context` | Produce context for a host adapter |
| `session-init` | Create a session buffer |
| `session-file` | Resolve a session ID to its buffer path |
| `session-append` | Append one message to a session buffer |
| `session-flush` | Convert a buffer into an observation |

All scripts support `--help`.

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

Search terms must occur somewhere in the same file. Complete term coverage is
the primary ranking tier for actual sections, so a section containing all terms
ranks above sections that provide only file-level fallback evidence when terms
are split across sections. An exact frontmatter-title result remains the
strongest title result. Title and heading evidence receives more weight than
body evidence within a coverage tier. Repeated evidence is capped, and
excerpts contain up to two highest-value matching lines.

Search section locators are directly usable with `section`: H2 results expose
`locator.number` in JSON and append `[section-number=N]` in normal output.
Duplicate H2 headings are therefore unambiguous. Results for prose before the
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

### Retrieval evaluation

`evaluate-retrieval` measures whether `search` returns expected evidence. It
uses a versioned JSON fixture and reports per-case status, distinct-section
top-five evidence coverage, first relevant rank, response bytes, and search
latency. The runner performs no model calls and does not modify the content
repository.

Run the public synthetic evaluation from the tooling repository:

```bash
scripts/evaluate-retrieval \
  --fixture tests/fixtures/retrieval-v1/retrieval-v1.json \
  --content-dir tests/fixtures/retrieval-v1/content \
  --baseline tests/fixtures/retrieval-v1/retrieval-v1.baseline.json \
  --json
```

The fixture format is `knowledge-base-retrieval-evaluation` version `1`. Each
case contains `query`, `expected_sections` (content-relative `path` and search
`section` locators), `requires_all_sections`, and `unanswerable`. Expected
sections are required evidence: the report always records both whether any and
whether all expected sections appear in the top five distinct sections. A case
passes when any expected section is present, unless `requires_all_sections` is
true. An unanswerable case is reported as `unanswerable` and is excluded from
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
latency, and first relevant rank describe the first search. Bounded response
`top_five_section_count` are distinct `{path, section}` display values derived from
the full-ranking search locators, which also include numeric H2 or command
selectors when required for disambiguation. `top_five` is kept compact,
the full ranking, while `bounded_raw_results` preserves the bounded search's
raw section excerpts.

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

The report records `fixture_id`, `corpus_id`, and SHA-256 identities for the
fixture and Markdown corpus. `--baseline` compares those identities and lists
changed cases, regressions, and improvements. A regression is a pass-to-fail
outcome, a new false-positive unanswerable retrieval, a loss of any/all
evidence, a lower matched-evidence count, or a first relevant result moving to
a higher-numbered rank. Use `--fail-on-regression` in
a manual ranking experiment;
it does not make evaluation part of the fast Bats suite.

The public fixture is synthetic. Private question sets may be supplied with
`--fixture` from a separately configured location and must not be committed to
this public repository. When fixture articles change, update expected section
locators in the same change, rerun the evaluator, and review the resulting
baseline before replacing it.

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

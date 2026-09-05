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

# Initialize a content repo
scripts/init --path ~/my-knowledge-base

# Or point at an existing one
export KNOWLEDGE_BASE=~/my-knowledge-base

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

The content repo can live anywhere. Set `KNOWLEDGE_BASE` to point at it,
or let it default to `./content` within the knowledge-base-core directory.
`content/` is gitignored here so the two git repos coexist in one tree.

### The two-root pattern

Scripts distinguish two roots, and that split is what lets the tooling be
public while the data stays private:

- **`REPO_ROOT`** (this repo) — finding sibling scripts, reading the infra
  `AGENTS.md`, display in `status` and `context`.
- **`CONTENT_DIR`** (the content repo) — every data path, `resolve_path`,
  lock-file placement, and `locked_commit`, which cds in and runs git there.
  Set by `_lib.sh`; defaults to `$REPO_ROOT/content`, overridable with
  `KB_CONTENT_DIR`.

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

## Scripts

| Script | Purpose |
|---|---|
| `init [--path DIR]` | Initialize a content repo |
| `observe --title "..." --body "..."` | Capture an observation to observations/pending/ |
| `pending [--full] [--count]` | List uncurated observations |
| `archive FILENAME [--all]` | Move observations to observations/archived/ |
| `batch start|status|defer` | Persist and resume a curation batch |
| `search <term> [term ...] [--json\|--text-only]` | Search content, ranked, with freshness and provenance |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT) [--json\|--text-only]` | Extract a section with freshness and provenance |
| `section --file FILE --references [--json]` | Return the complete provenance reference list |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `lint [--path DIR] [--strict]` | Check articles against the structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status]` | Pull and push the content repo |
| `status` | Summary stats |
| `context` | Compact summary for session injection |
| `session-context` | Produce context for a host adapter |
| `session-init` | Create a session buffer |
| `session-file` | Resolve a session ID to its buffer path |
| `session-append` | Append one message to a session buffer |
| `session-flush` | Convert a buffer into an observation |

All scripts support `--help`.

### Retrieval output

`search` and `section` include retrieval metadata by default. `--text-only`
preserves the historical body/line output for callers that cannot consume
metadata. `--json` returns structured output and keeps diagnostics on stderr.
The two modes cannot be combined.

Metadata classifies each result as a curated article, source document, pending
observation, question, or archive. Open and resolved questions use the
`question` corpus with `provenance.state` set to `open` or `resolved`; they are
knowledge gaps or question records, not evidence. Curated articles use
`verified` and their applicable `ttl`; source documents use `synced`. Missing
dates are `unknown`, malformed dates are `invalid`, and neither is reported as
fresh. Stale results remain available and are labeled `stale`.

Curated article `sources` are exposed as article-level references. They identify
the evidence associated with the article and are not claim-level citations.
The default output displays at most five references and reports
`reference_count` and `references_truncated` in JSON. The complete list remains
in the file's `sources:` frontmatter; retrieve it with
`section --file FILE --references [--json]`. Pending and archived observations
are labeled uncurated or archived evidence. Source documents expose their
`canonical` reference when present.

`search --json` returns an object with a bounded `results` array plus
`total_files`, `total_lines`, `returned`, and `truncated`. Each line result
contains `path`, `corpus`, `locator`, `freshness`, `provenance`, and `text`;
`--files` returns one file result with `match_count` and a null locator.
`section --json` returns one object with `path`, `corpus`, `locator`,
`freshness`, `provenance`, and the multiline `content`.

`sync` verifies a successful fetch and an available `origin/<branch>` tracking
ref before reporting counts. Normal and `--status` runs return nonzero when
remote state cannot be verified; they do not report cached counts as current.

## Capture → curate pipeline

1. **Capture.** Call `scripts/observe` during a session (or drop a markdown
   file into `observations/pending/`). Observations are timestamped and
   auto-committed.

2. **Curate.** Create a batch with `scripts/batch start`, review its selected
   observations, and merge them into knowledge articles. Complete items with
   explicit `scripts/archive --batch ... FILENAME` commands; deferred and
   newly arrived observations remain pending.
   The `curate` skill handles this, or do it manually.

3. **Archive.** Processed items move to `observations/archived/` for
   provenance. **Never delete an observation** — the archive is the complete
   record of everything the base has ever seen.

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
Claude and Codex shell adapters under `scripts/adapters/`; OpenCode and Pi
integrations can use the same API from their plugin systems.

Run `scripts/portability-lint` to reject host-specific lifecycle, environment,
and skill metadata from the shared surface. Run it with `--client NAME` to
verify a host adapter exists.

## Testing

```bash
bats tests/
```

Tests run in CI via GitHub Actions on push and PR to main.

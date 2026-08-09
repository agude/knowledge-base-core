# knowledge-base-core

**Knowledge-Base-Core** is an external memory and context layer for Claude
Code sessions. Scripts, skills, and schemas that operate on a separate content
repo.

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
├── skills/             # Claude Code skills
├── tests/              # bats tests
└── .claude/skills      # symlink → skills/

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
  `CLAUDE.md`, display in `status` and `context`.
- **`CONTENT_DIR`** (the content repo) — every data path, `resolve_path`,
  lock-file placement, and `locked_commit`, which cds in and runs git there.
  Set by `_lib.sh`; defaults to `$REPO_ROOT/content`, overridable with
  `KB_CONTENT_DIR`.

Output paths strip `$CONTENT_DIR/`, so users see and pass relative paths like
`knowledge/topic.md`. **Every commit made by a script goes to the content
repo.**

### Pluggable `CLAUDE.md`

`session-start` concatenates this repo's `CLAUDE.md` (how the knowledge base
works) with `content/CLAUDE.md` (project-specific policy) when the latter
exists.

**Order matters:** the content file comes second, so its rules take precedence
— later instructions override earlier ones. Policy like "we never record X"
belongs in `content/CLAUDE.md`, not here.

### Three layers of instruction

| Layer | Loaded | Holds |
|---|---|---|
| `CLAUDE.md` (infra + content) | Every session, injected | Script table, observation trigger rules, pointer to the skills |
| `knowledge-base` skill | On invoke | Lookup workflow, observation practices, attribution, freshness thresholds |
| `curate` skill | On invoke | Curation workflow, article conventions, voice, frontmatter |

Observation *trigger* rules stay in `CLAUDE.md` because an agent has to observe
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
sources:
  - observations/archived/20260412T101500-a1b2.md
---

Standard markdown content. Links use [normal syntax](other-page.md).
```

- `updated` — date of the last curator edit.
- `verified` — date the content was last confirmed accurate. `stale` compares
  this against a per-topic threshold, so it is the field that decides how much
  a reading session should trust the article.
- `sources` — the observation files that fed the article. Append on update.

## Scripts

| Script | Purpose |
|---|---|
| `init [--path DIR]` | Initialize a content repo |
| `observe --title "..." --body "..."` | Capture an observation to observations/pending/ |
| `pending [--full] [--count]` | List uncurated observations |
| `archive FILENAME [--all]` | Move observations to observations/archived/ |
| `search "<query>"` | Search all content |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT)` | Extract a section from an article |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `lint [--path DIR] [--strict]` | Check articles against the structural conventions |
| `status` | Summary stats |
| `context` | Compact summary for session injection |
| `session-start` | SessionStart hook for Claude Code |

All scripts support `--help`.

## Capture → curate pipeline

1. **Capture.** Call `scripts/observe` during a session (or drop a markdown
   file into `observations/pending/`). Observations are timestamped and
   auto-committed.

2. **Curate.** Review pending observations and merge them into knowledge
   articles. The `curate` Claude skill handles this, or do it manually.

3. **Archive.** Processed items move to `observations/archived/` for
   provenance. **Never delete an observation** — the archive is the complete
   record of everything the base has ever seen.

## Claude Code integration

### Skills

| Skill | Scope | Purpose |
|---|---|---|
| `knowledge-base` | Project | Search, browse, observe |
| `curate` | Project | Process observations into articles |

Project skills activate when Claude is working in this repo.

### Session hook

`scripts/session-start` is a [coat-tree][ct] hook that injects `CLAUDE.md`
into Claude's context at session start. It also sets `KNOWLEDGE_OBSERVE=1`
so the session can capture observations, and creates a session-specific
buffer file for batching writes. Install it by symlinking into the
coat-tree hooks directory (the dotfiles installer handles this). coat-tree
is not required. If you prefer, point Claude Code's `SessionStart` hook
in `settings.json` directly at `scripts/session-start`.

[ct]: https://github.com/agude/coat-tree

## Testing

```bash
bats tests/
```

Tests run in CI via GitHub Actions on push and PR to main.

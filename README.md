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

content/                # separate git repo
├── knowledge/          # curated articles (organized by topic)
├── inbox/              # raw observations, uncurated
└── archived/           # processed inbox items (provenance)
```

The content repo can live anywhere. Set `KNOWLEDGE_BASE` to point at it,
or let it default to `./content` within the knowledge-base-core directory.

## Content structure

Knowledge articles live in `knowledge/`. Organization is by topic
subdirectories, with frontmatter tags for cross-cutting concerns.

```yaml
---
title: Sync Topology
tags: [infrastructure, nas, syncthing, backup]
created: 2026-04-12
updated: 2026-04-12
---

Standard markdown content. Links use [normal syntax](other-page.md).
```

## Scripts

| Script | Purpose |
|---|---|
| `init [--path DIR]` | Initialize a content repo |
| `observe --title "..." --body "..."` | Capture an observation to inbox/ |
| `pending [--full] [--count]` | List uncurated inbox items |
| `archive FILENAME [--all]` | Move inbox items to archived/ |
| `search "<query>"` | Search all content |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT)` | Extract a section from an article |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `status` | Summary stats |
| `context` | Compact summary for session injection |
| `session-start` | SessionStart hook for Claude Code |

All scripts support `--help`.

## Capture → curate pipeline

1. **Capture.** Call `scripts/observe` during a session (or create a
   markdown file in `inbox/`). Observations are timestamped and
   auto-committed.

2. **Curate.** Review inbox items and merge them into knowledge articles.
   The `curate` Claude skill handles this, or do it manually.

3. **Archive.** Processed items move from `inbox/` to `archived/` for
   provenance. Never delete inbox items.

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
coat-tree hooks directory (the dotfiles installer handles this).

[ct]: https://github.com/agude/coat-tree

## Testing

```bash
bats tests/
```

Tests run in CI via GitHub Actions on push and PR to main.

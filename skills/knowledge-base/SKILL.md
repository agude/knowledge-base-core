---
name: knowledge-base
description: Search and record durable facts a future agent session would need -- domain rules, system behavior, people and ownership, the user's preferences and conventions, and why things were decided. Use before starting any task, to check what is already known. This is the agent's durable memory (~/Knowledge); it is NOT the wiki (~/Wiki, written for the user to read) and NOT Johnny Decimal (~/Documents, which files artifacts like PDFs and receipts).
---

# Knowledge Base

You have access to a knowledge base at `$KNOWLEDGE_BASE`. It contains curated
articles, source documents, and pending observations. All interaction goes
through scripts in `$KNOWLEDGE_BASE/scripts/`.

## Which system is this

Three systems overlap and putting something in the wrong one is how it
gets lost. The split is by **audience**, not by topic:

| System | Audience | Holds |
|---|---|---|
| **Knowledge base** (`~/Knowledge`) | agent sessions | Curated articles loaded for context: domain rules, system behavior, people, preferences, decisions |
| Wiki (`~/Wiki`) | The user, reading | "How my stuff works" — architecture, runbooks, decision logs, written as prose for a person |
| Johnny Decimal (`~/Documents`) | The user, filing | Artifacts: PDFs, scans, receipts, project documents |

This skill is the first one. If what you learned is something a *future
session* needs in order to work — record it here. If it is something the
user would sit down and read — that is the wiki. If it is a file — that
is Johnny Decimal.

Each agent client's own per-project auto-memory is a fourth store. Keep it for
interaction-style feedback ("stop explaining before you act"); anything
durable about systems, domain, or people belongs here, where it is
curated, dated, and searchable across projects.

## Looking things up

Start by searching, not browsing.

1. **Search first.** `$KNOWLEDGE_BASE/scripts/search <term> [term ...]`
   returns matches across knowledge articles, source documents, and pending
   observations. Output format: `<file> | <section> | <matched line>`.
   - Several terms are ANDed: the file must contain all of them.
   - Results are ranked; a term in the title outranks one in a heading,
     which outranks one in the body.
   - Output is capped at 20 lines. Use `--limit N`, or `--files` to see
     just which articles matched.
   - `--archive` widens the search to archived observations and open
     questions. The default corpus is curated articles only.

2. **Narrow with toc.** If search gives too many results or you need to
   explore a topic area, use `$KNOWLEDGE_BASE/scripts/toc` to scan section names.
   - `toc --depth 1` — just topic names (one line per file)
   - `toc --depth 2` — H2 section names (the primary content units)
   - `toc --depth 3` — H3 subsections with dot numbers (1.1, 1.2)
   - `toc --path knowledge/some-dir/` — scope to a subdirectory
   - `toc --dirs` — show the file/directory tree

3. **Load a section.** `$KNOWLEDGE_BASE/scripts/section --file <path> --number N` loads one
   H2. Use `--number N.M` for an H3 subsection. Use `--heading "text"` for
   a case-insensitive substring match on any heading level.

**Always load the minimum content needed.** Do NOT read entire knowledge
files. The toc → section hierarchy is the compression scheme — scan the
index, then load only what's relevant.

## Recording observations

When you learn something non-obvious during a task — the user corrects you,
states a preference, shares domain knowledge, or you discover something
unexpected — capture it immediately:

```bash
$KNOWLEDGE_BASE/scripts/observe --title "<one-line summary>" --body "<details>"
```

### Rules

- **Only observe if `KNOWLEDGE_OBSERVE=1`** is set in your environment.
  Check before calling. Subagents do not get this variable.
- **Capture immediately.** Do not wait until the task is done.
- **One observation per concept.** Three things learned = three calls.
- **Be specific.** "Use uv + PEP 723 for standalone scripts" is good.
  "Use modern tooling" is bad.
- **Include concrete details:** exact commands, error messages, version
  numbers, who told you.
- **Attribute when possible.** If the user says "Dana told me X," include
  Dana's name and role in the observation body. The curator preserves
  inline attribution in knowledge articles.

### What to observe

- Corrections ("no, we don't do X, we do Y because...")
- Domain rules and business logic
- People and roles ("Jake owns the deploy pipeline")
- Preferences and conventions ("always use snake_case in this repo")
- System behavior and gotchas
- Historical context ("we switched from X to Y after the outage in March")

Don't observe ephemeral state ("the build is broken right now") or things
already captured in the knowledge base.

## Recording questions

When you notice a gap — a system, person, or process referenced but not
covered in the knowledge base — flag it:

```bash
$KNOWLEDGE_BASE/scripts/ask --title "Who owns the feature-flag service?" --context knowledge/deploys/canary.md
```

- `--context` is optional. Links the question to a knowledge area.
- `--body` adds detail about why the gap matters.

Questions are reviewed during curation passes.

## Freshness

Knowledge articles carry a `verified` date and a `ttl` in frontmatter.
`ttl` is the article's own answer to how fast it rots:

| `ttl` | Stale after | Typical content |
|---|---|---|
| `people`, `status` | 14 days | People, roles, org, active projects |
| `process` | 60 days | Processes and workflows |
| `domain` | 180 days | Domain rules, system behavior |
| *absent* | 60 days | Unclassified |

`$KNOWLEDGE_BASE/scripts/stale` lists what is past its threshold.

If an article is past its `ttl`, treat its claims with skepticism and
verify against live sources before acting on them. Source documents under
`sources/` use `synced` instead — the date the local copy was pulled.

## Script reference

All scripts are at `$KNOWLEDGE_BASE/scripts/<name>`.

| Script | Purpose |
|---|---|
| `search <term> [term ...]` | Search all content, ranked |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT)` | Extract a section |
| `observe --title "..." --body "..."` | Record an observation |
| `pending [--full] [--count]` | List uncurated observations |
| `batch start|status|defer` | Persist and resume a curation batch |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `archive FILENAME [--all]` | Move observations to archived |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `lint [--path DIR] [--strict]` | Check articles against the structural conventions |
| `commit -m "..."` | Commit curation work under the write lock |
| `sync [--status]` | Pull and push the content repo |
| `init [--path DIR]` | Initialize an empty content repo |
| `status` | Summary stats |
| `context` | Compact summary for session injection |

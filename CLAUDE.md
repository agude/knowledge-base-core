# Knowledge Base

An external memory and context layer for Claude sessions on this machine.
Located at `$KNOWLEDGE_BASE` (this directory).

The knowledge base contains curated articles about the user's systems, domain,
preferences, tooling, etc. --- context that would otherwise take multiple
rounds of questions to establish. A quick `search` or `toc` scan up front
often saves significant back-and-forth.

## Scripts

All paths are `$KNOWLEDGE_BASE/scripts/<name>`.

| Script | Purpose |
|---|---|
| `search "<query>"` | Search all content |
| `toc [--depth N] [--path DIR] [--flat] [--dirs]` | List topics and sections |
| `section --file FILE (--number N \| --heading TEXT)` | Extract a section |
| `observe --title "..." --body "..."` | Record an observation |
| `pending [--full] [--count]` | List uncurated observations |
| `ask --title "..." [--context FILE] [--body "..."]` | Record a question |
| `questions [--path DIR] [--file F] [--full] [--all]` | List open questions |
| `resolve --file F [--answer "..."]` | Resolve a question |
| `archive FILENAME [--all]` | Move observations to archived |
| `stale [--days N] [--path DIR]` | List articles needing re-verification |
| `init [--path DIR]` | Initialize an empty content repo |
| `status` | Summary stats |
| `context` | Compact summary |

Use the `knowledge-base` skill for detailed lookup and recording workflows.
Use the `curate` skill to process pending observations into knowledge
articles.

## Observations

When the user corrects you, states a preference, or you discover something
non-obvious during a task, capture it immediately:

```
scripts/observe --title "<one-line summary>" --body "<details>"
```

- **Only observe if `KNOWLEDGE_OBSERVE=1`** is set in your environment.
  Subagents do not get this variable. Only top-level sessions observe. Scripts
  check for this and won't write if its not set.
- Capture IMMEDIATELY. Do not wait until the task is done.
- Be specific. One observation per concept. Include concrete details.

## Rules

- **Use scripts, not direct file I/O**, for observations and reading.
- **Do NOT edit entries directly.** Curated entries under `content/knowledge/`
  are maintained exclusively by the curation agent.
- **The curator is the exception.** It reads and writes knowledge files
  directly via its own skill.

## Project-specific rules

This knowledge base may include project-specific instructions in
`content/CLAUDE.md`. Those instructions take precedence over the defaults
above when they conflict.

# Knowledge Base

Previously learned facts about this user's work: business logic, institutional
history, technical stack, people and ownership, and durable preferences. The
knowledge base is located at `$KNOWLEDGE_BASE`.

**Search it before starting any task.** Team ownership, system behavior,
domain rules, data tables, and process details are often already here.

```bash
$KNOWLEDGE_BASE/scripts/search <term> [term ...]   # start here
$KNOWLEDGE_BASE/scripts/toc --path knowledge/<area>  # titles in one area
$KNOWLEDGE_BASE/scripts/section --file <path> --number N   # extract a section
$KNOWLEDGE_BASE/scripts/observe --title "..." --body "..." # record an observation
```

Load the minimum: scan the index, then pull only the section you need. Do not
read whole articles.

Invoke the `knowledge-base` skill for the full script reference, lookup
workflow, and freshness rules. Invoke the `curate` skill to process pending
observations into articles.

## Observations

Observation triggers live here because a session has to notice them
spontaneously; it cannot load a skill first.

```bash
$KNOWLEDGE_BASE/scripts/observe --title "<one-line summary>" --body "<details>"
```

- **Capture immediately.** Do not wait until the task is done.
- **One observation per concept.** Three things learned means three calls.
- **Be specific.** Record exact commands, error messages, versions, and
  attribution when relevant.
- Skip ephemeral state and anything already in the knowledge base.

`KNOWLEDGE_OBSERVE=0` disables automatic observation capture. Explicit
observation commands remain available when the session is configured to allow
them.

## Freshness

Articles carry `verified` and `ttl` metadata. Past the relevant TTL, verify
claims against live sources before acting on them. `scripts/stale` lists
articles needing re-verification.

## Where this ends

Split by audience. **Here**: durable facts a future session needs to work.
**`~/Wiki`**: material the user would sit down and read. **`~/Documents`**:
artifacts such as PDFs, scans, receipts, and project documents. Interaction
style belongs in auto-memory; durable system, domain, and people facts belong
here.

## Rules

- **Use the scripts, not direct file I/O**, for reading and recording.
- **Do NOT edit `content/knowledge/` directly.** Those articles are the
  curator's; the `curate` skill is the only writer.
- `content/AGENTS.md`, when present, adds project-specific policy and takes
  precedence over this file. `content/CLAUDE.md` remains a compatibility name
  and is also accepted.

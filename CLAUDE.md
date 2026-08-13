# Knowledge Base

Previously learned facts about this user's work: business logic, institutional
history, technical stack, processes, people, and domain knowledge. Located at
`$KNOWLEDGE_BASE`.

**Search it before starting any task.** Team ownership, system behavior,
domain rules, data tables, process details — the answers are often already
here, and finding them costs one command instead of an investigation.

```bash
$KNOWLEDGE_BASE/scripts/search <term> [term ...]   # start here
$KNOWLEDGE_BASE/scripts/toc --path knowledge/<area>  # titles in one area
$KNOWLEDGE_BASE/scripts/section --file <path> --number N   # load one section
$KNOWLEDGE_BASE/scripts/observe --title "..." --body "..." # record a fact
```

Load the minimum: scan the index, then pull only the section you need. Do not
read whole articles.

Invoke the **`knowledge-base` skill** for the full script reference, lookup
workflow, and freshness rules. Invoke the **`curate` skill** to process
pending observations into articles.

## Observations

Observation triggers live here rather than in the skill because an agent has
to notice spontaneously — it cannot load a skill to learn that it should.

When the user corrects you, states a preference, or you discover something
non-obvious during a task, capture it immediately:

```bash
$KNOWLEDGE_BASE/scripts/observe --title "<one-line summary>" --body "<details>"
```

- **Capture immediately.** Do not wait until the task is done.
- **One observation per concept.** Three things learned, three calls.
- **Be specific.** Exact commands, error messages, version numbers, who said
  it. "Use uv + PEP 723 for standalone scripts" is good; "use modern tooling"
  is not.
- Skip ephemeral state ("the build is broken right now") and anything already
  in the base.

Explicit `observe` calls always work. `KNOWLEDGE_OBSERVE` only controls
automatic session capture.

## Freshness

Articles carry `verified` and a `ttl` (14/60/180 days by content type).
Past it, verify against live sources before acting. `scripts/stale` lists
what has expired.

## Where this ends

Split by audience. **Here**: what a future Claude session needs to work.
**`~/Wiki`**: what the user would sit down and read. **`~/Documents`**:
artifacts (PDFs, scans). **Auto-memory**: interaction style only —
anything durable about systems, domain, or people belongs here.

## Rules

- **Use the scripts, not direct file I/O**, for reading and recording.
- **Do NOT edit `content/knowledge/` directly.** Those articles are the
  curator's; the `curate` skill is the only writer.
- `content/CLAUDE.md`, when present, adds project-specific policy and takes
  precedence over this file.

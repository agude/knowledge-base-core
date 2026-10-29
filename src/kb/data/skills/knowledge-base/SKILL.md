---
name: knowledge-base
description: Search the user's knowledge base for prior facts and decisions, and record durable facts or unanswered questions with kb.
---

# Knowledge Base

Use this skill when starting a task or when a task needs a fact that may be in
the knowledge base. The knowledge base holds durable facts from past sessions:
systems, domain rules, people, preferences, and decisions. The content policy
is in the repository's `AGENTS.md`.

## Search

Start with a focused query:

```sh
kb recall backup retention
```

`kb recall QUERY...` prints the best curated sections in full, with a locator,
heading, freshness, and sources. It may list matching pending observations and
open questions under `Uncurated`. If no curated section matches, it returns
the best observations, transcripts, and questions as evidence. Read a printed
locator directly:

```sh
kb read knowledge/infra/backups.md#2
```

Use `kb map PATH` to see the articles and section locators in an area. Use
`kb questions --context PATH` to list open questions about that area and its
descendants. Use `kb evidence QUERY...` when you need supporting observations,
transcript turns, or resolved questions. Evidence rows include a locator, date,
kind, and title or excerpt; `kb read` accepts the locator unchanged. Add
`--kind`, `--since`, or `--until` when a narrower evidence search helps.

Search again when the task reaches a new system, person, domain rule, or past
decision. Load only the sections needed for the task.

## Record a durable fact

Record a fact when the user corrects you or you learn something non-obvious
that a future session needs. First check whether the knowledge base already
holds it. Skip temporary status, task details that will expire, and facts
already recorded. Never include credentials, tokens, or other possible
secrets. `kb observe` checks the title and body and refuses text that may hold
a secret.

```sh
kb observe --title "Backup restore order" --body "Restore the catalog before the media files."
```

`--body -` reads UTF-8 text from standard input. A successful command writes
one observation under `observations/pending/` and commits it. Do not record on
behalf of a subagent; subagents do not record.

## Record a gap

Use `kb gap` when the task needed an answer that the knowledge base does not
hold and you could not find elsewhere. Give the best-known area as context; it
may not exist yet.

```sh
kb gap --title "Where is the backup disk?" \
  --body "The backup disk location is not recorded." \
  --context knowledge/infra
```

The question is committed under `questions/open/`. Use `kb questions
--context PATH` to find it later. `--body -` reads UTF-8 text from standard
input. Do not put possible secrets in a title or body.

## Curation

The user starts curation. Do not start a batch as part of ordinary task work.
When the user asks you to curate pending observations, follow the separate
`curate` skill.

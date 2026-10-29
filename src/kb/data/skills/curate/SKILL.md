---
name: curate
description: Process pending knowledge-base observations into checked articles, settle each batch item, and publish the result.
---

# Curate the knowledge base

The user starts a curation run. Use this skill only when the user asks you to
curate. Curation edits articles in the content repository and publishes a
batch in one commit.

## Start or resume a batch

Start by synchronizing with the remote and selecting a bounded set of pending
observations:

```sh
kb curate start --max-bytes 65536
```

Use the `RUN` printed by the command in every later command. The byte budget
counts each selected observation's original UTF-8 bytes, including front
matter. Automatic selection follows creation date; supplied filenames keep
their order. `start` requires a clean worktree and synchronizes with `origin`
before it creates the batch. For explicitly requested offline work, use
`kb curate start --no-sync --max-bytes N`; this creates a local batch that is
not synchronized.

Inspect progress and the next item with:

```sh
kb curate status RUN
kb curate next RUN
```

`status` shows batch progress and publication state without contacting the
remote. `next` prints the full observation, up to three matching curated
sections, and up to five related open questions. Use `--query TEXT` when a
different query better describes the observation.

If a prior command was interrupted, run `status` first. When it prints an
exact recovery command for an archive intent, repeat that command exactly.
Then inspect the batch again before continuing. Do not recreate a batch over
an unsettled one.

## Process each observation

Read the whole observation and the context from `next`. Use `kb recall`,
`kb evidence`, and `kb questions` to check for existing knowledge, supporting
evidence, and open questions. Verify time-sensitive claims against current
sources. Preserve durable facts, decisions, and useful attribution. Do not
copy secrets or temporary task details into articles.

For an incorporated fact, edit the relevant article directly. Add the future
archive locator to its `sources`, such as
`observations/archived/FILENAME.md#1`; the target appears when completion
archives the observation. A commit hook sets `updated` to today's UTC date on
staged articles when needed. Editing does not verify a fact and never changes
`verified` or `ttl`.

Use `kb verify ARTICLE` only after checking the article against current
evidence. A valid `ttl` is required. If the article has no valid `ttl`, supply
`--ttl` with `people`, `status`, `process`, `domain`, or a positive day count
up to 1,000,000. Choose the period that fits how quickly the fact may change.
`kb lint` checks article structure, metadata, and local references before the
batch is published.

Settle each item with exactly one outcome:

```sh
kb curate complete RUN FILENAME --disposition incorporated LOCATOR...
kb curate complete RUN FILENAME --disposition duplicate LOCATOR...
kb curate complete RUN FILENAME --disposition ephemeral --reason TEXT
kb curate defer RUN FILENAME --reason TEXT
kb curate drop RUN FILENAME --reason TEXT
```

Use `incorporated` when the durable fact is in an article. It accepts a whole
article or readable section. Use `duplicate` when the article already records
the same fact; name a numbered section. Both outcomes accept multiple
destinations. Use `ephemeral` when the observation has no durable value; give a
brief, single-line reason. Use `defer` when more research or a later decision
is needed and the input is unchanged. Use `drop` only when another writer
removed or changed the selected input; explain what happened. Defer and drop
reasons and completion destinations are checked for possible secrets.

Resolve an open question with `kb resolve QUESTION --answer TEXT
--destination LOCATOR` when evidence supports an answer, or use `--obsolete`
when the question no longer applies. Do not mark an article verified just
because it was edited or because the observation says it is true.

## Finish and publish

After every selected item is completed, deferred, or dropped, review `status`,
run `kb lint` on changed articles, and finish the batch:

```sh
kb curate status RUN
kb curate finish RUN
```

`finish` validates the publication set, commits it once, then fetches, rebases,
and pushes. It refuses pending work, interrupted archives, staged changes,
and files outside the batch. If publication fails after the local commit,
resolve the reported cause and run `kb sync` or repeat `kb curate finish RUN`;
the repeat pushes the existing commit without creating another. Use
`--no-push` only when the user requests a local commit or the machine is
offline. A later `kb sync` publishes it.

---
name: curate
description: Process pending knowledge-base observations into checked articles, settle each batch item, and publish the result.
---

# Curate the knowledge base

The user starts a curation run. Use this skill only when the user asks you to
curate. Curation edits articles in the content repository and publishes each
batch in one commit. A run continues through successive batches until the
pending queue is empty; see "Repeat until the queue is empty".

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

For an incorporated fact, write the text and let `kb edit` place it. Do not
splice text into article files by hand. Pass the text on stdin:

```sh
kb edit replace ARTICLE#N    # rewrite a whole section; use this to edit an entry
kb edit append ARTICLE#N     # add paragraphs or bullets at the end of a section
kb edit insert ARTICLE --after N     # add a new section; --after top for the first H2
kb edit move ARTICLE#N --after M     # reorder or regroup sections
kb edit remove ARTICLE#N
```

To change one bullet or add an entry mid-section, read the section with
`kb read`, rewrite the whole section, and `replace` it. Several headings in the
text split a section that is too long. `replace` keeps the section's metadata
comment when the rewrite omits it. Each edit prints the locators it wrote and
any section it renumbered; complete with the printed locator, never a number
counted by hand.

Completion adds the archive locator to each destination's `sources`; do not
add it yourself. A commit hook sets `updated` to today's UTC date on staged
articles when needed. Editing does not verify a fact and never changes
`verified`. When `kb edit` notes that an edited article has no `ttl`, set one
with `kb edit ttl ARTICLE TTL`, choosing the period that fits how quickly its
facts change.

Use `kb verify ARTICLE` only after checking the article against current
evidence. A valid `ttl` is required. If the article has no valid `ttl`, supply
`--ttl` with `people`, `status`, `process`, `domain`, or a positive day count
up to 1,000,000. `kb verify` refuses an article with section-level `verified`
metadata; use `kb edit ttl` there. `kb lint` checks article structure,
metadata, and local references before the batch is published.

Settle each item with exactly one outcome:

```sh
kb curate complete RUN FILENAME --disposition incorporated LOCATOR...
kb curate complete RUN FILENAME --disposition duplicate LOCATOR...
kb curate complete RUN FILENAME --disposition ephemeral --reason TEXT
kb curate defer RUN FILENAME --reason TEXT
kb curate drop RUN FILENAME --reason TEXT
```

If a recorded destination is wrong, correct it before finishing:

```sh
kb curate amend RUN FILENAME LOCATOR...
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
run `kb lint --require-ttl` on changed articles, and finish the batch:

```sh
kb curate status RUN
kb curate finish RUN
```

`finish` renumbers a destination whose section moved when its heading is still
unique, and names `kb curate amend` for any other changed destination. It
validates the publication set, commits it once, then fetches, rebases, and
pushes. It refuses pending work, interrupted archives, staged changes,
and files outside the batch. If publication fails after the local commit,
resolve the reported cause and run `kb sync` or repeat `kb curate finish RUN`;
the repeat pushes the existing commit without creating another. Use
`--no-push` only when the user requests a local commit or the machine is
offline. A later `kb sync` publishes it.

## Repeat until the queue is empty

One batch is bounded by `--max-bytes`, so it may not hold every pending
observation. After `finish` succeeds, run `kb curate start --max-bytes 65536`
again and repeat the process and finish steps for the new batch. Continue
until one of these conditions ends the run:

- `start` prints `No pending observations.` The queue is empty.
- Every observation in a new batch was already deferred earlier in this run,
  and none can now be settled. Defer them again, finish the batch, and report
  the deferred filenames and reasons to the user.

Deferred observations stay in `observations/pending/`, so later batches select
them again.

The `start` report lists each observation larger than the budget under
`Larger than budget` with an exact command that selects it alone, such as
`kb curate start --max-bytes 70000 FILENAME`. When `start` prints
`No observations fit --max-bytes N.`, only such observations remain. Run the
printed command for each one in turn, processing and finishing each batch.

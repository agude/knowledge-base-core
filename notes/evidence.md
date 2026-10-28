# Evidence

Measurements taken on 2026-10-26 on this machine. They describe the bash
system's use, so they show where it cost round trips, not what agents need.

## Content repository (`~/Knowledge/content`)

| Measure | Value |
|---|---|
| Curated articles | 210 |
| Stale articles (`verified` older than `ttl`) | 121; 98 have no `ttl` (60-day default); 43 were edited in the last 30 days; median 27 days over |
| Open / resolved questions | 44 / 13 |
| Question `source` values | `curator` 50, `session` 7 |
| Pending observations | 56, all top level (no subdirectories) |
| Archived observations | 2,489; 1,433 cited by some article's `sources` |
| Observation `source` values (archived) | `session-transcript` 1,387, `session` 789, untagged 312, `test` 1 |
| Median observation size | explicit 0.8 KB, transcript 3.9 KB |
| Dispositions, explicit observations | incorporated 408, duplicate 53, ephemeral 31, processed 3 |
| Dispositions, transcripts | incorporated 157, duplicate 33, ephemeral 47 |
| Commits / curation commits | about 2,600 / 114 |
| Old transcript observation front matter | `title`, `source`, `created` only; no session ID |

## Command use (Claude Code and Codex transcripts, development sessions excluded)

Script: `notes/scripts/command_usage.py`. Option counts are noisy below
about 5 because some quoted multi-line commands parse imperfectly.

| Command | Calls | Sessions | Main options |
|---|---:|---:|---|
| `search` | 2,208 | 484 | `--limit` 836, `--archive` 55, `--query` 49, `--path` 49, `--max-bytes` 45, `--per-file` 42, `--corpus` 38, `--text-only` 32, `--files` 29, `--topic` 26, `--relax` 14, `--json` 2 |
| `section` | 1,117 | 264 | `--file` 1,261, `--number` 1,016, `--text-only` about 100, `--heading` 91, `--top` 55, `--references` 36 |
| `observe` | 595 | 182 | `--title`, `--body` |
| `toc` | 358 | 171 | `--path` 249, `--depth` 230 |
| `pending` | 238 | 40 | `--count` 50, `--full` 30, `--preview` 30 |
| `lint` | 208 | 30 | `--path` 148, `--batch` 97 |
| `questions` | 105 | 28 | `--path` 78 |
| `archive` | 85 | 28 | `--batch` 55, `--disposition` 54, `--no-commit` 45, `--destination` 35 |
| `sync` | 78 | 40 | |
| `commit` | 63 | 30 | `-m` |
| `batch` | 66 | 24 | `status` 40, `start --files` 22 |
| `status` | 39 | 28 | |
| `stale` | 24 | 17 | `--path` 13, `--sections` 5 |
| `ask` | 17 | 9 | `--context` 11, `--body` 11 |
| `resolve` | 3 | 2 | |

What followed a `search`: another `search` 1,234, `section` 287, `observe`
224, `toc` 112.

## Claude Code transcripts (`~/.claude/projects`, 101 main sessions, 19 days)

| Part | Total | Median per session |
|---|---:|---:|
| Whole files | 422 MB | 1.5 MB |
| User and assistant text | 2.5 MB | 10 KB |
| Tool-call inputs | 8.9 MB | 23 KB |
| Tool results | 44.1 MB (`Read` 28, `Bash` 15) | 164 KB |
| Thinking text | 0.1 MB | 0 |

- Retention: `cleanupPeriodDays` unset (default 30); oldest file 2026-10-07.
- Gzip ratio on raw files: about 0.44.
- Subagent transcripts: 54 files under `<session>/subagents/`.
- Resumed conversations append to the same file under the same session ID:
  20 of 102 files span more than one day; no file contains another
  session's ID; no message uuid appears in two files.
- Not yet checked: what `--fork-session` writes.
- Codex: 944 session files in `~/.codex/sessions`, 1.8 GB, oldest 2026-08-17.

## Hook wiring on this machine

- `~/.claude/settings.json` sends every event to `coat-tree`
  (`~/.local/share/coat-tree/dispatch.sh`), which runs
  `~/.config/coat-tree/hooks.d/<Event>/NNN.*` in order and merges outputs by
  Claude Code's rules.
- Knowledge-base entries: `PreToolUse/010.knowledge` (symlink to the old
  `pretool-allow`); `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`
  `010.knowledge.sh` (dotfiles shims duplicating the old adapters).
- `KNOWLEDGE_BASE=$HOME/Knowledge` (the old tooling checkout) is exported by
  `~/.dotfiles/shared/sharedrc.d/004.tool_repos.sh`.
- OpenCode and Pi capture through plugins in the dotfiles.

## Transcript schema measurement (2026-10-26)

Script: `notes/scripts/measure_transcript_shapes.py`. Read-only scan; it prints
aggregate counts and does not write transcript content. Counts are a point-in-
time sample; Codex files changed during repeated scans.

### Claude Code

- 108 main files and 60 `subagents/agent-*.jsonl` files; 0 malformed lines.
- Record types: `ai-title` 4,241; `api-request` 9,918; `api-request-blob`
  14,463; `api-request-shape` 179; `assistant` 26,652; `atis-latch` 6,646;
  `attachment` 28,821; `cost-state` 115; `file-history-delta` 505;
  `file-history-snapshot` 882; `last-prompt` 6,757; `mode` 6,642;
  `permission-mode` 6,640; `queue-operation` 816; `relocated` 14; `system`
  2,402; `tools-used` 11; `user` 14,683; `worktree-state` 10.
- Top-level `assistant` records carried 26,652 text messages and 13,060
  `tool_use` blocks. Top-level `user` records carried 14,683 text messages,
  13,059 `tool_result` blocks, 476 `isMeta: true` records, and 2,254
  `isSidechain: true` records. `attachment` records carried 2,908 sidechain
  markers. `api-request-blob` carried 14,453 nested text records, 4,720
  `tool_use` blocks, and 741 `tool_result` blocks; it is not a top-level
  `user` or `assistant` message type.
- `assistant` records had 3,934 `isSidechain: true` markers. No main file had
  a sidechain record; the sidechain records were in the separate subagent
  files.
- Tool names: `Bash` 14,434; `Edit` 2,050; `Read` 1,201; `Write` 624;
  `WebFetch` 332; `WebSearch` 305; `Agent` 72; `Monitor` 69; `Skill` 50;
  `SendMessage` 30; `ToolSearch` 81; `SubagentHandback` 78; `TaskStop` 14;
  `AskUserQuestion` 8; `SendFeedback` 2; `EnterWorktree` 1; `ListAgents` 3;
  `bash` 1.
- 40,859 kept user/assistant messages: every one had a `uuid`; none repeated
  within a file or across files.

### Codex

- 953 rollout files, 1,001 `session_meta` records, and 953 distinct primary
  session IDs; 0 malformed lines. Every file has exactly one `session_meta.id`
  matching its rollout filename, and it is the first metadata record. 48 files
  have a second, distinct `session_meta.id` at the start of the file.
- Record types: `compacted` 233; `event_msg` 162,615;
  `inter_agent_communication_metadata` 1,020; `response_item` 138,586;
  `session_meta` 1,001; `token_usage_record` 34,947; `turn_context` 6,783;
  `world_state` 1,432.
- Item types: `additional_tools` 7; `agent_message` 3,553;
  `agent_reasoning` 58; `compaction` 95; `context_compacted` 12;
  `custom_tool_call` 31,440; `custom_tool_call_output` 31,439;
  `function_call` 1,708; `function_call_output` 1,708; `item_completed`
  98,565; `message` 23,006; `reasoning` 47,994; `task_complete` 6,443;
  `task_started` 6,591; `thread_goal_updated` 40;
  `thread_settings_applied` 5,933; `token_count` 40,143; `turn_aborted` 102;
  `user_message` 2,364.
- Tool names: `exec` 31,440; `send_message` 601; `wait_agent` 500; `wait` 260;
  `followup_task` 131; `spawn_agent` 85; `list_agents` 73; `sleep` 33;
  `request_user_input_async` 17; `interrupt_agent` 8.
- The 1,708 `function_call` items are named collaboration tools: `send_message`
  601; `wait_agent` 500; `wait` 260; `followup_task` 131; `spawn_agent` 85;
  `list_agents` 73; `sleep` 33; `request_user_input_async` 17;
  `interrupt_agent` 8. Shell calls are `custom_tool_call` items named `exec`.
- Injected-context markers in user messages: `AGENTS.md` 1,523 in
  `response_item.message` and 332 in `event_msg.user_message`;
  `<environment_context>` 989 and `<codex_internal_context>` 102 in
  `response_item.message`.
- Subagent threads are separate rollout files. `session_meta.parent_thread_id`
  appeared in 520 files; all 520 IDs matched another primary rollout session.
  `agent_path` appeared in 85 files. `forked_from_id` appeared in 61 files;
  all 61 pointed to a local primary session.
- All 51,698 kept messages had IDs and no ID repeated within a file. 112 IDs
  were shared across files; all were shared across distinct fork-related
  sessions. There were 132 file pairs sharing IDs: 85 had a leading shared
  prefix in both files, and 47 had it in one file. For those 47 pairs, the
  non-prefix owner had the earlier first-message timestamp, so harvest order
  assigns ownership before the fork skips its leading copy.

### Codex session identity choice

Choose the unique first `session_meta.id` that matches the file's rollout
filename as its session ID. This produces one unique primary ID for each of the
953 rollout files; additional leading metadata IDs are not the file's session
identity. This resolves the one-file/one-session state rule. Shared message
IDs occur only across fork-related primary sessions, and first-message
timestamp ordering gives the non-prefix owner first access in the 47 pairs
where only one file begins with the shared messages.

## Harvest on real data (2026-10-27)

All runs used copied Claude Code and Codex transcript roots and a scratch
content clone whose only remote was a scratch bare repository. The real
content repository remained at its recorded `main` status (`ahead 20`) and
HEAD `3315cdf8b4a94711813a9647cb79a9b806b2e8f5`. The scratch clone ended
four commits ahead of its scratch origin and was not pushed.

### Inventory and accounting

- Source files scanned: 1,146; scan failures: 0.
- At the initial `--status` sample, ready/waiting sessions were Claude Code
  79/1 and Codex 21/8. At final accounting, 2 additional Codex sessions had
  become ready: Claude Code 79/1 and Codex 23/6.
- Final eligible and harvested sessions: 102 (Claude Code 79, Codex 23).
  Observations: 103 (Claude Code 80, Codex 23), because one Claude session
  produced a continuation part 2. Total messages: 9,759 (Claude Code 8,850;
  Codex 909).
- Ready subagents: Claude Code 39, Codex 9. Eligible source forks sharing
  message IDs: 0; observations with `forked_from`: 0.
- Median observation size: 17,118 bytes; largest: 1,457,527 bytes.
  Median message count: 32; largest: 1,657.
- Redacted lines: 9 total — AWS Access Key 1, GitHub Token 1, Hex High
  Entropy String 1, Secret Keyword 4, Slack Token 1, Stripe Access Key 1.
- Skipped sessions: 0. Malformed source lines: 0. Duplicate source IDs: 0.
  Eligible messages unaccounted for: 0; duplicate harvested messages: 0;
  messages with content mismatches: 0; secret findings outside redactions: 0.

The independent backward audit found 14 eligible messages not yet
accounted for after an idle session crossed the 60-minute threshold during
the run. A catch-up run harvested 2 newly ready sessions (22 messages); the
final no-op run and final audit then reported zero unaccounted messages.
No eligible fork example or one-message observation existed in this data.

### Run times

| Run | Result | Elapsed |
|---|---|---:|
| Initial `--dry-run` | 50 planned sessions, 3,551 messages | 38.32 s |
| Initial `--status` | 100 ready, 9 waiting | 25.37 s |
| Harvest 1 | 50 sessions, 3,551 messages | 38.23 s |
| Harvest 2 | 50 sessions, 6,167 messages | 63.82 s |
| Harvest 3 | 0 sessions | 25.52 s |
| Continuation part 2 | 1 session, 19 messages | 25.77 s |
| Idempotence run | 0 sessions | 25.56 s |
| Catch-up after inventory audit | 2 sessions, 22 messages | 25.41 s |
| Final idempotence run | 0 sessions | 25.24 s |

## Fresh validation after the harvest fixes (2026-10-27)

Tested repository revision: `ed5a02d1cfd590ff86b5735a0df150cd5869cede`.
The run used a new `/tmp` scratch tree with fresh copies of both transcript
roots, preserved mtimes, a new bare content origin, and a fresh working clone.
The working clone's only remote was the scratch bare repository. The cutoff
was `2026-10-20T22:23:03Z`. The real content repository started at
`39763a314342b72f855beb06d6b0c2414406f47e` with status `main [ahead 24]`;
both values were unchanged at the end. The scratch clone finished clean and
three commits ahead of its scratch origin; it was not pushed.

No previous continuation session and split boundary were present in the
current notes. A qualifying session from the fresh Claude copy was selected,
split into 18 and 19 eligible messages, then restored with its original mtime.
The verification confirmed adjacent parts with no overlapping messages.

An initial scratch harvest attempt failed before creating a commit because
the fresh clone had no Git author identity. Its `HEAD` and working tree still
matched the starting state. That clone was discarded, a new working clone was
made from the same scratch bare origin, and a scratch-local identity was set.
The full dry-run, status, harvest, continuation, and idempotence sequence was
then repeated successfully.

### Inventory and accounting

- Source files scanned: 1,152; scan failures: 0.
- Initial `--status`: 92 ready and 5 waiting. Final independent accounting
  found the same total, with Claude Code 63 ready/1 waiting and Codex 29
  ready/4 waiting; no sessions crossed the idle threshold during the run.
- Eligible and harvested sessions: 92 (Claude Code 63, Codex 29).
  Observations: 93 (Claude Code 64, Codex 29), including one continuation
  part 2. Total messages: 10,039 (Claude Code 8,276; Codex 1,763).
- Ready subagents: Claude Code 24, Codex 12. Eligible source forks sharing
  message IDs: 0; observations with `forked_from`: 0. The source scan found
  112 shared message IDs overall, none in eligible fork sessions.
- Parts: 92 part 1 observations and one part 2 observation.
- Median observation size: 24,305 bytes; largest: 1,457,527 bytes.
  Median message count: 32; largest: 1,657.
- Redacted lines: 10 total — AWS Access Key 1, GitHub Token 1, Hex High
  Entropy String 1, Secret Keyword 5, Slack Token 1, Stripe Access Key 1.
- Skipped sessions: 0. Malformed source lines: 0. Duplicate source IDs: 0.
  Eligible messages unaccounted for: 0; duplicate harvested messages: 0;
  message content mismatches: 0; secret findings outside redactions: 0.
- Observation fields and H2 counts matched for all 93 observations. Six
  `kb read` examples covering every kind present passed 12 locator checks.
  No eligible fork example or one-message observation existed in this data;
  fixture coverage remains the evidence for those kinds.

### Run times

| Run | Result | Elapsed |
|---|---|---:|
| Initial dry-run, before scratch clone reset | 50 sessions, 7,225 messages | 70.25 s |
| Initial status, before scratch clone reset | 92 ready, 5 waiting | 28.70 s |
| Initial harvest attempt, discarded after author identity failure | No commit; scratch `HEAD` and tree unchanged | 66.29 s |
| Retry dry-run | 50 sessions, 7,225 messages | 63.55 s |
| Retry status | 92 ready, 5 waiting | 25.63 s |
| Harvest 1 | 50 sessions, 7,225 messages | 64.31 s |
| Harvest 2 | 42 sessions, 2,795 messages | 48.66 s |
| Backlog drain | 0 sessions | 27.02 s |
| Continuation part 2 | 1 session, 19 messages | 26.21 s |
| Idempotence | 0 sessions | 25.99 s |

### Recovered acceptance results (2026-10-27)

The results below were recovered from a scratch copy of the Codex session
that performed this validation. They document the existing run at
`ed5a02d`; no new harvest was run during the evidence review. The source is
`~/.codex/sessions/2026/10/27/rollout-2026-10-27T14-54-04-01a17f5b-2dc3-7523-bb1c-b703376b9299.jsonl`.
The table identifies the original tool-result timestamps and call IDs so
the claims can be traced without retaining transcript content here.

| Check | Recorded result | Tool-result time (UTC) and call ID |
|---|---|---|
| Copied mtimes | Three samples matched: Claude main, Claude subagent, and Codex rollout. | `22:23:12.493`, `call_530c08bd9ad64d9ea9f3da14b4a2549f` |
| Continuation cut | 37 eligible messages split into 18 and 19 at the IDs recorded below; copied and truncated files retained the original mtime. | `22:23:49.155`, `call_fb0a82c1f791433da099a7e3eb3dd3b9`; `22:23:54.329`, `call_2becf8a0fd8d4bf4876cf02708a1df4f` |
| Retry dry-run Git state | Before/after comparisons passed for working-tree status, `HEAD`, every ref including remote-tracking refs, and `kb-tmp/`. Exit 0; `dry_run_state_unchanged=yes`. | `22:29:04.117`, `call_cb22673fc03342f4be501f06d393f874` |
| Retry status Git state | Before/after comparisons passed for working-tree status, `HEAD`, the index tree, and every local branch. Exit 0; `status_git_state_unchanged=yes`. | `22:29:36.832`, `call_221427a432154ba6bd6fa81868e2b54d` |
| Dry-run versus harvest 1 | All 50 app/session/part identities and per-session message counts matched the first commit; 7,225 messages total. | `22:30:49.350`, `call_b661491d4c2c4646a5ee6a8f49981419` |
| Harvest commits and selection | Exactly three commits, changing 50, 42, and 1 observation paths, with the required subjects. The first dry-run list was oldest first by start timestamp and session ID; the first backlog commit contained the oldest 50 sessions and the second contained the remaining 42. | `22:38:25.524`, `call_47c7f6d073d247379fca61533425276b` |
| Continuation | Both parts committed; 18 and 19 H2 sections, adjacent boundary messages, zero overlap. | `22:33:22.368`, `call_a4d3c2a4794043698c2e91ebfe6564b4` |
| Independent accounting, structure, and secrets | `account_exit=0`: 10,039 source messages accounted for, zero mismatches, duplicates, or secret findings outside redactions. The audit checked every H2 body for text outside fences and unclosed fences, accepted closers only when at least as long as their opener, and checked H2 counts against source messages. | `22:35:38.410`, `call_bc584f435911408086ec213927d3a802` |
| Read locators | Six examples and 12 locators matched their source sections. | `22:36:10.765`, `call_6d44630fcb44470dbe719eb8b136c015` |
| Real repository and cleanup | Final `HEAD` and status comparisons passed. The command deleted the exact scratch tree and checked its absence before printing `real_content_unchanged=yes scratch_removed=yes`. | `22:41:18.688`, `call_b438150b60b344b8bb74422443aad70c` |

The successful retry sequence's dry-run, status, two harvest batches,
backlog no-op, continuation, and final idempotence run all exited 0. The
Git-identity failure described above belongs to the discarded attempt.
The two no-op runs retained their preceding `HEAD`; no session was skipped.

The three scratch harvest commits were:

| Commit | Subject |
|---|---|
| `1dc66c5617d6f1b8a3fa71e13ba5731ced7adbef` | `Observe: 50 session transcript(s)` |
| `3174031e1b031d7f46c933aa69698c1656ef1b32` | `Observe: 42 session transcript(s)` |
| `3651024498d462c70a0aaada6449a2e50e24d668` | `Observe: 1 session transcript(s)` |

These commits existed only in the deleted scratch clone. Their identities,
subjects, exit statuses, and no-op `HEAD` comparisons are preserved in the
source session's tool results from `22:30:47.188` through `22:33:53.791`.

The continuation cut is reproducible while the source session remains
available and eligible:

- App: `claude-code`.
- Session: `253e45b4-0033-49a8-ad51-5c162e6caee3`.
- Last message in part 1: `d179f906-16c3-4655-9a2b-4e10cbb81cd7`.
- First message in part 2: `e23da9a1-f356-42df-bfb3-3b07ae4189ac`.
- Prefix: 220 complete lines from the 370-line copied file, under cutoff
  `2026-10-20T22:23:03Z`. Future runs must recheck readiness and eligible
  message counts before reusing this cut.

The deleted validation tree was `/tmp/kb-phase1-validation.GDk2J3`. The
cleanup command removed that entire tree, including both transcript roots,
`full.jsonl`, the bare origin, working clone, and generated observations.
This records direct cleanup evidence rather than inferring cleanup from a
search for particular filenames.

### Review closeout and remaining validation

The review ran `just check` against `ed5a02d` on Linux with Python 3.15.0:
lint and strict type checking passed; 846 tests passed, 5 compatibility
tests skipped, and branch coverage was 100%. Tool caches and coverage
output used writable `/tmp` paths. Zizmor ran in offline mode; its online
audits were not exercised.

The Windows CI job has not run; its first native run remains outstanding.
The default-config and backslash filesystem tests have Windows branches,
but those branches have not executed. Symlink and shell-hook support on
the Windows runner also remains unverified. Record the tested revision and
actual Windows results before closing those platform criteria.

## Evidence access baseline (2026-10-27)

Tested code revision: `ed5a02d1cfd590ff86b5735a0df150cd5869cede`.
The read-only baseline used a scratch copy of content revision
`95838f8ebac66a56c621f8ce7001ca6fd6fb8135`. The copy began clean and remained
unchanged. `KB_CONTENT` was unset; a scratch config selected the copy, both
transcript roots were empty, and `harvest_since` was absent. No real content
was written.

The shared Markdown model found 61 pending and 1,102 archived ordinary
observations, 1,435 harvested transcripts, and 44 open plus 13 resolved
questions. All 57 question contexts use `knowledge/`; one target is missing.
No harvested transcript meets the addressable-message contract, so message
locators still have fixture-only coverage.

Each recall command had one warm-up and three timed runs. The medians below
exclude the warm-up; peak RSS is the maximum across the three timed runs.

| Command case | Median elapsed | Maximum peak RSS |
|---|---:|---:|
| Curated hit | 2.06 s | 34,076 KiB |
| No match | 15.03 s | 146,504 KiB |

These values are the baseline for the phase 2 final performance comparison.

The first unfiltered `kb evidence` implementation measurement used the same
scratch snapshot, one warm-up, and three timed runs. Its median was 13.85 s
with 146,644 KiB maximum peak RSS, within the 20 s and 200 MiB gates. The
command output was redirected; it did not change the content or Git state.

## Evidence access closeout (2026-10-27)

The phase 2 implementation was tested at `35a084ef5e1e9417d57ecefc833a24c96c5bcd1e`;
the documentation closeout commit is `4709002`.
All closeout commands used a private scratch copy at content revision
`95838f8ebac66a56c621f8ce7001ca6fd6fb8135`, with `KB_CONTENT` unset, a
scratch config, empty Claude and Codex transcript roots, and no
`harvest_since`. The real content repository and scratch copy both remained
at that revision with clean Git state. No real content was written and no
harvest was run.

The inventory remained 61 pending and 1,102 archived ordinary observations,
1,435 harvested transcripts, and 44 open plus 13 resolved questions. All 57
question contexts use `knowledge/`; one target is deleted. No real transcript
has addressable message metadata, so message locators remain fixture-only.

Each performance case had one warm-up and three timed runs. Medians exclude
the warm-up; peak RSS is the maximum of the three timed runs.

| Command case | Median elapsed | Maximum peak RSS | Gate |
|---|---:|---:|---|
| `kb questions` | 0.13 s | 28,444 KiB | Pass: <= 2 s and <= 200 MiB |
| Unfiltered `kb evidence` | 13.91 s | 146,652 KiB | Pass: <= 20 s and <= 200 MiB |
| Curated-hit `kb recall` | 2.50 s | 34,264 KiB | Pass: <= 5 s and baseline allowance |
| No-match `kb recall` | 14.68 s | 146,688 KiB | Pass: <= 20 s and baseline allowance |

Recall baseline medians were 2.06 s for curated hits and 15.03 s for no
matches. The final medians satisfy the plan's `baseline * 1.10 + 1 s` limits
(3.27 s and 17.54 s). The no-match path still exceeds the separate desired
latency of 5 s; that follow-up remains open.

The closeout also passed a deleted-article context filter, a scoped question
listing, transcript kind/date filters, open-question kind filtering, and
legacy transcript searches. Baseline and final recall each returned five
archived-observation rows for three identical query/store pools. All three
file orders were identical: 15 rows compared and zero changed positions.
This confirms no ordering change for an unchanged archived-observation pool.
The intended evidence changes are filter-dependent corpus ranking and the
addition of matching open questions to curated-hit recall; curated section
ranking remains unchanged.

`just eval` passed at step 2: the question set had 8/8 answerable results in
the top three and 2/2 unanswerable results; the original retrieval set had
32/32 expected locators in the top three, 4/4 unanswerable results, and
10/10 `requires_all` results.

`just check` passed with 958 tests, 6 skipped, and 98.59% total coverage;
lint, formatting, actionlint, offline zizmor, and strict mypy passed. The
default uv, Ruff, and `just` runtime cache paths were read-only, so checks
used scratch cache and runtime directories. The first package-check attempt
could not resolve PyPI from the sandbox. The required
`just build package-check` then passed with network access: it built the
wheel, installed it into a clean environment, and verified version `0.1.0`.

The first native Windows CI run remains outstanding. Harvesting remains
disabled and installed host allow rules were not changed. Guided curation,
article verification, and question resolution remain phase 3 work.

## Curation primitives baseline (2026-10-27)

Tested code revision: `22d95f9ea907f5ce51648fa10859270d9ee386ff`.
The private scratch clone used content revision
`0c34b26f71c8930aa9dd2becf61b431f98d55ff6`. The old `scripts/lint` checked
all 210 articles and exited 0 with no errors or warnings:

| Check | Errors | Warnings |
|---|---:|---:|
| Front matter | 0 | — |
| Headings and fences | 0 | — |
| Section metadata | 0 | — |
| Source references | 0 | — |
| Local Markdown links | 0 | — |
| Long H2 sections | — | 0 |
| Duplicate H2 headings | — | 0 |

The inventory used the shared Markdown model and the old `stale --count`:

| Measure | Result |
|---|---:|
| Articles | 210 |
| Articles without `ttl` | 100 |
| Articles with invalid `ttl` | 0 |
| Stale articles | 124 |
| Articles with `conflict: unresolved` | 4 |
| Articles with section-level `verified` | 61 |
| Section-level `verified` overrides | 119 |
| Open questions | 44 |
| Open questions already containing `## Resolution` | 0 |

Reference fragment shapes were:

| Reference kind | No fragment | kb fragment | Exact H2/H3 | ASCII slug | Other | Total |
|---|---:|---:|---:|---:|---:|---:|
| `sources` entries | 1,916 | 0 | 0 | 0 | 3 | 1,919 |
| Local Markdown links | 129 | 0 | 0 | 80 | 0 | 209 |

The verification refusal for section-level `verified` metadata affects 61 of
210 articles (29%). Even if all 61 were stale, they would be fewer than half
of the 124 stale articles, so the refusal does not block most article
verification. Continue with lint and the front-matter editor, then implement
`kb verify`.

Before the baseline commit, `just check` passed on Linux with Python 3.15.0:
967 tests passed, 6 were skipped, and branch coverage was 98.56%. Ruff,
formatting, actionlint, offline zizmor, and strict mypy passed.

The scratch tree's file hashes and Git state were unchanged after the runs;
the clone was removed. The live content repository advanced from the baseline
revision to `2298c0e4f7dcb923455d4b861db46042e9211f56` in one
observations-only commit during the measurement. The run did not write to the
live repository.

## Curation lint structure and metadata (2026-10-27)

The step 2 comparison used the repository's `tests/fixtures/content` tree.
Fixture front matter was given valid `updated` dates where that was not the
case under test; the CRLF fixture remained CRLF. No real knowledge content
was read or written for this comparison.

The old `scripts/lint knowledge/rules` exited 1 with 22 errors and 2 warnings
across 24 files. `kb lint knowledge/rules` reported 29 errors and 2 warnings
across the same files. Both found the duplicate H1, unclosed fence, missing
H1, long and duplicate H2, effective-date ordering, supersedes locator and
cycle errors, and the core metadata placement and syntax problems. The new
fixture test asserts every finding and its output order.

Accepted differences:

- The old script treats CRLF front matter delimiters as missing and reported
  three missing-field errors for that fixture. The shared model recognizes
  CRLF, so the new linter reports it cleanly.
- The old script uses the H1 as a fallback title when front matter has no
  `title`. The new contract requires the front-matter field, so it reports
  the missing title in the no-front-matter and unclosed-front-matter cases.
- The old front-matter check validates date shape only and does not validate
  article `ttl`. The new linter checks actual calendar dates and validates
  article TTLs against the named values and `MAX_TTL_DAYS`.
- The old section TTL parser accepts zero as a nonnegative number. The new
  contract requires a positive integer within `MAX_TTL_DAYS`, so `ttl=0` is
  an error.
- For duplicate section fields, the old shell checker validates the last
  value. The shared model's existing retrieval behavior keeps the first
  value; lint preserves that behavior, reports the conflict, and validates
  the first value.
- The old shell checker accepts both `key=value` and `key: value` section
  fields, while the shared Python model reads only the documented
  `key=value` syntax. A synthetic `ttl: people` comment passed old lint and
  produces a malformed-field error in the new linter. This follows the
  specified comment syntax and keeps retrieval behavior unchanged.
- The old shell checker ignores text after a metadata comment's closing
  marker. The model retains that span and the new linter reports the trailing
  text.
- Finding locations and formatting follow the new path/line contract. The
  old script reports some front-matter errors at line 1 and section metadata
  errors at section locators, and combines several metadata errors into one
  message.

The colon-syntax comparison ran both commands against the same disposable
fixture copy: old lint exited 0; `kb lint` reported one malformed field. The
copy was removed. The old and new linter also both ignore an H1 inside the
unclosed fence; the new linter points to the fence's opening line, while the
old script points to end of file.

`just check` passed on Linux with Python 3.15.0: lint, formatting,
actionlint, offline zizmor, and strict mypy passed; 998 tests passed, 6 were
skipped, and total coverage was 97.60%. Tool caches and coverage output used
scratch paths under `/tmp`.

## Curation lint references (2026-10-27)

The old `scripts/lint` and `kb lint` both checked the fixture knowledge tree
without reporting a missing source or Markdown-link target or fragment. The
step 3 tests also cover valid and missing front-matter and section sources,
archived observations, `sources/` articles, relative links, repository
escapes, external URLs, `mailto:`, absolute paths, kb locators, exact H2/H3
headings, ASCII slugs, and headings inside code fences.

One accepted anchor difference is covered directly. The old script's anchor
scanner accepts ATX headings at levels 1 through 6. The plan's fragment
contract accepts kb locators and exact or slug H2/H3 headings, so the new
linter rejects a link to an H1 or H4 slug. On a disposable fixture, old lint
passed links to both levels; `kb lint` reported both missing anchors. The
fixture was removed.

`just check` passed on Linux with Python 3.15.0: lint, formatting,
actionlint, offline zizmor, and strict mypy passed; 1,004 tests passed, 6
were skipped, and total coverage was 96.99%. Tool caches and coverage output
used scratch paths under `/tmp`.

## Front-matter editor (2026-10-27)

The pure model editor replaces a unique scalar field line or inserts one after a unique scalar field or before the closing delimiter. It uses the parser's line spans, refuses missing or unclosed front matter, duplicate fields, block-list targets and anchors, invalid names, and multiline values. Insertions follow the surrounding LF or CRLF convention. Replacement values are quoted and escaped when needed, and every edit is reparsed to confirm the requested value.

Tests assert that replacement changes only its target line, insertion adds one line, other quoted fields and body bytes remain unchanged, CRLF is preserved, and ambiguous or unsafe edits fail. `just check` passed on Linux with Python 3.15.0: lint, formatting, actionlint, offline zizmor, and strict mypy passed; 1,017 tests passed, 6 were skipped, and total coverage was 96.67%. Tool caches and coverage output used scratch paths under `/tmp`.

## Explicit article verification (2026-10-27)

`kb verify` resolves a whole Markdown article under `knowledge/`, reads it under the shared kernel and legacy locks, and builds the verified date and optional TTL edit in memory. It runs structural, metadata, and local-reference lint against the proposed document with `--require-ttl`; unresolved conflicts and section-level verified dates are explicit refusals. The command scans the final TTL, then atomically replaces the article from `.git/kb-tmp`. It preserves UTF-8 bytes outside the edited lines, including CRLF and a leading BOM, and skips replacement when date and TTL already match. It does not stage or commit, and a unit test forbids Git subprocess calls.

Fixture tests cover replacing and inserting both fields, named and numeric TTLs, repaired invalid values, missing TTL without an override, paths and fragments, ambiguous names, lint and reference failures, unsafe front matter, conflicts, local verification overrides, CRLF, same-day mtime stability, read and recall freshness, both locks, lock wait parsing, and cleanup after failure or interruption. `just test-compat` passed all 7 tests; the old `stale` and `lint` scripts accepted an article written by `kb verify`. `just check` passed on Linux with Python 3.15.0: lint, formatting, actionlint, offline zizmor, and strict mypy passed; 1,051 tests passed, 7 were skipped, and total coverage was 95.54%. Tool caches and coverage output used scratch paths under `/tmp`.

## Question resolution (2026-10-27)

`kb resolve` validates one `questions/open/` file, an existing `knowledge/` locator for answered outcomes, and exactly one outcome. It writes a byte-preserving resolved copy with resolution metadata and the answer section, then removes the open file while holding the shared writer locks. The command scans the destination and answer for possible secrets, does not stage or commit, and rolls back the publication if removing the open file fails. The renderer preserves original line endings and a leading UTF-8 BOM.

The end-to-end and unit tests cover exact answered and obsolete output, old questions without attribution fields, `kb gap` output, Unicode and stdin, quoted titles, canonical numbered fragments, missing and ambiguous destinations, missing fragments, `sources/` refusal, outcome and source refusals, secret locations, resolved-copy conflicts, questions/evidence/recall behavior, and rollback after publication under both an I/O error and interruption. `just test-compat` passed all 9 tests; the old questions reader accepted a new resolution, and `kb questions --all` listed an old-script resolution. `just check` passed on Linux with Python 3.15.0: lint, formatting, actionlint, offline zizmor, strict mypy, and 1,068 tests passed; 9 were skipped; total coverage was 93.16%. Tool caches and coverage output used scratch paths under `/tmp`.

## Phase 3 documentation and closeout (2026-10-27)

Validated code revision: `3d3cfb7 Add question resolution command`. The real-data copy came from content revision `62a2bf69f8076bceabda5490a70f9a3e3b607624`; it excluded the live `.git` directory and received its own scratch Git metadata. The live content worktree remained clean at the same revision. The scratch copy was removed after validation.

The old `scripts/lint` exited 0 on all 210 articles with 0 errors and 0 warnings, matching the per-check baseline from step 1. `kb lint` checked the same 210 articles and reported 2 errors and 0 warnings:

| Check | Old errors | Old warnings | `kb lint` errors | `kb lint` warnings |
|---|---:|---:|---:|---:|
| Front matter | 0 | — | 0 | — |
| Headings and fences | 0 | — | 0 | — |
| Section metadata | 0 | — | 0 | — |
| Source references | 0 | — | 2 | — |
| Local Markdown links | 0 | — | 0 | — |
| Long H2 sections | — | 0 | — | 0 |
| Duplicate H2 headings | — | 0 | — | 0 |

Both new errors are missing targets from `sources` entries whose targets do not end in `.md`. The old shell linter ignores those entries because it checks only `.md` and `.md#...` source values; the new contract checks every `sources` entry. The remaining checks match the step 1 counts. No content was changed.

Three timed `kb lint` runs took 0.41, 0.35, and 0.37 seconds; the median was 0.37 seconds. Peak RSS was 27,592 KiB. Both results meet the plan limits of 5 seconds and 200 MiB. `kb verify` and `kb resolve` each succeeded on the disposable copy; the copy was then deleted.

`just eval` exited 0 and met acceptance on both fixture sets. `just build package-check` passed; the clean environment installed the 0.1.0 wheel and confirmed its version. The existing `dist/` directory was restored after the check. Native Windows validation remains unrun. The guided curation run, dispositions and archiving, finishing commit and sync, content pre-commit hook, and one-time `ttl` assignment pass remain outstanding. Installed host allow rules and the separate no-match recall latency follow-up also remain open.

`just check` passed on Linux with Python 3.15.0: lint, formatting, actionlint, offline zizmor, and strict mypy passed; 1,068 tests passed, 9 were skipped, and total coverage was 93.16%. Tool caches and coverage output used scratch paths under `/tmp`.

## Curation lint link syntax and anchor case (2026-10-27)

Base revision: `611dbdf Document curation checks and closeout`. This change
corrects three reference-check defects found after closeout.

- Link targets now follow Markdown syntax. A new `kb/links.py` reads inline
  targets with balanced parentheses, angle-bracket targets, titles, escaped
  punctuation, and nested link text. It also resolves full, collapsed, and
  shortcut reference-style links against their `[label]: target`
  definitions. The first definition wins, labels ignore case and collapse
  whitespace, and a definition may follow its use.
- Slug anchors match the old lint's rule. The old `heading_slug` comparison
  lowercases ASCII letters in the fragment, then requires the result to
  equal the heading slug. `kb lint` now does the same, so
  `#EXACT-HEADING` resolves to `## Exact Heading!`. Before this change, the
  linter slugged both sides and accepted fragments such as
  `#exact-heading!!!`, which the old lint rejects.
- An unclosed or malformed section-metadata comment no longer hides later
  section metadata. The model inspects each later opener independently, as
  retrieval did before metadata diagnostics existed, and keeps the
  diagnostics for the malformed comment.

Accepted differences from the old `scripts/lint`:

- The old script ends a link target at the first `)`, so
  `[x](guide(v2).md)` reported the missing target `guide(v2`. `kb lint`
  resolves the full target.
- The old script does not check reference-style links. `kb lint` reports a
  missing target or anchor in a reference definition at the line that uses
  it.

A disposable fixture confirmed each difference. Old lint and the step 3
`kb lint` reported the truncated target. The corrected `kb lint` accepted the
target with parentheses and the uppercase slug, and it reported the missing
reference-style target. The fixture was removed.

Real-data validation used a copy of content revision
`b9ddbb6d6942597fc6f08217faa4471b5e8248d9`. The copy excluded the live
`.git` directory and received its own scratch Git metadata. Old lint exited
0 with 0 errors and 0 warnings in 210 files. `kb lint` reported 2 errors and
0 warnings in 210 files. Both errors are the non-`.md` `sources` targets
recorded at closeout, so every per-check count matches the closeout table.
The old pattern and the new parser each found 292 local Markdown links in the
copy. No link target contains parentheses, and no fragment contains uppercase
letters. Three timed runs took
0.44, 0.41, and 0.45 seconds (median 0.44 seconds), with a peak RSS of
27,548 KiB. The copy was deleted, and the live content worktree remained
clean at the same revision.

## Local curation batches closeout (2026-10-28)

Implementation commits: `4178ab6` added pure batch state and transitions;
`7827f93` added local start and status; `e7285f7` added next-item context;
`2b01785` added outcomes and archive recovery; and `a71d3a3` added defer and
drop outcomes. Step 6 extends compatibility coverage, documents the command
contracts, and reuses one parsed curated snapshot to rank all selected titles
for the related-stale report. A unit test confirms that batched locator
results match independent recall queries, including their order.

`just test-compat` passed all 10 tests. The old reader omitted a new archive
from pending, found it through archive search, and accepted an article citing
it. The new readers accepted both a legacy archive with no metadata and one
with `disposition: processed`; recall found the latter. The compatibility
test ran against isolated fixtures and did not write to `~/Knowledge`.

The synthetic scale repository contained 1,200 pending observations and
2,100 articles. Observation payloads totaled 352,369 bytes; article payloads
totaled 351,300 bytes; the largest observation was 234,775 bytes. `start`
selected all 1,200 observations and reported 1,200 related stale articles.
The whole start took 6.21 seconds, including 5.86 seconds for related-stale
ranking. Peak RSS was 37,700 KiB (36.8 MiB). `status` took 0.28 seconds and
used 28,336 KiB (27.2 MiB). The scratch repository was removed. A first
implementation reparsed the curated corpus for each selected title and did
not finish in several minutes; the batch helper now shares candidate parsing
while preserving per-query ranking results.

`just eval` exited 0. Both fixture sets met acceptance: retrieval-question-v1
scored 8/8 answerable and 2/2 unanswerable; retrieval-v1 scored 32/32
answerable, 4/4 no-curated-result, and 10/10 `requires_all`. No evaluation
case changed.

`just build package-check` did not complete in this sandbox. The build stage
produced both the 0.1.0 wheel and source distribution, but the clean-environment
dependency install did not complete. The default uv cache is read-only here
and network access is unavailable; attempts with a scratch cache encountered
cache/installer path errors before the installed-wheel smoke test. The
preexisting `dist/` directory was restored. Run this recipe in an environment
with a writable uv cache and registry access before treating the package check
as passed.

`just check` passed on Linux with Python 3.15.0: ruff, formatting, actionlint,
offline zizmor, and strict mypy passed; 1,256 tests passed, 10 were skipped,
and total branch coverage was 90.10%. Native Windows validation remains
unrun. Phase 3 still needs synchronized start, the finishing commit and push,
the content pre-commit hook, and the one-time real-content TTL pass. No batch
was published or rolled out.

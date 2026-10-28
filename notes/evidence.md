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

## Publication and synchronization closeout (2026-10-28)

Implementation commits: `f8c637e` checked the carried workflow criteria;
`a258cc1` extracted the shared remote steps into `kb/remote.py`; `0393745`
added the synchronized start and manifest schema version 2; `b96017d` added
publication validation and `kb hook pre-commit`; `e1207d6` added
`kb curate finish`; `b274957` added the two-clone cycle and old-hook
compatibility tests. The documentation commit follows the tests.

`just build package-check` passed with the default uv cache and registry access.
The clean-environment install reported version 0.1.0, and the preexisting `dist/`
directory was restored.

`just check` passed on Linux with Python 3.15.0: lint, formatting, actionlint,
offline zizmor, and strict mypy passed. 1,386 tests passed, 11 were skipped (the
compatibility tests run under `just test-compat`), and total branch coverage was
91.36%.

`just test-compat` passed all 11 tests against `~/Knowledge`. The finish test
commits through the old pre-commit hook. The old `lint` accepts the article, and
the old `section` reads its first section. Each test used an isolated fixture.

`just eval` exited 0. Both fixture sets met acceptance, and no evaluation case
changed.

Real-content check. A scratch copy received its own Git metadata and a scratch
bare origin. The live repository was not written, and no real text is retained:

| Measure | Result |
|---|---:|
| Articles in the copy | 210 |
| Tracked files in the copy | 2,946 |
| Validation with no changes: blocking findings | 0 |
| Validation with no changes: preexisting findings | 2 (missing non-`.md` source references) |
| Validation time | 0.29 s |
| `kb lint` over the copy | 2 errors, 0 warnings in 210 files |
| One synthetic finish in the copy | published; origin matched local; 0.65 s; 37,876 KiB peak RSS |

The copy was removed after the run.

Synthetic repository: 2,100 articles, 1,200 pending observations, 3,301 tracked
files, and a bare origin. The repository was removed after the run.

| Operation | Elapsed | Peak RSS |
|---|---:|---:|
| `curate start`, one observation selected, synchronized | 3.72 s | 41,772 KiB |
| `curate finish`, topology change (one article deleted), pushed | 0.85 s | 39,780 KiB |
| `kb hook pre-commit`, direct run, topology change | 0.66 s | 33,728 KiB |
| `git commit` through the installed hook, one stamped article | 0.66 s | 33,916 KiB (git process) |

Deviations and open items:

- Native Windows validation remains unrun. The finish and hook end-to-end tests
  skip there because the installed hook is a POSIX shell script; the unit tests
  run in process.
- The sync unit tests that scripted `sync._git` for the moved helpers now patch
  `remote._git`. Their assertions are unchanged.
- `curate status` reads local Git refs for settled batches. It still runs without
  Git metadata and never contacts origin.
- A dropped member's input joins the publication set only when the file was
  deleted. A changed input refuses finish.
- Installing the hook (phase 4), adoption (phase 5), and the one-time real TTL
  pass remain. The 2026-10-27 baseline found 100 articles without `ttl`; this
  closeout did not re-measure it.
- The no-match recall latency follow-up is unchanged.

## Host conventions for setup and diagnosis (2026-10-28)

Phase 4 step 1, read only. Installed: Claude Code 2.1.312 and Codex CLI
0.165.0. Documentation was read on 2026-10-28 at code.claude.com/docs and at
learn.chatgpt.com/docs (developers.openai.com/codex redirects there). No host
setting was edited. Codex probes ran `codex execpolicy check` with a scratch
`CODEX_HOME` under `~/.cache`, not the live `~/.codex`. The `codex` shell
function adds `--profile agude`, which `execpolicy` rejects, so the probes
called the binary at `~/.local/bin/codex` directly.

### Claude Code

- Allow rules live in `permissions.allow` of the user settings file,
  `~/.claude/settings.json`, or `$CLAUDE_CONFIG_DIR/settings.json`.
  Source: code.claude.com/docs/en/permissions, "Wildcard patterns". The form
  is `Bash(kb recall *)`. A trailing `*` after a space also matches the bare
  command. `Bash(kb recall:*)` is equivalent, but the permission dialog writes
  the space form. Rules match the command text as typed, so the agent must
  call `kb` by name, not by absolute path.
- Compound commands: "Claude Code is aware of shell operators, so a rule like
  `Bash(safe-cmd *)` won't give it permission to run the command
  `safe-cmd && other-cmd`." Separators are `&&`, `||`, `;`, `|`, `|&`, `&`,
  and newlines. Every subcommand must be allowed. Deny and ask rules also
  reach subshells and command substitutions; allow rules need each part to
  qualify.
- Wrappers stripped before matching: `timeout`, `time`, `nice`, `nohup`,
  `stdbuf`, `command`, `builtin`, `noglob`, and bare `xargs`. `env`, `npx`,
  `direnv exec`, and `docker exec` are not stripped.
- Rule text for the seven working-agent commands:

  ```json
  "Bash(kb recall *)",
  "Bash(kb read *)",
  "Bash(kb map *)",
  "Bash(kb questions *)",
  "Bash(kb evidence *)",
  "Bash(kb observe *)",
  "Bash(kb gap *)"
  ```

- Global instruction file: `~/.claude/CLAUDE.md`. "If you set
  `CLAUDE_CONFIG_DIR`, every `~/.claude` path on this page lives under that
  directory instead." Source: code.claude.com/docs/en/claude-directory. On this
  machine the file is a symlink to `~/.dotfiles/llm/AGENTS.md`.
- Import: supported. `@path/to/file` in CLAUDE.md. Relative paths resolve
  against the importing file. Absolute and `~/` paths are allowed. Imports
  nest four hops deep. Imports inside code spans and fenced blocks are not
  read. A user-scope file's imports load without the external-import
  approval dialog. Source: code.claude.com/docs/en/memory, "Import additional
  files".
- Transcript retention: `cleanupPeriodDays` deletes
  `projects/<project>/<session>.jsonl` and the session's subagent transcripts
  once older than the value. Default 30 days, minimum 1, and `0` fails
  validation. Source: code.claude.com/docs/en/claude-directory, "Cleaned up
  automatically". This machine sets `cleanupPeriodDays` to 36500 in the
  dotfiles-linked `~/.claude/settings.json`, so the default cutoff never
  applies here.
- Hook registration: `~/.claude/settings.json` has one `coat-tree` command for
  each of PreToolUse, PostToolUse, SessionStart, UserPromptSubmit, Stop, and
  SessionEnd. The old tooling's entries are in `~/.config/coat-tree/hooks.d`:
  `PreToolUse/010.knowledge` (symlink to `~/Knowledge/scripts/adapters/claude/pretool-allow`,
  an auto-approve hook), and `SessionStart`, `UserPromptSubmit`, `Stop`, and
  `SessionEnd` `010.knowledge.sh` (symlinks to dotfiles shims). Other entries
  (`010.git-guard.sh`, `030.gh-guard.sh`, `040.skill-guard.sh`, and the
  `020.wiki` links) are not legacy.
- Permission rules installed now: 121 `permissions.allow` entries, none naming
  `kb` or `Knowledge`.

### Codex CLI

- Rule files: `.rules` files under `rules/` in the config layer. The user
  layer is `$CODEX_HOME/rules/`, which is `~/.codex/rules/` by default. Source:
  learn.chatgpt.com/docs/agent-configuration/rules. The directory does not
  exist on this machine.
- Syntax: `prefix_rule(pattern = [...], decision = "allow" | "prompt" |
  "forbidden", justification = "...", match = [...], not_match = [...])`.
  `pattern` is required. `decision` defaults to `allow`. `match` and
  `not_match` are checked when the file loads.
- Matching, measured with `codex execpolicy check --rules FILE -- ARGV`, one
  rule `prefix_rule(pattern = ["kb", "recall"], decision = "allow")`:

  | Command (argv) | Result |
  |---|---|
  | `kb recall foo` | allow |
  | `kb recall` | allow |
  | `kb recall --help` | allow (arguments after the prefix are not checked) |
  | `kb observe foo` | no matching rule |
  | `kb --verbose recall foo` | no matching rule (a word before the subcommand breaks the prefix) |
  | `bash -lc 'kb recall foo'`, `bash -c`, `sh -c`, `zsh -lc`, `/bin/bash -c` | no matching rule |
  | `env kb recall foo`, `timeout 5 kb recall foo` | no matching rule |
  | `bash -lc 'kb recall foo && rm -rf /tmp/x'` | no matching rule |

  The evaluator matches the argv prefix only. It does not unwrap shell
  wrappers or split compound commands. Multiple matching rules resolve to the
  strictest decision: forbidden, then prompt, then allow.
- A matching `allow` rule runs the command outside the sandbox without asking.
  Source: the rules page, "Use rules to control which commands Codex can run
  outside the sandbox."
- Rule text for the seven working-agent commands (one `prefix_rule` each):

  ```starlark
  prefix_rule(pattern = ["kb", "recall"], decision = "allow")
  prefix_rule(pattern = ["kb", "read"], decision = "allow")
  prefix_rule(pattern = ["kb", "map"], decision = "allow")
  prefix_rule(pattern = ["kb", "questions"], decision = "allow")
  prefix_rule(pattern = ["kb", "evidence"], decision = "allow")
  prefix_rule(pattern = ["kb", "observe"], decision = "allow")
  prefix_rule(pattern = ["kb", "gap"], decision = "allow")
  ```

- Global instruction file: `$CODEX_HOME/AGENTS.md`, which is `~/.codex/AGENTS.md`
  by default. `AGENTS.override.md` replaces it when non-empty. Source:
  learn.chatgpt.com/docs/agent-configuration/agents-md. Read at session start.
  Combined instruction files are capped by `project_doc_max_bytes`, 32 KiB by
  default.
- Import: not supported. The page documents concatenation only, so the
  instruction block names the content `AGENTS.md` by path. On this machine
  `~/.codex/AGENTS.md` is a symlink to `~/.dotfiles/llm/AGENTS.md`, the same
  file as Claude's global file.
- Transcript storage: rollouts are `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`.
  This machine has 1,020 of them, and the oldest, created 2026-08-17, is still
  present 72 days later. The config reference (learn.chatgpt.com/docs/config-file/config-reference)
  documents no retention or deletion key for rollouts. `history.persistence`
  (`save-all` or `none`) controls only `history.jsonl`, and `history.max_bytes`
  caps only that file by size. Retention is recorded as `unknown`.
- Hook registration: `~/.codex/hooks.json` (symlink to
  `~/.dotfiles/llm/codex/hooks.json`) has SessionStart, UserPromptSubmit, Stop,
  and SessionEnd entries, each `bash ~/.codex/hooks.d/session-*.sh`. Those are
  symlinks to `~/.dotfiles/llm/codex/hooks.d/*.sh`, and their headers say they
  "delegate to the knowledge-base adapter". `~/.codex/config.toml` has no hook
  entries. Codex has no coat-tree links.

### Open items

- Codex runtime invocation: whether Codex passes an agent's command to the
  rules as argv or wraps it in a shell is not measured. A live session would
  show it, and it writes a transcript, so it waits for rollout. If the
  runtime wraps commands, the Codex rules approve none of them.
- Allow rules match the typed command text. The instruction block and the
  allow rules must name `kb`, not an absolute path.

## Phase 4 closeout: setup and diagnosis (2026-10-28)

Commits, in order. Step 0 is four atomic commits, not one, because each
defect and the roadmap edit are separate changes: `b1de41f` (name renamed
articles in the finish message), `e69d24f` (report the rebased finish commit),
`2bb6139` (read the partial-commit index from the hook's environment), and
`dff83db` (update the longterm plan). Then `c3898ce` (sync outcome record,
step 2), `19d81b9` (instruction block and `--print`, step 3), `a17dc16` (config
and hook, step 4), `7f67564` (`--init`, step 5), and `9380f35` (`kb doctor`,
step 6), `302b2cd` (skip the POSIX shell tests on Windows), `af9c267` (the
compatibility test for the installed hook), and `6ef1eba` (gap and
`curate start` on a new repository). Each commit passed `just check` before
it was made.

Measurements:

- `kb doctor` on a synthetic configured machine: 2,100 articles, 1,200 pending
  observations, 500 Claude transcript sessions, an origin, and a sync record.
  Three runs took 0.46, 0.46, and 0.45 seconds. Peak resident memory was
  29,304 KiB. The target was under 5 seconds.
- Live read-only check, this machine, `uv run --locked python -m kb doctor`.
  Before and after the run, the status of the content repository and the
  modification times of the content root and its `.git` were unchanged. The
  states were 3 PASS (version, config, curation), 8 WARN (content, gitattributes,
  hook, scheduler, capture, instructions, allow-rules, legacy), and 1 FAIL
  (sync: no record). Exit status 1. Counts: 55 unpublished commits in the
  content repository, and 14 old-tooling registrations.
- Scratch-copy rehearsal. The copy had its own Git metadata and a scratch
  origin. Its config and host files were in a scratch home, and the live config
  was not touched. `kb setup --content COPY --replace-old-hook` created the config
  and replaced the old hook's link, and the link's target was not changed. An
  article edit committed through the installed hook was stamped. Doctor reported
  5 PASS (version, config, hook, curation, legacy), 6 WARN (content with one
  unpublished commit, gitattributes, scheduler, capture, instructions,
  allow-rules), and 1 FAIL (sync: no record). The copy was removed.
- Renormalization. Adding `* text=auto eol=lf` to the copy changed 0 of its
  2,950 tracked files under `git add --renormalize .`, which took 0.12 seconds.
- `just test-compat`: 12 passed against the old tooling checkout. The new test
  installs the hook with `kb setup`, runs the old `observe` and `archive` through
  it, and checks that the new hook stamps a staged article.
- `just eval`: exit 0, acceptance met. Answerable cases in the top 3: 32 of 32.
  Unanswerable cases with no curated result: 4 of 4. `requires_all` cases: 10 of
  10.
- `just build package-check`: passed. The installed wheel prints the instruction
  block.
- `just check`: 1,614 passed and 11 skipped at the doctor commit, with branch
  coverage of 90.71%.

Deviations and contract amendments:

- The sync record's `message` is the first line of the failure, as section 5.1
  says. Git and operating-system messages can contain a path, so the record can
  contain one, which section 5.1 says it must not. The implementation keeps the
  line unredacted. Redacting it or truncating it at the first path is a decision
  for the user.
- The installed instruction block is one block for both hosts, because the
  dotfiles install one file for both. Its policy line is an import. Claude Code
  loads the import, and Codex reads the same line as a path. This replaces
  section 5.3's "import where supported, otherwise path".
- `kb setup --print instructions` needs a content path, from `KB_CONTENT` or the
  config file, but the directory need not exist. This is the reading of "needs
  no content repository" that the implementation uses.
- The hook refuses a kb path that contains a carriage return, in addition to the
  three characters section 5.2 lists. The refusal is stricter, and no valid path
  is refused.
- Review fixes after closeout. Section 5.2 names `kb sync` as the recovery after
  a failed `--init` push, but `kb sync` fetches `origin/main` first and fails on
  an empty origin. Setup now prints `git push --set-upstream origin main`, run in
  the new repository. A refused hook or a failed initial commit now removes what
  `--init` created and leaves the config unchanged, so `--init` can run again.
  `kb setup --print instructions` now resolves the content path, as
  `config.content_root` does, so doctor's comparison matches through a symbolic
  link.
- `kb setup` with no options configures the machine: it installs the hook in the
  configured repository and leaves the config unchanged. The usage in section 5.2
  allows this form.
- `harvest.Selection` gained `ready_modified`, a defaulted field, so the capture
  check can count ready transcripts older than 20 days. `kb/commands/curate.py`
  gained a read-only `doctor_findings`, and the hook classifier is now the public
  `existing_hook`, which setup and doctor share.
- Codex retention is reported as `unknown`. Its configuration documents no
  retention setting. The oldest rollout on this machine, created 2026-08-17, was
  still present 72 days later.
- Claude Code's `cleanupPeriodDays` is 36500 on this machine, not the default
  30. Doctor reports the configured value. At that value, transcripts do not age
  out under the default cutoff.

Open items:

- Native Windows is not verified here. CI runs `just test` on Windows, so the
  POSIX-shell tests skip on `win32`, and the Windows hook behavior is untested.
- Codex's runtime invocation is unmeasured. The rules match an argument list,
  and a `bash -c` wrapper does not match. If Codex's runtime wraps the agent's
  commands in a shell, the Codex allow rules approve none of them. A live session
  would show which form it uses.
- Capture is not enabled. `harvest_since` is unset, and the old capture hooks are
  still registered. Enabling and removing them happens together at phase 5.
- On this machine, the dotfiles do not yet install the instruction block or the
  allow rules, the timer is not installed, and no sync record exists under the
  new code. The content repository has 55 unpublished commits, and the old hook's
  link remains. These are rollout work, phase 5.
- The content repository does not have `.gitattributes`. The renormalization
  count is 0, so adding the file needs no renormalizing commit. Adding it is a
  rollout decision.

## dirac adoption baseline (2026-10-28)

### Rechecked live state

- Machine: `dirac`. Installed `kb` is `~/.local/bin/kb`, from the uv tool `knowledge-base` 0.1.0. Claude Code is 2.1.312; Codex CLI is 0.165.0.
- `~/Knowledge` core is clean on `main` at `1672b54508145938c436767460cc100a2f1057b3`. `~/.dotfiles` is clean on `main` and level with `origin/main` at `70751e74b90569a1002c70860fcd0130633c1da6`.
- `~/Knowledge/content` is on `main` at `01ccc2bc22e778d37eac35f9517e565e9a3dd13b`, clean and 57 commits ahead of its origin, with 2,952 tracked files. It has no `.gitattributes`; its pre-commit hook links to `~/Knowledge/scripts/hooks/pre-commit`.
- Installed and checkout `kb doctor` report the same result and exit 1: 3 PASS (`version`, `config`, `curation`), 8 WARN (`content`, `gitattributes`, `hook`, `scheduler`, `capture`, `instructions`, `allow-rules`, `legacy`), and 1 FAIL (`sync: No record`). The content warning counts 57 unpublished commits. The capture warning finds `harvest_since` unset; no writer for that setting exists yet. The legacy warning counts 14 registrations.
- `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` both link to `~/.dotfiles/llm/AGENTS.md`, whose Knowledge Base instructions still describe the old scripts.

### Codex paths and registration owners

- Current Codex documentation puts user skills in `$HOME/.agents/skills`; that is the same directory as `~/.agents/skills` here. Codex also scans repository, admin, and bundled system skills. The docs list `~/.codex/rules/default.rules` as the user rules location and define an `allow` prefix as permission to run outside the sandbox without a prompt. Sources: [Codex skill locations](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) and [Codex rules](https://learn.chatgpt.com/docs/agent-configuration/rules#create-a-rules-file).
- Dotfiles owns the four Claude lifecycle hook links under coat-tree and the four Codex hook entries: `links.conf` links `~/.codex/hooks.json` to `llm/codex/hooks.json`; `install.sh` links the hook scripts and Claude shims from dotfiles. These are 8 of the 14 old registrations.
- `~/Knowledge/scripts/install` currently creates coat-tree `PreToolUse/010.knowledge`, the content pre-commit hook, and the old skills in `~/.agents/skills`. Those account for 4 more registrations. The other two registrations are the existing `~/.claude/skills/{curate,knowledge-base}` symlinks into `~/Knowledge/skills`; the current old installer does not install into `~/.claude/skills`, and dotfiles has no matching skills to recreate them. The current producer of those two links was not found. The cutover must still remove them by target.

### Isolated Codex runtime probe

- Used Codex CLI 0.165.0 in an interactive, non-daemon TUI session with `--ask-for-approval on-request --sandbox workspace-write`, an isolated `HOME`, `CODEX_HOME`, XDG config, and transcript store, plus a `kb` shim invoking this checkout with `uv run --locked python -m kb`. The scratch Codex rules file contained exactly the seven generated prefixes: `recall`, `read`, `map`, `questions`, `evidence`, `observe`, and `gap`.
- The content fixture and local bare origin were separate from the Codex project. The final approval checks used a fixture outside `/tmp`; the initial `/tmp` fixture was writable under this environment's temporary-directory exception and let `kb sync` push two commits to the local bare origin. That run was discarded as an approval measurement.
- In the interactive TUI, Codex submitted simple commands as literal `cmd` strings to its `exec` tool. All seven allowed prefixes ran without approval; the five read commands used `--help`, and `kb observe` and `kb gap` wrote only to the disposable fixture. Codex's documentation says simple commands are split for prefix matching; advanced shell syntax is treated as a `bash -lc` invocation. The non-interactive `codex exec --json` transcript showed `/usr/bin/zsh -lc` wrappers and `approval_policy: never`, so it was not used to judge prompt behavior.
- `kb sync` produced an approval prompt before it could write to the outside-`/tmp` fixture. `kb curate start --no-sync --max-bytes 1` also produced an approval prompt. Neither command was approved. Sync did not exchange or publish fixture commits; curate did not start a batch.
- Interactive probe session IDs: allowed commands `01a184d1-57dc-7491-86c1-8aa1b89d027c`; sync approval `01a184d0-337b-7062-b2a8-8dbc24580d25`; curator approval `01a184d2-102a-7723-bd74-a2530aa3b618`. No host credentials or settings were written into this repository.

## Capture switch implementation (2026-10-28)

- `kb setup --enable-capture` scans the four old coat-tree lifecycle events and Codex hook
  scripts using the same registration readers as `kb doctor`. It refuses each remaining
  registration before setting `harvest_since` and names it in stderr.
- The config writer now lives in `kb/config.py`. Content and capture edits use the same sibling
  temporary file and atomic replace. The capture edit preserves BOM, CRLF, and unrelated TOML
  values; it inserts a UTC offset datetime at whole-second precision and refuses invalid or
  nested `harvest_since` values. A second enable reports the saved cutoff unchanged.
- Isolated e2e tests verified refusal and byte-identical config for each of the four coat-tree
  events and one Codex hook, successful enable and repeat enable, and `kb sync` harvesting a
  transcript newer than the boundary while skipping an older transcript.
- `just check` passed: 1,641 passed, 12 skipped, 90.39% branch coverage; ruff, actionlint,
  zizmor, and strict mypy passed.

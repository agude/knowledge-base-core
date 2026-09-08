import assert from "node:assert/strict"
import { execFile as execFileCallback } from "node:child_process"
import { chmod, mkdtemp, mkdir, readdir, readFile, rm, symlink, writeFile } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { promisify } from "node:util"
import { test } from "node:test"
import type {
  BeforeAgentStartEvent,
  BeforeAgentStartEventResult,
  MessageEndEvent,
  SessionShutdownEvent,
  SessionStartEvent,
} from "@earendil-works/pi-coding-agent"
import type {
  KnowledgeExtensionAPI,
  KnowledgeExtensionContext,
} from "../knowledge.js"

const execFile = promisify(execFileCallback)
const repositoryRoot = dirname(
  dirname(dirname(dirname(dirname(fileURLToPath(import.meta.url))))),
)
const adapterPath = join(repositoryRoot, "scripts/adapters/pi/knowledge.ts")

type Harness = {
  root: string
  contentDir: string
  sessionDir: string
}

type TestContext = KnowledgeExtensionContext
type Handler<Event, Result = undefined> = (
  event: Event,
  context: TestContext,
) => Promise<Result | void> | Result | void
type HandlerSet = {
  session_start: Handler<SessionStartEvent>
  message_end: Handler<MessageEndEvent>
  before_agent_start: Handler<BeforeAgentStartEvent, BeforeAgentStartEventResult>
  session_shutdown: Handler<SessionShutdownEvent>
}
type RegisteredHandlers = Partial<HandlerSet>
type AdapterFactory = (pi: KnowledgeExtensionAPI) => void | Promise<void>
type Message = MessageEndEvent["message"]
type UserMessage = Extract<Message, { role: "user" }>
type AssistantMessage = Extract<Message, { role: "assistant" }>
type ToolResultMessage = Extract<Message, { role: "toolResult" }>
type EnvironmentOptions = {
  knowledgeBase?: string
  observation: "0" | "1" | undefined
}

type FakeCoreOptions = {
  missing?: string[]
}

type Lifecycle = {
  sessionStart: HandlerSet["session_start"]
  messageEnd: HandlerSet["message_end"]
  beforeAgentStart: HandlerSet["before_agent_start"]
  shutdown: HandlerSet["session_shutdown"]
  context: TestContext
}

class PiMock implements KnowledgeExtensionAPI {
  readonly handlers: RegisteredHandlers = {}

  on(event: "session_start", handler: HandlerSet["session_start"]): void
  on(event: "message_end", handler: HandlerSet["message_end"]): void
  on(event: "before_agent_start", handler: HandlerSet["before_agent_start"]): void
  on(event: "session_shutdown", handler: HandlerSet["session_shutdown"]): void
  on(...registration: {
    [Name in keyof HandlerSet]: [Name, HandlerSet[Name]]
  }[keyof HandlerSet]): void {
    const [event, handler] = registration
    switch (event) {
      case "session_start":
        this.handlers.session_start = handler
        break
      case "message_end":
        this.handlers.message_end = handler
        break
      case "before_agent_start":
        this.handlers.before_agent_start = handler
        break
      case "session_shutdown":
        this.handlers.session_shutdown = handler
        break
    }
  }
}

async function loadAdapter(): Promise<AdapterFactory> {
  const moduleUrl = pathToFileURL(adapterPath).href + "?test=" + randomUUID()
  const module = await import(moduleUrl) as { default: AdapterFactory }
  return module.default
}

async function loadPi(): Promise<PiMock> {
  const pi = new PiMock()
  const adapter = await loadAdapter()
  await adapter(pi)
  return pi
}

function lifecycle(pi: PiMock, sessionFile: () => string | undefined): Lifecycle {
  const sessionStart = pi.handlers.session_start
  const messageEnd = pi.handlers.message_end
  const beforeAgentStart = pi.handlers.before_agent_start
  const shutdown = pi.handlers.session_shutdown
  if (!sessionStart || !messageEnd || !beforeAgentStart || !shutdown) {
    throw new Error("Pi lifecycle handlers were not registered")
  }
  return {
    sessionStart,
    messageEnd,
    beforeAgentStart,
    shutdown,
    context: { sessionManager: { getSessionFile: sessionFile } },
  }
}

function sessionStartEvent(
  reason: SessionStartEvent["reason"] = "startup",
  previousSessionFile?: string,
): SessionStartEvent {
  if (previousSessionFile === undefined) {
    return { type: "session_start", reason }
  }
  return { type: "session_start", reason, previousSessionFile }
}

function shutdownEvent(
  reason: SessionShutdownEvent["reason"] = "quit",
  targetSessionFile?: string,
): SessionShutdownEvent {
  if (targetSessionFile === undefined) {
    return { type: "session_shutdown", reason }
  }
  return { type: "session_shutdown", reason, targetSessionFile }
}

function beforeAgentStartEvent(systemPrompt: string): BeforeAgentStartEvent {
  return {
    type: "before_agent_start",
    prompt: "test prompt",
    systemPrompt,
    systemPromptOptions: { cwd: repositoryRoot },
  }
}

function userMessage(
  timestamp: number,
  content: UserMessage["content"],
): UserMessage {
  return { role: "user", content, timestamp }
}

function assistantMessage(
  timestamp: number,
  content: AssistantMessage["content"],
): AssistantMessage {
  return {
    role: "assistant",
    content,
    api: "test-api",
    provider: "test-provider",
    model: "test-model",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "stop",
    timestamp,
  }
}

function toolResultMessage(timestamp: number, content: string): ToolResultMessage {
  return {
    role: "toolResult",
    toolCallId: "tool-call-1",
    toolName: "test-tool",
    content: [{ type: "text", text: content }],
    isError: false,
    timestamp,
  }
}

function customRoleMessage(timestamp: number): Message {
  // The base SDK union has no custom entries. Mutate a valid message to model
  // a custom message supplied by another extension at runtime.
  const message = userMessage(timestamp, "custom content")
  Object.defineProperty(message, "role", { value: "custom" })
  return message
}

function messageEndEvent(message: Message): MessageEndEvent {
  return { type: "message_end", message }
}

async function createHarness(): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "knowledge-pi-adapter-"))
  const contentDir = join(root, "content")
  const sessionDir = join(root, "sessions")
  for (const directory of [
    "knowledge",
    "observations/pending",
    "observations/archived",
    "questions/open",
    "questions/resolved",
    "sources",
  ]) {
    await mkdir(join(contentDir, directory), { recursive: true })
  }
  await writeFile(join(contentDir, ".gitkeep"), "")
  await execFile("git", ["init", "-q"], { cwd: contentDir })
  await execFile("git", ["config", "user.email", "test@test.com"], { cwd: contentDir })
  await execFile("git", ["config", "user.name", "Pi Adapter Test"], { cwd: contentDir })
  await execFile("git", ["add", ".gitkeep"], { cwd: contentDir })
  await execFile("git", ["commit", "-q", "-m", "init"], { cwd: contentDir })
  await mkdir(sessionDir, { recursive: true })
  return { root, contentDir, sessionDir }
}

async function withHarness<T>(callback: (harness: Harness) => Promise<T>): Promise<T> {
  const harness = await createHarness()
  try {
    return await callback(harness)
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
}

async function withEnvironment<T>(
  harness: Harness,
  options: EnvironmentOptions,
  callback: () => Promise<T>,
): Promise<T> {
  const names = [
    "KNOWLEDGE_BASE",
    "KB_CONTENT_DIR",
    "SESSION_DIR",
    "KNOWLEDGE_OBSERVE",
    "KNOWLEDGE_MIN_MESSAGES",
    "REAL_KB",
    "ADAPTER_LOG_DIR",
    "FAIL_APPEND_BEFORE_ONCE",
    "FAIL_APPEND_POST_WRITE_ONCE",
    "FAIL_FLUSH_ONCE",
  ]
  const previous = new Map<string, string | undefined>()
  for (const name of names) previous.set(name, process.env[name])

  if (options.knowledgeBase === undefined) delete process.env.KNOWLEDGE_BASE
  else process.env.KNOWLEDGE_BASE = options.knowledgeBase
  process.env.KB_CONTENT_DIR = harness.contentDir
  process.env.SESSION_DIR = harness.sessionDir
  process.env.REAL_KB = repositoryRoot
  process.env.ADAPTER_LOG_DIR = join(harness.root, "adapter-log")
  process.env.KNOWLEDGE_MIN_MESSAGES = "0"
  if (options.observation === undefined) delete process.env.KNOWLEDGE_OBSERVE
  else process.env.KNOWLEDGE_OBSERVE = options.observation

  try {
    return await callback()
  } finally {
    for (const [name, value] of previous) {
      if (value === undefined) delete process.env[name]
      else process.env[name] = value
    }
  }
}

async function createFakeCore(
  harness: Harness,
  options: FakeCoreOptions = {},
): Promise<string> {
  const coreRoot = join(harness.root, "fake-core")
  const scriptsDir = join(coreRoot, "scripts")
  const missing = new Set(options.missing ?? [])
  await mkdir(scriptsDir, { recursive: true })
  await mkdir(join(harness.root, "adapter-log"), { recursive: true })

  for (const name of ["session-init", "session-file"]) {
    if (!missing.has(name)) {
      await symlink(join(repositoryRoot, "scripts", name), join(scriptsDir, name))
    }
  }

  if (!missing.has("session-append")) {
    await writeFile(join(scriptsDir, "session-append"), `#!/usr/bin/env bash
set -eu
count_file="$ADAPTER_LOG_DIR/append.count"
count=0
[[ -f "$count_file" ]] && count="$(<"$count_file")"
count=$((count + 1))
printf '%s\\n' "$count" > "$count_file"
if [[ "\${FAIL_APPEND_BEFORE_ONCE:-0}" == 1 && "$count" == 1 ]]; then
  file="$2"
  chmod u-w "$file"
  set +e
  "$REAL_KB/scripts/session-append" "$@"
  status=$?
  set -e
  chmod u+w "$file"
  exit "$status"
fi
if [[ "\${FAIL_APPEND_POST_WRITE_ONCE:-0}" == 1 && "$count" == 1 ]]; then
  "$REAL_KB/scripts/session-append" "$@"
  exit 75
fi
exec "$REAL_KB/scripts/session-append" "$@"
`)
    await chmod(join(scriptsDir, "session-append"), 0o700)
  }

  if (!missing.has("session-flush")) {
    await writeFile(join(scriptsDir, "session-flush"), `#!/usr/bin/env bash
set -eu
count_file="$ADAPTER_LOG_DIR/flush.count"
count=0
[[ -f "$count_file" ]] && count="$(<"$count_file")"
count=$((count + 1))
printf '%s\\n' "$count" > "$count_file"
if [[ "\${FAIL_FLUSH_ONCE:-0}" == 1 && "$count" == 1 ]]; then
  pending_dir="$KB_CONTENT_DIR/observations/pending"
  chmod u-w "$pending_dir"
  set +e
  "$REAL_KB/scripts/session-flush" "$@"
  status=$?
  set -e
  chmod u+w "$pending_dir"
  exit "$status"
fi
exec "$REAL_KB/scripts/session-flush" "$@"
`)
    await chmod(join(scriptsDir, "session-flush"), 0o700)
  }

  if (!missing.has("session-context")) {
    await writeFile(join(scriptsDir, "session-context"), `#!/usr/bin/env bash
set -eu
count_file="$ADAPTER_LOG_DIR/context.count"
count=0
[[ -f "$count_file" ]] && count="$(<"$count_file")"
count=$((count + 1))
printf '%s\\n' "$count" > "$count_file"
exec "$REAL_KB/scripts/session-context" "$@"
`)
    await chmod(join(scriptsDir, "session-context"), 0o700)
  }

  return coreRoot
}

async function counter(harness: Harness, name: string): Promise<number> {
  return Number(await readFile(join(harness.root, "adapter-log", name), "utf8"))
}

async function sessionBufferNames(harness: Harness): Promise<string[]> {
  return (await readdir(harness.sessionDir)).sort()
}

async function pendingFiles(harness: Harness): Promise<string[]> {
  const names = await readdir(join(harness.contentDir, "observations", "pending"))
  return names.filter((name) => name.endsWith(".md")).sort()
}

async function pendingBodies(harness: Harness): Promise<string[]> {
  const files = await pendingFiles(harness)
  return Promise.all(
    files.map((file) =>
      readFile(join(harness.contentDir, "observations", "pending", file), "utf8"),
    ),
  )
}

async function onlyPendingBody(harness: Harness): Promise<string> {
  const bodies = await pendingBodies(harness)
  assert.equal(bodies.length, 1)
  return bodies[0]
}

async function appendThree(
  handlers: Lifecycle,
  label: string,
  timestampStart: number,
): Promise<void> {
  const messages: Array<["user" | "assistant", string]> = [
    ["user", label + " user 1"],
    ["assistant", label + " assistant"],
    ["user", label + " user 2"],
  ]
  for (const [index, [role, text]] of messages.entries()) {
    const message = role === "user"
      ? userMessage(timestampStart + index, text)
      : assistantMessage(timestampStart + index, [{ type: "text", text }])
    await handlers.messageEnd(messageEndEvent(message), handlers.context)
  }
}

test("registers current Pi lifecycle handlers and captures supported message text", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      const pi = await loadPi()
      const handlers = lifecycle(pi, () => join(harness.root, "persistent.jsonl"))
      await handlers.sessionStart(sessionStartEvent(), handlers.context)

      const plainUser = messageEndEvent(userMessage(1, "plain user"))
      await handlers.messageEnd(plainUser, handlers.context)
      await handlers.messageEnd(plainUser, handlers.context)
      await handlers.messageEnd(
        messageEndEvent(userMessage(2, [
          { type: "text", text: "structured user" },
          { type: "image", data: "image-data", mimeType: "image/png" },
        ])),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(assistantMessage(3, [
          { type: "thinking", thinking: "hidden reasoning" },
          { type: "toolCall", id: "tool-call", name: "test-tool", arguments: {} },
          { type: "text", text: "structured assistant" },
        ])),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(userMessage(4, "")),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(userMessage(5, [{ type: "text", text: "" }])),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(userMessage(6, [
          { type: "image", data: "image-only-data", mimeType: "image/png" },
        ])),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(assistantMessage(7, [])),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(toolResultMessage(8, "tool result")),
        handlers.context,
      )
      await handlers.messageEnd(
        messageEndEvent(customRoleMessage(9)),
        handlers.context,
      )

      const firstPrompt = await handlers.beforeAgentStart(
        beforeAgentStartEvent("earlier prompt"),
        handlers.context,
      )
      const secondPrompt = await handlers.beforeAgentStart(
        beforeAgentStartEvent("later prompt"),
        handlers.context,
      )
      assert.ok(firstPrompt)
      assert.ok(secondPrompt)
      assert.match(firstPrompt.systemPrompt ?? "", /^earlier prompt\n\n/)
      assert.match(secondPrompt.systemPrompt ?? "", /^later prompt\n\n/)
      assert.match(secondPrompt.systemPrompt ?? "", /Topic areas/)
      assert.equal(await counter(harness, "context.count"), 1)

      await handlers.shutdown(shutdownEvent(), handlers.context)
      const body = await onlyPendingBody(harness)
      assert.equal(await counter(harness, "append.count"), 3)
      assert.match(body, /### user/)
      assert.match(body, /plain user/)
      assert.match(body, /structured user/)
      assert.match(body, /### assistant/)
      assert.match(body, /structured assistant/)
      assert.doesNotMatch(body, /hidden reasoning/)
      assert.doesNotMatch(body, /tool result/)
      assert.doesNotMatch(body, /custom content/)
      assert.doesNotMatch(body, /image-only-data/)
    })
  })
})

test("disabled observation creates no buffer or observation", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "0" }, async () => {
      const pi = await loadPi()
      const handlers = lifecycle(pi, () => join(harness.root, "disabled.jsonl"))
      await handlers.sessionStart(sessionStartEvent(), handlers.context)
      await handlers.messageEnd(
        messageEndEvent(userMessage(1, "not captured")),
        handlers.context,
      )
      await handlers.beforeAgentStart(
        beforeAgentStartEvent("base"),
        handlers.context,
      )
      await handlers.shutdown(shutdownEvent(), handlers.context)

      assert.deepEqual(await sessionBufferNames(harness), [])
      assert.deepEqual(await pendingFiles(harness), [])
    })
  })
})

test("unset observation enables capture", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: undefined }, async () => {
      const pi = await loadPi()
      const handlers = lifecycle(pi, () => join(harness.root, "default-enabled.jsonl"))
      await handlers.sessionStart(sessionStartEvent(), handlers.context)
      await appendThree(handlers, "default enabled", 10)
      await handlers.shutdown(shutdownEvent(), handlers.context)

      assert.equal((await pendingFiles(harness)).length, 1)
      assert.match(await onlyPendingBody(harness), /default enabled assistant/)
    })
  })
})

test("uses stable persistent and generated ephemeral session identities", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      const persistentSessionFile = join(harness.root, "persistent.jsonl")
      const persistent = lifecycle(await loadPi(), () => persistentSessionFile)
      await persistent.sessionStart(sessionStartEvent(), persistent.context)
      assert.deepEqual(await sessionBufferNames(harness), ["session-persistent.jsonl"])
      await appendThree(persistent, "persistent", 20)
      await persistent.shutdown(shutdownEvent(), persistent.context)

      const ephemeral = lifecycle(await loadPi(), () => undefined)
      await ephemeral.sessionStart(sessionStartEvent(), ephemeral.context)
      const ephemeralBuffers = await sessionBufferNames(harness)
      assert.equal(ephemeralBuffers.length, 1)
      assert.match(ephemeralBuffers[0], /^session-[0-9a-f-]+\.jsonl$/)
      await appendThree(ephemeral, "ephemeral", 30)
      await ephemeral.shutdown(shutdownEvent(), ephemeral.context)

      assert.deepEqual(await sessionBufferNames(harness), [])
      assert.equal((await pendingFiles(harness)).length, 2)
    })
  })
})

test("recovers new, resume, fork, and reload sessions in fresh instances", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      let currentSessionFile = join(harness.root, "new-session.jsonl")
      const currentContext = (): TestContext => ({
        sessionManager: { getSessionFile: () => currentSessionFile },
      })

      const first = lifecycle(await loadPi(), () => currentSessionFile)
      await first.sessionStart(sessionStartEvent(), first.context)
      await appendThree(first, "new", 40)
      const firstSessionFile = currentSessionFile
      currentSessionFile = join(harness.root, "resume-session.jsonl")
      await first.shutdown(shutdownEvent("new", currentSessionFile), first.context)

      const second = lifecycle(await loadPi(), () => currentSessionFile)
      await second.sessionStart(sessionStartEvent("new", firstSessionFile), second.context)
      await appendThree(second, "resume", 50)
      const secondSessionFile = currentSessionFile
      currentSessionFile = join(harness.root, "fork-session.jsonl")
      await second.shutdown(shutdownEvent("resume", currentSessionFile), second.context)

      const third = lifecycle(await loadPi(), () => currentSessionFile)
      await third.sessionStart(sessionStartEvent("resume", secondSessionFile), third.context)
      await appendThree(third, "fork", 60)
      const thirdSessionFile = currentSessionFile
      currentSessionFile = join(harness.root, "after-fork.jsonl")
      await third.shutdown(shutdownEvent("fork", currentSessionFile), third.context)

      const fourth = lifecycle(await loadPi(), () => currentSessionFile)
      await fourth.sessionStart(sessionStartEvent("fork", thirdSessionFile), fourth.context)
      await fourth.shutdown(shutdownEvent(), fourth.context)

      currentSessionFile = join(harness.root, "reload-session.jsonl")
      const reloadSource = lifecycle(await loadPi(), () => currentSessionFile)
      await reloadSource.sessionStart(sessionStartEvent(), reloadSource.context)
      await appendThree(reloadSource, "reload before", 70)
      const reload = lifecycle(await loadPi(), () => currentSessionFile)
      await reload.sessionStart(sessionStartEvent("reload"), reload.context)
      await appendThree(reload, "reload after", 80)
      await reload.shutdown(shutdownEvent(), reload.context)

      const bodies = await pendingBodies(harness)
      assert.equal(bodies.length, 5)
      for (const label of ["new", "resume", "fork", "reload before", "reload after"]) {
        assert.ok(bodies.some((body) => body.includes(label)))
      }
    })
  })
})

test("retries a pre-write append failure without host redelivery", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      process.env.FAIL_APPEND_BEFORE_ONCE = "1"
      const handlers = lifecycle(await loadPi(), () => join(harness.root, "pre-write.jsonl"))
      await handlers.sessionStart(sessionStartEvent(), handlers.context)
      await handlers.messageEnd(
        messageEndEvent(userMessage(90, "pre-write retry")),
        handlers.context,
      )
      await handlers.shutdown(shutdownEvent(), handlers.context)

      assert.equal(await counter(harness, "append.count"), 2)
      assert.match(await onlyPendingBody(harness), /pre-write retry/)
    })
  })
})

test("preserves a post-write append duplicate under at-least-once delivery", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      process.env.FAIL_APPEND_POST_WRITE_ONCE = "1"
      const handlers = lifecycle(await loadPi(), () => join(harness.root, "post-write.jsonl"))
      await handlers.sessionStart(sessionStartEvent(), handlers.context)
      await handlers.messageEnd(
        messageEndEvent(userMessage(91, "post-write retry")),
        handlers.context,
      )
      await handlers.shutdown(shutdownEvent(), handlers.context)

      assert.equal(await counter(harness, "append.count"), 2)
      const body = await onlyPendingBody(harness)
      assert.equal((body.match(/post-write retry/g) ?? []).length, 2)
    })
  })
})

test("recovers a failed shutdown flush in a fresh extension instance", async () => {
  await withHarness(async (harness) => {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, { knowledgeBase: fakeCore, observation: "1" }, async () => {
      process.env.FAIL_FLUSH_ONCE = "1"
      const sessionFile = join(harness.root, "failed-flush.jsonl")
      const old = lifecycle(await loadPi(), () => sessionFile)
      await old.sessionStart(sessionStartEvent(), old.context)
      await appendThree(old, "failed flush", 100)
      await old.shutdown(shutdownEvent("reload"), old.context)

      assert.equal(await counter(harness, "flush.count"), 1)
      assert.deepEqual(await pendingFiles(harness), [])
      assert.deepEqual(await sessionBufferNames(harness), ["session-failed-flush.jsonl"])

      const fresh = lifecycle(await loadPi(), () => sessionFile)
      await fresh.sessionStart(sessionStartEvent("reload"), fresh.context)
      assert.equal(await counter(harness, "flush.count"), 2)
      assert.equal((await pendingFiles(harness)).length, 1)
      await fresh.shutdown(shutdownEvent(), fresh.context)
      assert.equal(await counter(harness, "flush.count"), 3)
    })
  })
})

test("disables itself when knowledge-base configuration or core commands are missing", async () => {
  await withHarness(async (harness) => {
    await withEnvironment(harness, { knowledgeBase: undefined, observation: "1" }, async () => {
      const pi = await loadPi()
      assert.deepEqual(Object.keys(pi.handlers), [])
    })

    const incompleteCore = await createFakeCore(harness, {
      missing: ["session-append", "session-context", "session-flush"],
    })
    await withEnvironment(
      harness,
      { knowledgeBase: incompleteCore, observation: "1" },
      async () => {
        const pi = await loadPi()
        const handlers = lifecycle(pi, () => join(harness.root, "missing-commands.jsonl"))
        await handlers.sessionStart(sessionStartEvent(), handlers.context)
        await handlers.messageEnd(
          messageEndEvent(userMessage(110, "missing command")),
          handlers.context,
        )
        await handlers.beforeAgentStart(
          beforeAgentStartEvent("base"),
          handlers.context,
        )
        await handlers.shutdown(shutdownEvent(), handlers.context)

        assert.deepEqual(await pendingFiles(harness), [])
      },
    )
  })
})

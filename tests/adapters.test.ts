import { execFile as execFileCallback } from "node:child_process"
import { mkdtemp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { promisify } from "node:util"
import type { Hooks as OpenCodeSdkHooks } from "@opencode-ai/plugin"
import type {
  Event as OpenCodeEvent,
  Part as OpenCodePart,
  UserMessage as OpenCodeUserMessage,
} from "@opencode-ai/sdk"
import type {
  BeforeAgentStartEvent,
  ExtensionAPI,
  ExtensionContext,
  ExtensionEvent,
  ExtensionFactory,
  ExtensionHandler,
  MessageEndEvent,
  SessionShutdownEvent,
  SessionStartEvent,
} from "@earendil-works/pi-coding-agent"
import { test } from "node:test"
import assert from "node:assert/strict"

const execFile = promisify(execFileCallback)
const repositoryRoot = dirname(dirname(fileURLToPath(import.meta.url)))

type Harness = {
  root: string
  contentDir: string
  sessionDir: string
}

type OpenCodeClient = {
  session: {
    message: (input: { path: { id: string; messageID: string } }) => Promise<{
      data?: { parts: unknown }
    }>
  }
}

type OpenCodeHooks = {
  event: NonNullable<OpenCodeSdkHooks["event"]>
  "chat.message": NonNullable<OpenCodeSdkHooks["chat.message"]>
  "experimental.chat.system.transform": NonNullable<
    OpenCodeSdkHooks["experimental.chat.system.transform"]
  >
  dispose: NonNullable<OpenCodeSdkHooks["dispose"]>
}

type OpenCodePlugin = (input: { client: OpenCodeClient }) => Promise<OpenCodeHooks>

type PiHandler = ExtensionHandler<ExtensionEvent>

type PiContext = ExtensionContext

type PiMock = {
  on: (event: string, handler: PiHandler) => void
}

function openCodeSessionCreatedEvent(id: string): Extract<OpenCodeEvent, { type: "session.created" }> {
  return {
    type: "session.created",
    properties: {
      info: {
        id,
        projectID: "test-project",
        directory: "/tmp/knowledge-adapter",
        title: "Adapter test",
        version: "1",
        time: { created: 1, updated: 1 },
      },
    },
  }
}

function openCodeAssistantUpdatedEvent(
  sessionID: string,
  messageID: string,
): Extract<OpenCodeEvent, { type: "message.updated" }> {
  return {
    type: "message.updated",
    properties: {
      info: {
        id: messageID,
        sessionID,
        role: "assistant",
        time: { created: 1, completed: 2 },
        parentID: "parent-message",
        modelID: "test-model",
        providerID: "test-provider",
        mode: "primary",
        path: { cwd: "/tmp/knowledge-adapter", root: "/tmp/knowledge-adapter" },
        cost: 0,
        tokens: {
          input: 0,
          output: 0,
          reasoning: 0,
          cache: { read: 0, write: 0 },
        },
      },
    },
  }
}

function openCodeTextPart(text: string): OpenCodePart {
  return {
    id: "text-part",
    sessionID: "test-session",
    messageID: "assistant-1",
    type: "text",
    text,
  }
}

function openCodeUserMessage(id: string): OpenCodeUserMessage {
  return {
    id,
    sessionID: "test-session",
    role: "user",
    time: { created: 1 },
    agent: "default",
    model: { providerID: "test-provider", modelID: "test-model" },
  }
}

function piSessionStartEvent(
  reason: SessionStartEvent["reason"] = "startup",
  previousSessionFile?: string,
): SessionStartEvent {
  return { type: "session_start", reason, previousSessionFile }
}

function piMessageEndEvent(
  role: "user" | "assistant",
  timestamp: number | string,
  content: string,
): MessageEndEvent {
  return {
    type: "message_end",
    message: { role, timestamp, content } as MessageEndEvent["message"],
  }
}

function piShutdownEvent(
  reason: SessionShutdownEvent["reason"] = "quit",
  targetSessionFile?: string,
): SessionShutdownEvent {
  return { type: "session_shutdown", reason, targetSessionFile }
}

function piBeforeAgentStartEvent(): BeforeAgentStartEvent {
  return {
    type: "before_agent_start",
    prompt: "test prompt",
    images: undefined,
    systemPrompt: "base",
    systemPromptOptions: {} as BeforeAgentStartEvent["systemPromptOptions"],
  }
}

async function createHarness(): Promise<Harness> {
  const root = await mkdtemp(join(tmpdir(), "knowledge-adapter-"))
  const contentDir = join(root, "content")
  const sessionDir = join(root, "sessions")
  await mkdir(join(contentDir, "knowledge"), { recursive: true })
  await mkdir(join(contentDir, "observations", "pending"), { recursive: true })
  await mkdir(join(contentDir, "observations", "archived"), { recursive: true })
  await mkdir(join(contentDir, "questions", "open"), { recursive: true })
  await mkdir(join(contentDir, "questions", "resolved"), { recursive: true })
  await mkdir(join(contentDir, "sources"), { recursive: true })
  await writeFile(join(contentDir, ".gitkeep"), "")
  await execFile("git", ["init", "-q"], { cwd: contentDir })
  await execFile("git", ["config", "user.email", "test@test.com"], { cwd: contentDir })
  await execFile("git", ["config", "user.name", "Adapter Test"], { cwd: contentDir })
  await execFile("git", ["add", ".gitkeep"], { cwd: contentDir })
  await execFile("git", ["commit", "-q", "-m", "init"], { cwd: contentDir })
  await mkdir(sessionDir, { recursive: true })
  return { root, contentDir, sessionDir }
}

async function withEnvironment<T>(
  harness: Harness,
  observe: "0" | "1" | undefined,
  callback: () => Promise<T>,
): Promise<T> {
  const names = [
    "KNOWLEDGE_BASE",
    "KB_CONTENT_DIR",
    "SESSION_DIR",
    "KNOWLEDGE_OBSERVE",
    "KNOWLEDGE_MIN_MESSAGES",
    "ADAPTER_LOG_DIR",
    "FAIL_APPEND_ONCE",
    "FAIL_APPEND_POST_WRITE_ONCE",
    "FAIL_FLUSH_ONCE",
    "REAL_KB",
  ]
  const previous = new Map<string, string | undefined>()
  for (const name of names) previous.set(name, process.env[name])
  process.env.KNOWLEDGE_BASE = repositoryRoot
  process.env.KB_CONTENT_DIR = harness.contentDir
  process.env.SESSION_DIR = harness.sessionDir
  if (observe === undefined) delete process.env.KNOWLEDGE_OBSERVE
  else process.env.KNOWLEDGE_OBSERVE = observe
  process.env.KNOWLEDGE_MIN_MESSAGES = "0"
  try {
    return await callback()
  } finally {
    for (const [name, value] of previous) {
      if (value === undefined) delete process.env[name]
      else process.env[name] = value
    }
  }
}

async function loadAdapter<T>(relativePath: string): Promise<T> {
  const path = join(repositoryRoot, relativePath)
  const moduleUrl = pathToFileURL(path).href + "?test=" + randomUUID()
  const module = await import(moduleUrl) as { default: T }
  return module.default
}

async function pendingFiles(harness: Harness): Promise<string[]> {
  const names = await readdir(join(harness.contentDir, "observations", "pending"))
  return names.filter((name) => name.endsWith(".md"))
}

async function onlyPendingBody(harness: Harness): Promise<string> {
  const files = await pendingFiles(harness)
  assert.equal(files.length, 1)
  return readFile(join(harness.contentDir, "observations", "pending", files[0]), "utf8")
}

async function makePiHandlers(): Promise<{
  handlers: Map<string, PiHandler>
  context: PiContext
}> {
  const handlers = new Map<string, PiHandler>()
  const pi: PiMock = {
    on(event, handler) {
      handlers.set(event, handler)
    },
  }
  const extension = await loadAdapter<ExtensionFactory>("scripts/adapters/pi/knowledge.ts")
  extension(pi as unknown as ExtensionAPI)
  return {
    handlers,
    context: {
      sessionManager: { getSessionFile: () => join(tmpdir(), "pi-session.jsonl") },
    } as unknown as PiContext,
  }
}

async function createFakeCore(harness: Harness): Promise<string> {
  const coreRoot = join(harness.root, "fake-core")
  const scriptsDir = join(coreRoot, "scripts")
  await mkdir(scriptsDir, { recursive: true })
  await mkdir(join(harness.root, "adapter-log"), { recursive: true })
  await writeFile(join(scriptsDir, "session-init"), `#!/usr/bin/env bash
set -eu
session_id=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --session-id ]]; then session_id="$2"; shift 2; else shift; fi
done
file="$SESSION_DIR/session-$session_id.jsonl"
touch "$file"
printf '%s\\n' "$file"
`)
  await writeFile(join(scriptsDir, "session-append"), `#!/usr/bin/env bash
set -eu
count_file="$ADAPTER_LOG_DIR/append.count"
count=0
[[ -f "$count_file" ]] && count="$(<"$count_file")"
count=$((count + 1))
printf '%s\\n' "$count" > "$count_file"
if [[ "\${FAIL_APPEND_ONCE:-0}" == 1 && "$count" == 1 ]]; then
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
  await writeFile(join(scriptsDir, "session-file"), `#!/usr/bin/env bash
set -eu
exec "$REAL_KB/scripts/session-file" "$@"
`)
  await writeFile(join(scriptsDir, "session-context"), "#!/usr/bin/env bash\nprintf '%s\\n' 'fake context'\n")
  for (const name of ["session-init", "session-append", "session-flush", "session-file", "session-context"]) {
    await execFile("chmod", ["700", join(scriptsDir, name)])
  }
  return coreRoot
}

async function readCounter(harness: Harness, name: string): Promise<number> {
  return Number(await readFile(join(harness.root, "adapter-log", name), "utf8"))
}

test("OpenCode captures messages, deduplicates events, and injects context", async () => {
  const harness = await createHarness()
  try {
    await withEnvironment(harness, "1", async () => {
      const messageCalls: string[] = []
      const plugin = await loadAdapter<OpenCodePlugin>("scripts/adapters/opencode/knowledge.ts")
      const hooks = await plugin({
        client: {
          session: {
            async message(input) {
              messageCalls.push(input.path.messageID)
              return { data: { parts: [openCodeTextPart("assistant answer")] } }
            },
          },
        },
      })
      const sessionID = "opencode-lifecycle"
      await hooks.event({
        event: openCodeSessionCreatedEvent(sessionID),
      })
      await hooks["chat.message"](
        { sessionID, messageID: "user-1" },
        { message: openCodeUserMessage("user-1"), parts: [openCodeTextPart("user question")] },
      )
      await hooks["chat.message"](
        { sessionID, messageID: "user-1" },
        { message: openCodeUserMessage("user-1"), parts: [openCodeTextPart("user question")] },
      )
      const assistantEvent = { event: openCodeAssistantUpdatedEvent(sessionID, "assistant-1") }
      await hooks.event(assistantEvent)
      await hooks.event(assistantEvent)
      const system = ["base system prompt"]
      await hooks["experimental.chat.system.transform"](
        {} as Parameters<NonNullable<OpenCodeSdkHooks["experimental.chat.system.transform"]>>[0],
        { system },
      )
      await hooks.dispose()

      assert.equal(messageCalls.length, 1)
      assert.equal((await pendingFiles(harness)).length, 1)
      assert.match(system[1], /Topic areas/)
      const body = await onlyPendingBody(harness)
      assert.match(body, /user question/)
      assert.match(body, /assistant answer/)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("Pi captures messages, deduplicates message_end, injects context, and flushes at shutdown", async () => {
  const harness = await createHarness()
  try {
    await withEnvironment(harness, "1", async () => {
      const { handlers, context } = await makePiHandlers()
      const sessionStart = handlers.get("session_start")
      const messageEnd = handlers.get("message_end")
      const beforeAgentStart = handlers.get("before_agent_start")
      const shutdown = handlers.get("session_shutdown")
      assert.ok(sessionStart)
      assert.ok(messageEnd)
      assert.ok(beforeAgentStart)
      assert.ok(shutdown)

      await sessionStart(piSessionStartEvent(), context)
      const userEvent = piMessageEndEvent("user", 1, "user prompt")
      const assistantEvent = piMessageEndEvent("assistant", 2, "assistant reply")
      await messageEnd(userEvent, context)
      await messageEnd(userEvent, context)
      await messageEnd(assistantEvent, context)
      await messageEnd(assistantEvent, context)
      const result = await beforeAgentStart(piBeforeAgentStartEvent(), context) as unknown as {
        systemPrompt: string
      }
      await shutdown(piShutdownEvent(), context)

      assert.match(result.systemPrompt, /Topic areas/)
      assert.equal((await pendingFiles(harness)).length, 1)
      const body = await onlyPendingBody(harness)
      assert.match(body, /user prompt/)
      assert.match(body, /assistant reply/)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("Pi flushes each session across fresh replacement instances", async () => {
  const harness = await createHarness()
  try {
    await withEnvironment(harness, "1", async () => {
      let sessionFile = join(harness.root, "first.jsonl")
      const context = {
        sessionManager: { getSessionFile: () => sessionFile },
      } as unknown as PiContext
      const getHandlers = async (): Promise<{
        sessionStart: PiHandler
        messageEnd: PiHandler
        shutdown: PiHandler
      }> => {
        const { handlers } = await makePiHandlers()
        const sessionStart = handlers.get("session_start")
        const messageEnd = handlers.get("message_end")
        const shutdown = handlers.get("session_shutdown")
        if (!sessionStart || !messageEnd || !shutdown) {
          throw new Error("Pi lifecycle handlers were not registered")
        }
        return { sessionStart, messageEnd, shutdown }
      }

      let { sessionStart, messageEnd, shutdown } = await getHandlers()

      const addMessages = async (label: string, appendMessage: PiHandler) => {
        const roles: Array<"user" | "assistant"> = ["user", "assistant", "user"]
        for (const [index, role] of roles.entries()) {
          await appendMessage(
            piMessageEndEvent(role, label + index, label + " message " + index),
            context,
          )
        }
      }

      await sessionStart(piSessionStartEvent(), context)
      await addMessages("first", messageEnd)
      sessionFile = join(harness.root, "second.jsonl")
      await shutdown(piShutdownEvent("new", sessionFile), context)
      const secondHandlers = await getHandlers()
      sessionStart = secondHandlers.sessionStart
      messageEnd = secondHandlers.messageEnd
      shutdown = secondHandlers.shutdown
      await sessionStart(
        piSessionStartEvent("new", join(harness.root, "first.jsonl")),
        context,
      )
      await addMessages("second", messageEnd)
      sessionFile = join(harness.root, "third.jsonl")
      await shutdown(piShutdownEvent("fork", sessionFile), context)
      const thirdHandlers = await getHandlers()
      sessionStart = thirdHandlers.sessionStart
      messageEnd = thirdHandlers.messageEnd
      shutdown = thirdHandlers.shutdown
      await sessionStart(
        piSessionStartEvent("fork", join(harness.root, "second.jsonl")),
        context,
      )
      await addMessages("third", messageEnd)
      await shutdown(piShutdownEvent(), context)

      assert.equal((await pendingFiles(harness)).length, 3)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("disabled observation does not create buffers or observations in either adapter", async () => {
  const harness = await createHarness()
  try {
    await withEnvironment(harness, "0", async () => {
      const opencode = await loadAdapter<OpenCodePlugin>("scripts/adapters/opencode/knowledge.ts")
      const openCodeHooks = await opencode({
        client: { session: { async message() { return { data: { parts: [] } } } } },
      })
      await openCodeHooks.event({
        event: openCodeSessionCreatedEvent("disabled-opencode"),
      })
      await openCodeHooks["chat.message"](
        { sessionID: "disabled-opencode", messageID: "message-1" },
        { message: openCodeUserMessage("message-1"), parts: [openCodeTextPart("not captured")] },
      )
      await openCodeHooks.dispose()

      const { handlers, context } = await makePiHandlers()
      await handlers.get("session_start")?.(piSessionStartEvent(), context)
      await handlers.get("message_end")?.(
        piMessageEndEvent("user", 1, "not captured"),
        context,
      )
      await handlers.get("session_shutdown")?.(piShutdownEvent(), context)

      assert.deepEqual(await pendingFiles(harness), [])
      assert.deepEqual(await readdir(harness.sessionDir), [])
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("unset observation flag enables capture in both TypeScript adapters", async () => {
  const harness = await createHarness()
  try {
    await withEnvironment(harness, undefined, async () => {
      const opencode = await loadAdapter<OpenCodePlugin>("scripts/adapters/opencode/knowledge.ts")
      const openCodeHooks = await opencode({
        client: { session: { async message() { return { data: { parts: [] } } } } },
      })
      await openCodeHooks.event({ event: openCodeSessionCreatedEvent("default-opencode") })
      await openCodeHooks["chat.message"](
        { sessionID: "default-opencode", messageID: "message-1" },
        { message: openCodeUserMessage("message-1"), parts: [openCodeTextPart("default OpenCode")] },
      )
      await openCodeHooks.dispose()

      const { handlers, context } = await makePiHandlers()
      await handlers.get("session_start")?.(piSessionStartEvent(), context)
      await handlers.get("message_end")?.(
        piMessageEndEvent("user", 1, "default Pi"),
        context,
      )
      await handlers.get("session_shutdown")?.(piShutdownEvent(), context)

      assert.equal((await pendingFiles(harness)).length, 2)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("one-shot append and flush failures recover without host redelivery", async () => {
  const harness = await createHarness()
  try {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, "1", async () => {
      process.env.KNOWLEDGE_BASE = fakeCore
      process.env.REAL_KB = repositoryRoot
      process.env.ADAPTER_LOG_DIR = join(harness.root, "adapter-log")
      process.env.FAIL_APPEND_ONCE = "1"
      process.env.FAIL_FLUSH_ONCE = "1"

      const opencode = await loadAdapter<OpenCodePlugin>("scripts/adapters/opencode/knowledge.ts")
      const openCodeHooks = await opencode({
        client: { session: { async message() { return { data: { parts: [] } } } } },
      })
      const sessionID = "retry-opencode"
      await openCodeHooks.event({
        event: openCodeSessionCreatedEvent(sessionID),
      })
      const input = { sessionID, messageID: "retry-message" }
      const output = {
        message: openCodeUserMessage("retry-message"),
        parts: [openCodeTextPart("retry this append")],
      }
      await openCodeHooks["chat.message"](input, output)
      await openCodeHooks.dispose()
      await openCodeHooks.dispose()

      assert.equal(await readCounter(harness, "append.count"), 2)
      assert.equal(await readCounter(harness, "flush.count"), 2)
      assert.match(await onlyPendingBody(harness), /retry this append/)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("post-write append failures are retried with at-least-once persistence", async () => {
  const harness = await createHarness()
  try {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, "1", async () => {
      process.env.KNOWLEDGE_BASE = fakeCore
      process.env.REAL_KB = repositoryRoot
      process.env.ADAPTER_LOG_DIR = join(harness.root, "adapter-log")
      process.env.FAIL_APPEND_POST_WRITE_ONCE = "1"

      const opencode = await loadAdapter<OpenCodePlugin>("scripts/adapters/opencode/knowledge.ts")
      const openCodeHooks = await opencode({
        client: { session: { async message() { return { data: { parts: [] } } } } },
      })
      await openCodeHooks.event({ event: openCodeSessionCreatedEvent("post-write-retry") })
      await openCodeHooks["chat.message"](
        { sessionID: "post-write-retry", messageID: "retry-message" },
        {
          message: openCodeUserMessage("retry-message"),
          parts: [openCodeTextPart("post-write payload")],
        },
      )
      await openCodeHooks.dispose()

      assert.equal(await readCounter(harness, "append.count"), 2)
      const body = await onlyPendingBody(harness)
      assert.equal((body.match(/post-write payload/g) ?? []).length, 2)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("Pi retries a one-shot append without host redelivery", async () => {
  const harness = await createHarness()
  try {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, "1", async () => {
      process.env.KNOWLEDGE_BASE = fakeCore
      process.env.REAL_KB = repositoryRoot
      process.env.ADAPTER_LOG_DIR = join(harness.root, "adapter-log")
      process.env.FAIL_APPEND_ONCE = "1"
      const { handlers, context } = await makePiHandlers()
      const sessionStart = handlers.get("session_start")
      const messageEnd = handlers.get("message_end")
      const shutdown = handlers.get("session_shutdown")
      assert.ok(sessionStart)
      assert.ok(messageEnd)
      assert.ok(shutdown)
      await sessionStart(piSessionStartEvent(), context)
      await messageEnd(
        piMessageEndEvent("user", 1, "retry Pi append"),
        context,
      )
      await shutdown(piShutdownEvent(), context)

      assert.equal(await readCounter(harness, "append.count"), 2)
      assert.match(await onlyPendingBody(harness), /retry Pi append/)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

test("Pi recovers a failed replacement flush in a fresh extension instance", async () => {
  const harness = await createHarness()
  try {
    const fakeCore = await createFakeCore(harness)
    await withEnvironment(harness, "1", async () => {
      process.env.KNOWLEDGE_BASE = fakeCore
      process.env.REAL_KB = repositoryRoot
      process.env.ADAPTER_LOG_DIR = join(harness.root, "adapter-log")
      process.env.FAIL_FLUSH_ONCE = "1"
      let currentSessionFile = join(harness.root, "first.jsonl")
      const oldContext = {
        sessionManager: { getSessionFile: () => currentSessionFile },
      } as unknown as PiContext
      const old = await makePiHandlers()
      const oldSessionStart = old.handlers.get("session_start")
      const oldMessageEnd = old.handlers.get("message_end")
      const oldShutdown = old.handlers.get("session_shutdown")
      assert.ok(oldSessionStart)
      assert.ok(oldMessageEnd)
      assert.ok(oldShutdown)
      await oldSessionStart(piSessionStartEvent(), oldContext)
      const roles: Array<"user" | "assistant"> = ["user", "assistant", "user"]
      for (const [index, role] of roles.entries()) {
        await oldMessageEnd(
          piMessageEndEvent(role, index, "old session message " + index),
          oldContext,
        )
      }

      currentSessionFile = join(harness.root, "second.jsonl")
      await oldShutdown(piShutdownEvent("new", currentSessionFile), oldContext)
      assert.equal(await readCounter(harness, "flush.count"), 1)

      const fresh = await makePiHandlers()
      const freshSessionStart = fresh.handlers.get("session_start")
      const freshMessageEnd = fresh.handlers.get("message_end")
      const freshShutdown = fresh.handlers.get("session_shutdown")
      assert.ok(freshSessionStart)
      assert.ok(freshMessageEnd)
      assert.ok(freshShutdown)
      const freshContext = {
        sessionManager: { getSessionFile: () => currentSessionFile },
      } as unknown as PiContext
      await freshSessionStart(
        piSessionStartEvent("new", join(harness.root, "first.jsonl")),
        freshContext,
      )
      assert.equal(await readCounter(harness, "flush.count"), 2)

      await freshMessageEnd(
        piMessageEndEvent("user", 4, "new session message"),
        freshContext,
      )
      await freshShutdown(piShutdownEvent(), freshContext)

      const bodies = await Promise.all(
        (await pendingFiles(harness)).map((name) =>
          readFile(join(harness.contentDir, "observations", "pending", name), "utf8")),
      )
      assert.equal(bodies.length, 2)
      assert.ok(bodies.some((body) => body.includes("old session message 0")))
      assert.equal(await readCounter(harness, "flush.count"), 3)
    })
  } finally {
    await rm(harness.root, { recursive: true, force: true })
  }
})

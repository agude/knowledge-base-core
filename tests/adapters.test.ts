import { execFile as execFileCallback } from "node:child_process"
import { mkdtemp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises"
import { randomUUID } from "node:crypto"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"
import { promisify } from "node:util"
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
  event: (input: { event: Record<string, unknown> }) => Promise<void>
  "chat.message": (
    input: { sessionID: string; messageID?: string },
    output: { parts: unknown },
  ) => Promise<void>
  "experimental.chat.system.transform": (
    input: unknown,
    output: { system: string[] },
  ) => Promise<void>
  dispose: () => Promise<void>
}

type OpenCodePlugin = (input: { client: OpenCodeClient }) => Promise<OpenCodeHooks>

type PiHandler = (event: unknown, context: PiContext) => Promise<unknown> | unknown

type PiContext = {
  sessionManager: {
    getSessionFile: () => string | undefined
  }
}

type PiMock = {
  on: (event: string, handler: PiHandler) => void
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
  observe: "0" | "1",
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
    "FAIL_FLUSH_ONCE",
    "REAL_KB",
  ]
  const previous = new Map<string, string | undefined>()
  for (const name of names) previous.set(name, process.env[name])
  process.env.KNOWLEDGE_BASE = repositoryRoot
  process.env.KB_CONTENT_DIR = harness.contentDir
  process.env.SESSION_DIR = harness.sessionDir
  process.env.KNOWLEDGE_OBSERVE = observe
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
  const extension = await loadAdapter<(api: PiMock) => void>("scripts/adapters/pi/knowledge.ts")
  extension(pi)
  return {
    handlers,
    context: { sessionManager: { getSessionFile: () => join(tmpdir(), "pi-session.jsonl") } },
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
if [[ "\${FAIL_APPEND_ONCE:-0}" == 1 && "$count" == 1 ]]; then exit 1; fi
exec "$REAL_KB/scripts/session-append" "$@"
`)
  await writeFile(join(scriptsDir, "session-flush"), `#!/usr/bin/env bash
set -eu
count_file="$ADAPTER_LOG_DIR/flush.count"
count=0
[[ -f "$count_file" ]] && count="$(<"$count_file")"
count=$((count + 1))
printf '%s\\n' "$count" > "$count_file"
if [[ "\${FAIL_FLUSH_ONCE:-0}" == 1 && "$count" == 1 ]]; then exit 1; fi
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
              return { data: { parts: [{ type: "text", text: "assistant answer" }] } }
            },
          },
        },
      })
      const sessionID = "opencode-lifecycle"
      await hooks.event({
        event: { type: "session.created", properties: { info: { id: sessionID } } },
      })
      await hooks["chat.message"](
        { sessionID, messageID: "user-1" },
        { parts: [{ type: "text", text: "user question" }] },
      )
      await hooks["chat.message"](
        { sessionID, messageID: "user-1" },
        { parts: [{ type: "text", text: "user question" }] },
      )
      const assistantEvent = {
        event: {
          type: "message.updated",
          properties: {
            info: {
              id: "assistant-1",
              sessionID,
              role: "assistant",
              time: { completed: Date.now() },
            },
          },
        },
      }
      await hooks.event(assistantEvent)
      await hooks.event(assistantEvent)
      const system = ["base system prompt"]
      await hooks["experimental.chat.system.transform"]({}, { system })
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

      await sessionStart({}, context)
      const userEvent = { message: { role: "user", timestamp: 1, content: "user prompt" } }
      const assistantEvent = { message: { role: "assistant", timestamp: 2, content: "assistant reply" } }
      await messageEnd(userEvent, context)
      await messageEnd(userEvent, context)
      await messageEnd(assistantEvent, context)
      await messageEnd(assistantEvent, context)
      const result = await beforeAgentStart({ systemPrompt: "base" }, context) as {
        systemPrompt: string
      }
      await shutdown({}, context)

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
      const context: PiContext = { sessionManager: { getSessionFile: () => sessionFile } }
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
        for (const [index, role] of ["user", "assistant", "user"].entries()) {
          await appendMessage(
            { message: { role, timestamp: label + index, content: label + " message " + index } },
            context,
          )
        }
      }

      await sessionStart({}, context)
      await addMessages("first", messageEnd)
      sessionFile = join(harness.root, "second.jsonl")
      await shutdown({ reason: "new", targetSessionFile: sessionFile }, context)
      const secondHandlers = await getHandlers()
      sessionStart = secondHandlers.sessionStart
      messageEnd = secondHandlers.messageEnd
      shutdown = secondHandlers.shutdown
      await sessionStart({ reason: "new", previousSessionFile: join(harness.root, "first.jsonl") }, context)
      await addMessages("second", messageEnd)
      sessionFile = join(harness.root, "third.jsonl")
      await shutdown({ reason: "fork", targetSessionFile: sessionFile }, context)
      const thirdHandlers = await getHandlers()
      sessionStart = thirdHandlers.sessionStart
      messageEnd = thirdHandlers.messageEnd
      shutdown = thirdHandlers.shutdown
      await sessionStart({ reason: "fork", previousSessionFile: join(harness.root, "second.jsonl") }, context)
      await addMessages("third", messageEnd)
      await shutdown({}, context)

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
        event: { type: "session.created", properties: { info: { id: "disabled-opencode" } } },
      })
      await openCodeHooks["chat.message"](
        { sessionID: "disabled-opencode", messageID: "message-1" },
        { parts: [{ type: "text", text: "not captured" }] },
      )
      await openCodeHooks.dispose()

      const { handlers, context } = await makePiHandlers()
      await handlers.get("session_start")?.({}, context)
      await handlers.get("message_end")?.(
        { message: { role: "user", timestamp: 1, content: "not captured" } },
        context,
      )
      await handlers.get("session_shutdown")?.({}, context)

      assert.deepEqual(await pendingFiles(harness), [])
      assert.deepEqual(await readdir(harness.sessionDir), [])
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
        event: { type: "session.created", properties: { info: { id: sessionID } } },
      })
      const input = { sessionID, messageID: "retry-message" }
      const output = { parts: [{ type: "text", text: "retry this append" }] }
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
      await sessionStart({}, context)
      await messageEnd(
        { message: { role: "user", timestamp: 1, content: "retry Pi append" } },
        context,
      )
      await shutdown({}, context)

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
      const oldContext: PiContext = { sessionManager: { getSessionFile: () => currentSessionFile } }
      const old = await makePiHandlers()
      const oldSessionStart = old.handlers.get("session_start")
      const oldMessageEnd = old.handlers.get("message_end")
      const oldShutdown = old.handlers.get("session_shutdown")
      assert.ok(oldSessionStart)
      assert.ok(oldMessageEnd)
      assert.ok(oldShutdown)
      await oldSessionStart({ reason: "startup" }, oldContext)
      for (const [index, role] of ["user", "assistant", "user"].entries()) {
        await oldMessageEnd(
          { message: { role, timestamp: index, content: "old session message " + index } },
          oldContext,
        )
      }

      currentSessionFile = join(harness.root, "second.jsonl")
      await oldShutdown({ reason: "new", targetSessionFile: currentSessionFile }, oldContext)
      assert.equal(await readCounter(harness, "flush.count"), 1)

      const fresh = await makePiHandlers()
      const freshSessionStart = fresh.handlers.get("session_start")
      const freshMessageEnd = fresh.handlers.get("message_end")
      const freshShutdown = fresh.handlers.get("session_shutdown")
      assert.ok(freshSessionStart)
      assert.ok(freshMessageEnd)
      assert.ok(freshShutdown)
      const freshContext: PiContext = { sessionManager: { getSessionFile: () => currentSessionFile } }
      await freshSessionStart({
        reason: "new",
        previousSessionFile: join(harness.root, "first.jsonl"),
      }, freshContext)
      assert.equal(await readCounter(harness, "flush.count"), 2)

      await freshMessageEnd(
        { message: { role: "user", timestamp: 4, content: "new session message" } },
        freshContext,
      )
      await freshShutdown({ reason: "quit" }, freshContext)

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

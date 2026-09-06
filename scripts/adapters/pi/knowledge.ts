// Pi adapter for the neutral knowledge-base session API.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { execFile as execFileCallback } from "node:child_process"
import { existsSync } from "node:fs"
import { randomUUID } from "node:crypto"
import { basename, extname } from "node:path"
import { promisify } from "node:util"

const execFile = promisify(execFileCallback)
const KB = process.env.KNOWLEDGE_BASE ?? ""
const OBSERVE = process.env.KNOWLEDGE_OBSERVE !== "0"
const warnings = new Set<string>()

function warn(key: string, message: string): void {
  if (warnings.has(key)) return
  warnings.add(key)
  console.error("knowledge adapter: " + message)
}

function script(name: string): string {
  return KB + "/scripts/" + name
}

function sessionIDFromFile(sessionFile: string): string {
  return basename(sessionFile, extname(sessionFile))
}

type CommandResult = { ok: boolean; output: string }

async function run(name: string, args: string[], timeout = 10000): Promise<CommandResult> {
  try {
    const result = await execFile(script(name), args, {
      timeout,
      encoding: "utf-8",
    })
    return { ok: true, output: result.stdout.trim() }
  } catch (error) {
    const failure = error as { stderr?: string; message?: string }
    warn(name, name + " failed: " + (failure.stderr || failure.message || "unknown error"))
    return { ok: false, output: "" }
  }
}

type MessageContent = string | Array<{ type: string; text?: string }> | undefined

function text(content: MessageContent): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""
  return content
    .filter((part): part is { type: "text"; text: string } =>
      part.type === "text" && typeof part.text === "string")
    .map((part) => part.text)
    .join("\n")
}

export default function knowledge(pi: ExtensionAPI): void {
  if (!KB || !existsSync(script("session-init"))) return

  let sessionID: string = randomUUID()
  let file: string | undefined
  const appended = new Set<string>()
  let context: string | undefined

  async function init(id?: string): Promise<void> {
    if (id) sessionID = id
    if (file && existsSync(file)) return
    const result = await run("session-init", ["--session-id", sessionID])
    file = result.ok && result.output ? result.output : undefined
  }

  async function recoverSession(sessionFile: string | undefined): Promise<void> {
    if (!OBSERVE || !sessionFile) return
    const previousSessionID = sessionIDFromFile(sessionFile)
    if (!previousSessionID) return

    const result = await run("session-file", ["--session-id", previousSessionID])
    if (!result.ok || !result.output || !existsSync(result.output)) return
    await run("session-flush", [result.output], 15000)
  }

  async function flush(): Promise<void> {
    if (!OBSERVE || !file || !existsSync(file)) return
    const current = file
    const result = await run("session-flush", [current], 15000)
    if (result.ok) file = undefined
  }

  async function startSession(sessionFile?: string): Promise<void> {
    sessionID = sessionFile ? basename(sessionFile, extname(sessionFile)) : randomUUID()
    file = undefined
    await init()
  }

  async function append(role: "user" | "assistant", value: string): Promise<boolean> {
    if (!OBSERVE || !value) return true
    if (!file || !existsSync(file)) await init()
    if (!file) return false
    const args = ["--file", file, "--role", role, "--message", value]
    const result = await run("session-append", args)
    if (result.ok) return true

    // The host does not promise to redeliver a failed event. Retry the same
    // payload here while the adapter still owns it.
    return (await run("session-append", args)).ok
  }

  pi.on("session_start", async (event, ctx) => {
    if (!OBSERVE) return
    const currentSessionFile = ctx.sessionManager.getSessionFile()
    await recoverSession(event.previousSessionFile)
    if (event.reason === "reload") await recoverSession(currentSessionFile)
    await startSession(currentSessionFile)
  })

  pi.on("message_end", async (event) => {
    try {
      const role = event.message.role
      if (role !== "user" && role !== "assistant") return
      const timestamp = event.message.timestamp
      if (timestamp === undefined) return
      const key = sessionID + ":" + role + ":" + timestamp
      if (appended.has(key)) return
      if (await append(role, text(event.message.content))) appended.add(key)
    } catch (error) {
      warn("message_end", "message_end handler failed: " + String(error))
    }
  })

  pi.on("before_agent_start", async (event) => {
    try {
      if (context === undefined) context = (await run("session-context", [])).output
      if (context) return { systemPrompt: event.systemPrompt + "\n\n" + context }
    } catch (error) {
      warn("before_agent_start", "context injection failed: " + String(error))
    }
  })

  pi.on("session_shutdown", async () => {
    await flush()
  })
}

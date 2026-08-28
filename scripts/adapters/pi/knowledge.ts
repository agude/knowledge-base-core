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

async function run(name: string, args: string[], timeout = 10000): Promise<string> {
  try {
    const result = await execFile(script(name), args, {
      timeout,
      encoding: "utf-8",
    })
    return result.stdout.trim()
  } catch (error) {
    const failure = error as { stderr?: string; message?: string }
    warn(name, name + " failed: " + (failure.stderr || failure.message || "unknown error"))
    return ""
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

  let sessionID = randomUUID()
  let file: string | undefined
  const appended = new Set<string>()
  let context: string | undefined

  async function init(id?: string): Promise<void> {
    if (id) sessionID = id
    if (file && existsSync(file)) return
    file = (await run("session-init", ["--session-id", sessionID])) || undefined
  }

  async function append(role: "user" | "assistant", value: string): Promise<void> {
    if (!OBSERVE || !value) return
    if (!file || !existsSync(file)) await init()
    if (file) await run("session-append", ["--file", file, "--role", role, "--message", value])
  }

  pi.on("session_start", async (_event, ctx) => {
    if (!OBSERVE) return
    const sessionFile = ctx.sessionManager.getSessionFile()
    const id = sessionFile ? basename(sessionFile, extname(sessionFile)) : undefined
    await init(id)
  })

  pi.on("message_end", async (event) => {
    try {
      const role = event.message.role
      if (role !== "user" && role !== "assistant") return
      const timestamp = event.message.timestamp
      if (timestamp === undefined) return
      const key = role + ":" + timestamp
      if (appended.has(key)) return
      appended.add(key)
      await append(role, text(event.message.content))
    } catch (error) {
      warn("message_end", "message_end handler failed: " + String(error))
    }
  })

  pi.on("before_agent_start", async (event) => {
    try {
      if (context === undefined) context = await run("session-context", [])
      if (context) return { systemPrompt: event.systemPrompt + "\n\n" + context }
    } catch (error) {
      warn("before_agent_start", "context injection failed: " + String(error))
    }
  })

  pi.on("session_shutdown", async () => {
    if (!OBSERVE || !file || !existsSync(file)) return
    const current = file
    file = undefined
    await run("session-flush", [current], 15000)
  })
}

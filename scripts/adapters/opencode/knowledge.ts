// OpenCode adapter for the neutral knowledge-base session API.
//
// The plugin owns only OpenCode event translation. Buffer creation, path
// resolution, message encoding, flushing, and observation writes stay in the
// shared shell scripts.

import type { Plugin } from "@opencode-ai/plugin"
import { execFile as execFileCallback } from "node:child_process"
import { existsSync } from "node:fs"
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

function text(parts: unknown): string {
  if (!Array.isArray(parts)) return ""
  return parts
    .filter((part): part is { type: "text"; text: string } =>
      typeof part === "object" && part !== null &&
      (part as { type?: unknown }).type === "text" &&
      typeof (part as { text?: unknown }).text === "string")
    .map((part) => part.text)
    .join("\n")
}

export default (async ({ client }) => {
  if (!KB || !existsSync(script("session-init"))) return {}

  const files = new Map<string, string>()
  const children = new Set<string>()
  const appended = new Set<string>()
  let context: string | undefined

  async function init(id: string): Promise<void> {
    if (!OBSERVE || children.has(id) || files.has(id)) return
    const result = await run("session-init", ["--session-id", id])
    if (result.ok && result.output) files.set(id, result.output)
  }

  async function buffer(id: string): Promise<string | undefined> {
    const known = files.get(id)
    if (known && existsSync(known)) return known
    if (known) files.delete(id)
    await init(id)
    return files.get(id)
  }

  async function append(id: string, role: "user" | "assistant", value: string): Promise<boolean> {
    if (!OBSERVE || !value || children.has(id)) return true
    const file = await buffer(id)
    if (!file) return false
    const result = await run("session-append", ["--file", file, "--role", role, "--message", value])
    return result.ok
  }

  async function flush(id: string): Promise<boolean> {
    if (!OBSERVE) return true
    const file = files.get(id)
    if (!file || !existsSync(file)) {
      files.delete(id)
      return true
    }
    const result = await run("session-flush", [file], 15000)
    if (result.ok) files.delete(id)
    return result.ok
  }

  async function flushAll(): Promise<void> {
    await Promise.allSettled(Array.from(files.keys()).map((id) => flush(id)))
  }

  return {
    event: async ({ event }) => {
      try {
        if (event.type === "session.created") {
          const info = event.properties.info as { id: string; parentID?: string }
          if (info.parentID) children.add(info.id)
          else await init(info.id)
          return
        }

        if (event.type !== "message.updated") return
        const message = event.properties.info
        if (message.role !== "assistant" || !message.time.completed) return

        const key = "assistant:" + message.sessionID + ":" + message.id
        if (appended.has(key)) return
        if (!files.has(message.sessionID)) return

        const result = await client.session.message({
          path: { id: message.sessionID, messageID: message.id },
        })
        if (result.data) {
          if (await append(message.sessionID, "assistant", text(result.data.parts))) {
            appended.add(key)
          }
        }
      } catch (error) {
        warn("event", "event handler failed: " + String(error))
      }
    },

    "chat.message": async ({ sessionID, messageID }, { parts }) => {
      const key = messageID ? "user:" + sessionID + ":" + messageID : ""
      if (key && appended.has(key)) return
      if (await append(sessionID, "user", text(parts)) && key) {
        appended.add(key)
      }
    },

    "experimental.chat.system.transform": async (_input, { system }) => {
      if (context === undefined) context = (await run("session-context", [])).output
      if (context) system.push(context)
    },

    dispose: async () => {
      await flushAll()
    },
  }
}) satisfies Plugin

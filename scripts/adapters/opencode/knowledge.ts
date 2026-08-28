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

function text(parts: Array<{ type: string; text?: string }>): string {
  return parts
    .filter((part): part is { type: "text"; text: string } =>
      part.type === "text" && typeof part.text === "string")
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
    const file = await run("session-init", ["--session-id", id])
    if (file) files.set(id, file)
  }

  async function buffer(id: string): Promise<string | undefined> {
    const known = files.get(id)
    if (known && existsSync(known)) return known
    if (known) files.delete(id)
    await init(id)
    return files.get(id)
  }

  async function append(id: string, role: "user" | "assistant", value: string): Promise<void> {
    if (!OBSERVE || !value || children.has(id)) return
    const file = await buffer(id)
    if (file) await run("session-append", ["--file", file, "--role", role, "--message", value])
  }

  async function flush(id: string): Promise<void> {
    if (!OBSERVE) return
    const file = files.get(id)
    files.delete(id)
    if (file && existsSync(file)) await run("session-flush", [file], 15000)
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

        const key = message.sessionID + ":" + message.id
        if (appended.has(key)) return
        appended.add(key)
        if (!files.has(message.sessionID)) return

        const result = await client.session.message({
          path: { id: message.sessionID, messageID: message.id },
        })
        if (result.data) {
          await append(message.sessionID, "assistant", text(result.data.parts))
        }
      } catch (error) {
        warn("event", "event handler failed: " + String(error))
      }
    },

    "chat.message": async ({ sessionID }, { parts }) => {
      await append(sessionID, "user", text(parts))
    },

    "experimental.chat.system.transform": async (_input, { system }) => {
      if (context === undefined) context = await run("session-context", [])
      if (context) system.push(context)
    },

    dispose: async () => {
      await flushAll()
    },
  }
}) satisfies Plugin

// Pi adapter for the neutral knowledge-base session API.

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { execFile as execFileCallback } from "node:child_process"
import { randomUUID } from "node:crypto"
import { existsSync } from "node:fs"
import { basename, extname } from "node:path"
import { promisify } from "node:util"

const execFile = promisify(execFileCallback)
const KNOWLEDGE_BASE = process.env.KNOWLEDGE_BASE ?? ""
const OBSERVATION_ENABLED = process.env.KNOWLEDGE_OBSERVE !== "0"
const warnings = new Set<string>()

type CommandResult = {
  ok: boolean
  output: string
}

function warnOnce(key: string, message: string): void {
  if (warnings.has(key)) return
  warnings.add(key)
  console.error("knowledge adapter: " + message)
}

function commandPath(name: string): string {
  return KNOWLEDGE_BASE + "/scripts/" + name
}

function sessionIDFromFile(sessionFile: string): string {
  return basename(sessionFile, extname(sessionFile))
}

async function runCommand(
  name: string,
  args: string[],
  timeout = 10000,
): Promise<CommandResult> {
  try {
    const result = await execFile(commandPath(name), args, {
      encoding: "utf-8",
      timeout,
    })
    return { ok: true, output: result.stdout.trim() }
  } catch (error) {
    const failure = error as { message?: string; stderr?: string }
    const detail = failure.stderr || failure.message || "unknown error"
    warnOnce("command:" + name, `${name} failed: ${detail}`)
    return { ok: false, output: "" }
  }
}

function extractText(content: unknown): string {
  if (typeof content === "string") return content
  if (!Array.isArray(content)) return ""

  return content
    .filter((part): part is { type: "text"; text: string } => {
      if (typeof part !== "object" || part === null) return false
      const candidate = part as { type?: unknown; text?: unknown }
      return candidate.type === "text" && typeof candidate.text === "string"
    })
    .map((part) => part.text)
    .join("\n")
}

function handlerError(category: string, error: unknown): void {
  warnOnce(
    "handler:" + category,
    `${category} handler failed: ${String(error)}`,
  )
}

export default function knowledge(pi: ExtensionAPI): void {
  if (!KNOWLEDGE_BASE || !existsSync(commandPath("session-init"))) return

  let sessionID = randomUUID()
  let currentSessionFile: string | undefined
  let bufferFile: string | undefined
  let sessionActive = false
  let context: string | undefined
  const appendedEvents = new Set<string>()

  async function initializeBuffer(): Promise<void> {
    if (bufferFile && existsSync(bufferFile)) return
    bufferFile = undefined

    const result = await runCommand("session-init", ["--session-id", sessionID])
    if (result.ok && result.output) bufferFile = result.output
  }

  async function recoverSession(sessionFile: string | undefined): Promise<void> {
    if (!OBSERVATION_ENABLED || !sessionFile) return

    const previousSessionID = sessionIDFromFile(sessionFile)
    if (!previousSessionID) return

    const result = await runCommand("session-file", ["--session-id", previousSessionID])
    if (!result.ok || !result.output || !existsSync(result.output)) return

    await runCommand("session-flush", [result.output], 15000)
  }

  async function startSession(sessionFile: string | undefined): Promise<void> {
    const sameActiveSession = sessionActive && currentSessionFile === sessionFile
    if (sameActiveSession && bufferFile && existsSync(bufferFile)) return

    if (!sameActiveSession) {
      sessionID = sessionFile ? sessionIDFromFile(sessionFile) : randomUUID()
      currentSessionFile = sessionFile
      bufferFile = undefined
      appendedEvents.clear()
    }

    sessionActive = true
    await initializeBuffer()
  }

  async function appendMessage(
    role: "user" | "assistant",
    message: string,
  ): Promise<boolean> {
    if (!OBSERVATION_ENABLED || !message) return true

    await initializeBuffer()
    if (!bufferFile) return false

    const args = [
      "--file",
      bufferFile,
      "--role",
      role,
      "--message",
      message,
    ]
    const result = await runCommand("session-append", args)
    if (result.ok) return true

    // Pi does not promise to redeliver a failed event. Retry the same payload
    // while this adapter still owns it, preserving at-least-once persistence.
    return (await runCommand("session-append", args)).ok
  }

  async function flushSession(): Promise<void> {
    if (!OBSERVATION_ENABLED) return

    if (!bufferFile || !existsSync(bufferFile)) {
      bufferFile = undefined
      sessionActive = false
      appendedEvents.clear()
      return
    }

    const result = await runCommand("session-flush", [bufferFile], 15000)
    if (!result.ok) return

    bufferFile = undefined
    sessionActive = false
    appendedEvents.clear()
  }

  pi.on("session_start", async (event, ctx) => {
    if (!OBSERVATION_ENABLED) return

    try {
      const sessionFile = ctx.sessionManager.getSessionFile()
      await recoverSession(event.previousSessionFile)
      if (event.reason === "reload") await recoverSession(sessionFile)
      await startSession(sessionFile)
    } catch (error) {
      handlerError("session_start", error)
    }
  })

  pi.on("message_end", async (event) => {
    if (!OBSERVATION_ENABLED) return

    try {
      const role = event.message.role
      if (role !== "user" && role !== "assistant") return

      const message = extractText(event.message.content)
      if (!message) return

      const eventKey = [
        sessionID,
        role,
        String(event.message.timestamp),
        message,
      ].join(":")
      if (appendedEvents.has(eventKey)) return

      if (await appendMessage(role, message)) appendedEvents.add(eventKey)
    } catch (error) {
      handlerError("message_end", error)
    }
  })

  pi.on("before_agent_start", async (event) => {
    if (!OBSERVATION_ENABLED) return

    try {
      if (context === undefined) {
        const result = await runCommand("session-context", [])
        if (!result.ok) return
        context = result.output
      }
      if (!context) return

      return { systemPrompt: event.systemPrompt + "\n\n" + context }
    } catch (error) {
      handlerError("before_agent_start", error)
    }
  })

  pi.on("session_shutdown", async () => {
    if (!OBSERVATION_ENABLED) return

    try {
      await flushSession()
    } catch (error) {
      handlerError("session_shutdown", error)
    }
  })
}

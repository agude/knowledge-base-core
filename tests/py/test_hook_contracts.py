"""Host hook protocols: what each adapter reads on stdin and writes on stdout.

Claude hooks: session-start prints context as plain text; prompt, stop, and
end print nothing; pretool-allow prints a decision JSON object or nothing.
Codex hooks always print one JSON object; session-start's carries the
context. Contract: exit code and the protocol-level stdout.
"""

from __future__ import annotations

import json

import pytest

from kbtest.golden import Golden
from kbtest.runner import KB, Result

ADAPTERS = {
    "claude/session-start": {},
    "claude/session-prompt": {"prompt": "A prompt"},
    "claude/session-stop": {"last_assistant_message": "A reply"},
    "claude/session-end": {"reason": "user_quit"},
    "codex/session-start": {},
    "codex/session-prompt": {"prompt": "A prompt"},
    "codex/session-stop": {"last_assistant_message": "A reply"},
    "codex/session-end": {},
}

INPUTS = ["payload", "empty-stdin", "observe-off"]


def _protocol(kb: KB, adapter: str, result: Result) -> str:
    """Stdout reduced to what the host reads from it."""
    if adapter.startswith("codex/"):
        data = json.loads(result.out)  # Codex requires one JSON object.
        context = data.get("hookSpecificOutput", {}).get("additionalContext")
        if context is not None:
            data["hookSpecificOutput"]["additionalContext"] = kb.context_facts(context)
        return json.dumps(data, indent=2, sort_keys=True) + "\n"
    if adapter == "claude/session-start":
        return kb.context_facts(result.out) if result.out else "empty\n"
    # Claude reads nothing from these hooks, so what they print is not contract
    # (A-040); Python prints nothing.
    return "not read\n"


def _params() -> list[object]:
    params = []
    for adapter in sorted(ADAPTERS):
        for given in INPUTS:
            marks = []
            if (
                adapter.startswith("claude/")
                and adapter != "claude/session-start"
                and given == "empty-stdin"
            ):
                marks.append(pytest.mark.null_ok("a Claude hook without input exits 0 silently"))
            params.append(pytest.param(adapter, given, marks=marks, id=f"{adapter}-{given}"))
    return params


TRANSCRIPT = [("user", "Q1"), ("assistant", "A1"), ("user", "Q2")]


@pytest.mark.parametrize(("adapter", "given"), _params())
def test_hook_protocol(kb: KB, golden: Golden, adapter: str, given: str) -> None:
    session_id = kb.session_id()
    env: dict[str, str | None] = {"KNOWLEDGE_OBSERVE": "1"}
    if given == "observe-off":
        env["KNOWLEDGE_OBSERVE"] = "0"
    buffer = kb.layout.sessions / f"session-{session_id}.jsonl"
    if adapter.endswith(("prompt", "stop", "end")) and given != "empty-stdin":
        kb.run("session-init", "--session-id", session_id, "--persist-initialization")
        if adapter.endswith("end") and buffer.exists():
            buffer.write_text(
                "".join(json.dumps({"role": r, "message": m}) + "\n" for r, m in TRANSCRIPT),
                encoding="utf-8",
            )
    stdin = (
        ""
        if given == "empty-stdin"
        else json.dumps({"session_id": session_id, **ADAPTERS[adapter]})
    )
    result = kb.run(f"adapters/{adapter}", stdin=stdin, env=env)
    golden.contract("result", f"exit {result.returncode}\n")
    golden.contract("protocol", _protocol(kb, adapter, result))
    golden.contract(
        "buffer", kb.norm(buffer.read_text(encoding="utf-8")) if buffer.exists() else "absent\n"
    )
    observations = len(list((kb.layout.content / "observations" / "pending").glob("*.md")))
    golden.contract("observations", f"{observations}\n")
    golden.check("stderr", kb.norm_err(result.err).replace(kb.session_prefix, "<SESSION>-"))

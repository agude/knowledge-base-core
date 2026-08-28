#!/usr/bin/env bats

# Adapter tests exercise host protocol translation while the session core
# tests keep the durable behavior client-neutral.

load test_helper

setup() {
    setup_content_dir
    export SESSION_DIR="$(mktemp -d)"
    chmod 700 "$SESSION_DIR"
    export SESSION_ID="codex-test-$$"
}

teardown() {
    teardown_content_dir
    rm -rf "$SESSION_DIR"
}

@test "Codex SessionStart returns protocol JSON and initializes capture" {
    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | KNOWLEDGE_OBSERVE=1 "$SCRIPTS/adapters/codex/session-start"'
    [[ "$status" -eq 0 ]]
    run jq -e '.hookSpecificOutput.additionalContext' <<< "$output"
    [[ "$status" -eq 0 ]]
    [[ -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
}

@test "Codex adapters capture and flush a multi-turn transcript" {
    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | KNOWLEDGE_OBSERVE=1 "$SCRIPTS/adapters/codex/session-start"'
    [[ "$status" -eq 0 ]]

    KNOWLEDGE_OBSERVE=1 bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"First\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    KNOWLEDGE_OBSERVE=1 bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Answer\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null
    KNOWLEDGE_OBSERVE=1 bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"Second\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    KNOWLEDGE_OBSERVE=1 bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Reply\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null

    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | KNOWLEDGE_OBSERVE=1 "$SCRIPTS/adapters/codex/session-end"'
    [[ "$status" -eq 0 ]]
    for _ in 1 2 3 4 5; do
        [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]] && break
        sleep 1
    done
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
}

@test "portable instruction file is the canonical source with Claude alias" {
    [[ -f "$BATS_TEST_DIRNAME/../AGENTS.md" ]]
    [[ -L "$BATS_TEST_DIRNAME/../CLAUDE.md" ]]
    [[ "$(readlink "$BATS_TEST_DIRNAME/../CLAUDE.md")" == "AGENTS.md" ]]
}

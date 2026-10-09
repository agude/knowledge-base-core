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

create_append_stub() {
    local fake_kb="$TEST_CONTENT_DIR/fake-kb"
    mkdir -p "$fake_kb/scripts"
    cat > "$fake_kb/scripts/session-append" <<'EOF'
#!/usr/bin/env bash
set -eu

count=0
if [[ -f "$APPEND_CALLS_FILE" ]]; then
    count="$(<"$APPEND_CALLS_FILE")"
fi
count=$((count + 1))
printf '%s\n' "$count" > "$APPEND_CALLS_FILE"

if [[ "${APPEND_MODE:-}" == before ]]; then
    exit 75
fi

printf '%s\n' "$APPEND_PAYLOAD" >> "$APPEND_TARGET_FILE"
if [[ "${APPEND_MODE:-}" == after && "$count" == 1 ]]; then
    exit 75
fi
EOF
    chmod 700 "$fake_kb/scripts/session-append"
    export KNOWLEDGE_BASE="$fake_kb"
    export APPEND_CALLS_FILE="$TEST_CONTENT_DIR/append.calls"
}

run_claude_prompt() {
    printf '%s\n' "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"$APPEND_PAYLOAD\"}" |
        "$SCRIPTS/adapters/claude/session-prompt"
}

run_claude_stop() {
    printf '%s\n' "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"$APPEND_PAYLOAD\"}" |
        "$SCRIPTS/adapters/claude/session-stop"
}

run_codex_prompt() {
    printf '%s\n' "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"$APPEND_PAYLOAD\"}" |
        "$SCRIPTS/adapters/codex/session-prompt"
}

run_codex_stop() {
    printf '%s\n' "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"$APPEND_PAYLOAD\"}" |
        "$SCRIPTS/adapters/codex/session-stop"
}

@test "Claude prompt and stop report enabled buffer creation failures" {
    local blocked_directory="$SESSION_DIR/blocked" event
    printf 'retain this file\n' > "$blocked_directory"
    export KNOWLEDGE_OBSERVE=1

    for event in prompt stop; do
        run env SESSION_DIR="$blocked_directory" bash -c '
            printf "%s\n" "{\"session_id\":\"probe\",\"prompt\":\"durable evidence\",\"last_assistant_message\":\"durable evidence\"}" |
                "$1"
        ' _ "$SCRIPTS/adapters/claude/session-$event"
        [[ "$status" -ne 0 ]]
        [[ -n "$output" ]]
        [[ "$(cat "$blocked_directory")" == 'retain this file' ]]
    done
}

@test "Codex prompt and stop retain protocol JSON on enabled buffer creation failures" {
    local blocked_directory="$SESSION_DIR/blocked" event
    local stdout_file="$TEST_CONTENT_DIR/adapter.stdout"
    local stderr_file="$TEST_CONTENT_DIR/adapter.stderr"
    printf 'retain this file\n' > "$blocked_directory"
    export KNOWLEDGE_OBSERVE=1

    for event in prompt stop; do
        run env SESSION_DIR="$blocked_directory" bash -c '
            printf "%s\n" "{\"session_id\":\"probe\",\"prompt\":\"durable evidence\",\"last_assistant_message\":\"durable evidence\"}" |
                "$1" > "$2" 2> "$3"
        ' _ "$SCRIPTS/adapters/codex/session-$event" "$stdout_file" "$stderr_file"
        [[ "$status" -ne 0 ]]
        [[ "$(cat "$stdout_file")" == '{}' ]]
        [[ -s "$stderr_file" ]]
        [[ "$(cat "$blocked_directory")" == 'retain this file' ]]
    done
}

@test "Claude retries an append that fails before persistence" {
    local target="$SESSION_DIR/claude-before.jsonl"
    touch "$target"
    export KNOWLEDGE_SESSION_FILE="$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Claude prompt" APPEND_MODE=before
    create_append_stub

    run run_claude_prompt
    [[ "$status" -ne 0 ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 2 ]]
    [[ ! -s "$target" ]]
}

@test "Claude preserves a duplicate after a post-persistence append failure" {
    local target="$SESSION_DIR/claude-after.jsonl"
    touch "$target"
    export KNOWLEDGE_SESSION_FILE="$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Claude prompt" APPEND_MODE=after
    create_append_stub

    run run_claude_prompt
    [[ "$status" -eq 0 ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 2 ]]
    [[ "$(wc -l < "$target")" -eq 2 ]]
}

@test "Codex retries an append that fails before persistence" {
    local target="$SESSION_DIR/codex-before.jsonl"
    touch "$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Codex prompt" APPEND_MODE=before
    create_append_stub

    run run_codex_prompt
    [[ "$status" -ne 0 ]]
    [[ "$output" == "{}" ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 2 ]]
    [[ ! -s "$target" ]]
}

@test "Codex preserves a duplicate after a post-persistence append failure" {
    local target="$SESSION_DIR/codex-after.jsonl"
    touch "$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Codex prompt" APPEND_MODE=after
    create_append_stub

    run run_codex_prompt
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 2 ]]
    [[ "$(wc -l < "$target")" -eq 2 ]]
}

@test "repeated Claude hook delivery is retained as a duplicate record" {
    local target="$SESSION_DIR/claude-duplicate.jsonl"
    touch "$target"
    export KNOWLEDGE_SESSION_FILE="$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Repeated prompt" APPEND_MODE=success
    create_append_stub

    run run_claude_prompt
    [[ "$status" -eq 0 ]]
    run run_claude_prompt
    [[ "$status" -eq 0 ]]
    run run_claude_stop
    [[ "$status" -eq 0 ]]
    run run_claude_stop
    [[ "$status" -eq 0 ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 4 ]]
    [[ "$(wc -l < "$target")" -eq 4 ]]
}

@test "repeated Codex hook delivery is retained as a duplicate record" {
    local target="$SESSION_DIR/codex-duplicate.jsonl"
    touch "$target"
    export APPEND_TARGET_FILE="$target" APPEND_PAYLOAD="Repeated prompt" APPEND_MODE=success
    create_append_stub

    run run_codex_prompt
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    run run_codex_prompt
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    run run_codex_stop
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    run run_codex_stop
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    [[ "$(<"$APPEND_CALLS_FILE")" == 4 ]]
    [[ "$(wc -l < "$target")" -eq 4 ]]
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

@test "Codex capture is enabled when KNOWLEDGE_OBSERVE is unset" {
    unset KNOWLEDGE_OBSERVE
    export KNOWLEDGE_MIN_MESSAGES=0

    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"'
    [[ "$status" -eq 0 ]]
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"First\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Answer\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"' >/dev/null

    for _ in 1 2 3 4 5; do
        [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]] && break
        sleep 1
    done
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
}

@test "Codex capture stays off when SessionStart never ran" {
    unset KNOWLEDGE_OBSERVE
    export KNOWLEDGE_MIN_MESSAGES=0

    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"First\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Answer\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"' >/dev/null

    [[ ! -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 0 ]]
}

@test "Codex capture survives a swept buffer when observation is unset" {
    unset KNOWLEDGE_OBSERVE
    export KNOWLEDGE_MIN_MESSAGES=0

    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"' >/dev/null
    rm "$SESSION_DIR/session-${SESSION_ID}.jsonl"

    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"After sweep\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    [[ -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Recovered\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"' >/dev/null

    for _ in 1 2 3 4 5; do
        [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]] && break
        sleep 1
    done
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
}

@test "Codex SessionEnd clears a marker after the orphan sweep removes its buffer" {
    unset KNOWLEDGE_OBSERVE
    export OLD_SESSION_ID="${SESSION_ID}-old"

    bash -c 'printf "%s\n" "{\"session_id\":\"$OLD_SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"' >/dev/null
    old_file="$SESSION_DIR/session-${OLD_SESSION_ID}.jsonl"
    old_marker="$SESSION_DIR/session-${OLD_SESSION_ID}.initialized"
    touch -d '2 hours ago' "$old_file" 2>/dev/null || touch -A -020000 "$old_file"

    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"' >/dev/null
    [[ ! -e "$old_file" ]]
    [[ -e "$old_marker" ]]

    bash -c 'printf "%s\n" "{\"session_id\":\"$OLD_SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"' >/dev/null
    for _ in 1 2 3 4 5; do
        [[ ! -e "$old_marker" ]] && break
        sleep 1
    done
    [[ ! -e "$old_marker" ]]
}

@test "Codex SessionEnd reports a failed flush and recovers on a later lifecycle" {
    export KNOWLEDGE_OBSERVE=1 KNOWLEDGE_MIN_MESSAGES=0

    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"'
    [[ "$status" -eq 0 ]]
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"Question\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"Answer\"}" | "$SCRIPTS/adapters/codex/session-stop"' >/dev/null

    chmod u-w "$TEST_CONTENT_DIR/observations/pending"
    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"'
    chmod u+w "$TEST_CONTENT_DIR/observations/pending"

    [[ "$status" -ne 0 ]]
    [[ "$output" == "{}" ]]
    [[ -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 0 ]]

    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"'
    [[ "$status" -eq 0 ]]
    [[ "$output" == "{}" ]]
    [[ ! -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
}

# Codex allows SessionEnd at most three seconds and runs it synchronously.
# A held commit lock must fail inside that budget and leave the buffer for
# a later sweep, not stall until Codex kills the hook.
@test "Codex SessionEnd fails inside its time budget when the lock is held" {
    export KNOWLEDGE_OBSERVE=1 KNOWLEDGE_MIN_MESSAGES=0

    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-start"' >/dev/null
    bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"Question\"}" | "$SCRIPTS/adapters/codex/session-prompt"' >/dev/null
    mkdir "$TEST_CONTENT_DIR/.observe.lock"
    echo $$ > "$TEST_CONTENT_DIR/.observe.lock/pid"

    local start=$SECONDS
    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"'
    (( SECONDS - start < 3 ))
    [[ "$status" -ne 0 ]]
    [[ "$output" == "{}" ]]
    [[ -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    [[ -z "$(find "$TEST_CONTENT_DIR/observations/pending" -type f)" ]]

    rm -rf "$TEST_CONTENT_DIR/.observe.lock"
    run bash -c 'printf "%s\n" "{\"session_id\":\"$SESSION_ID\"}" | "$SCRIPTS/adapters/codex/session-end"'
    [[ "$status" -eq 0 ]]
    [[ ! -f "$SESSION_DIR/session-${SESSION_ID}.jsonl" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
}

@test "portable instruction file is the canonical source" {
    [[ -f "$BATS_TEST_DIRNAME/../AGENTS.md" ]]
    [[ ! -e "$BATS_TEST_DIRNAME/../CLAUDE.md" ]]
}

@test "enabled adapters report message allocation and extraction failures" {
    create_append_stub
    local fake_bin="$TEST_CONTENT_DIR/adapter-fail-bin"
    local real_jq client event mode stdout_file
    real_jq="$(command -v jq)"
    mkdir -p "$fake_bin"
    cat > "$fake_bin/mktemp" <<'STUB'
#!/usr/bin/env bash
if [[ "$ADAPTER_FAILURE_MODE" == allocation ]]; then
    echo 'injected message allocation failure' >&2
    exit 23
fi
exec "$ADAPTER_REAL_MKTEMP" "$@"
STUB
    cat > "$fake_bin/jq" <<'STUB'
#!/usr/bin/env bash
if [[ "$ADAPTER_FAILURE_MODE" == extraction && "$1" == -rj ]]; then
    printf 'partial message'
    echo 'injected message extraction failure' >&2
    exit 24
fi
exec "$ADAPTER_REAL_JQ" "$@"
STUB
    chmod 700 "$fake_bin/"*
    local real_mktemp
    real_mktemp="$(command -v mktemp)"
    for client in claude codex; do
        for event in prompt stop; do
            for mode in allocation extraction; do
                stdout_file="$TEST_CONTENT_DIR/$client-$event-$mode.stdout"
                run env PATH="$fake_bin:$PATH" KNOWLEDGE_OBSERVE=1 \
                    ADAPTER_FAILURE_MODE="$mode" ADAPTER_REAL_JQ="$real_jq" \
                    ADAPTER_REAL_MKTEMP="$real_mktemp" bash -c '
                    printf "%s\n" "{\"session_id\":\"probe\",\"prompt\":\"evidence\",\"last_assistant_message\":\"evidence\"}" |
                        "$1" > "$2"
                ' _ "$SCRIPTS/adapters/$client/session-$event" "$stdout_file"
                [[ "$status" -ne 0 ]]
                [[ "$output" == *"failure"* ]]
                [[ ! -e "$APPEND_CALLS_FILE" ]]
                if [[ "$client" == codex ]]; then
                    [[ "$(cat "$stdout_file")" == '{}' ]]
                else
                    [[ ! -s "$stdout_file" ]]
                fi
            done
        done
    done
}

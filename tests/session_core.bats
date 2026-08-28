#!/usr/bin/env bats

# Tests for the core session API scripts (agent-agnostic).
#
# These scripts form the stable API that agent-specific shims call.
# They use CLI args (not JSON stdin) and output plain text to stdout.

load test_helper

setup() {
    setup_content_dir
    export SESSION_DIR="$(mktemp -d)"
    chmod 700 "$SESSION_DIR"
}

teardown() {
    teardown_content_dir
    [[ -d "$SESSION_DIR" ]] && rm -rf "$SESSION_DIR"
}

# ── session-context ──────────────────────────────────────────────────

@test "session-context outputs non-empty text" {
    run "$SCRIPTS/session-context"
    [[ "$status" -eq 0 ]]
    [[ -n "$output" ]]
}

@test "session-context includes topic areas heading" {
    run "$SCRIPTS/session-context"
    [[ "$output" == *"## Topic areas (auto-generated)"* ]]
}

@test "session-context includes state line" {
    run "$SCRIPTS/session-context"
    [[ "$output" == *"State:"* ]]
}

@test "session-context includes articles from knowledge/" {
    create_test_article "infra/networking.md" "# Networking

## DNS

Content."
    run "$SCRIPTS/session-context"
    [[ "$output" == *"knowledge/infra/"* ]]
}

@test "session-context includes pending observation count" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    run "$SCRIPTS/session-context"
    [[ "$output" == *"1 pending"* ]]
}

@test "session-context includes content AGENTS.md when present" {
    echo "# Project Rules" > "$TEST_CONTENT_DIR/AGENTS.md"
    run "$SCRIPTS/session-context"
    [[ "$output" == *"Project Rules"* ]]
}

# ── session-init ─────────────────────────────────────────────────────

@test "session-init creates buffer file and prints path" {
    run "$SCRIPTS/session-init" --session-id "test-1"
    [[ "$status" -eq 0 ]]
    [[ -n "$output" ]]
    [[ -f "$output" ]]
}

@test "session-init buffer has mode 600" {
    run "$SCRIPTS/session-init" --session-id "test-mode"
    local path="$output"
    run stat -c '%a' "$path"
    [[ "$output" == "600" ]]
}

@test "session-init creates session dir with mode 700" {
    local newdir="$SESSION_DIR/sub"
    SESSION_DIR="$newdir" run "$SCRIPTS/session-init" --session-id "test-dir"
    run stat -c '%a' "$newdir"
    [[ "$output" == "700" ]]
}

@test "session-init is idempotent" {
    run "$SCRIPTS/session-init" --session-id "test-idem"
    local path1="$output"
    run "$SCRIPTS/session-init" --session-id "test-idem"
    local path2="$output"
    [[ "$path1" == "$path2" ]]
    [[ -f "$path1" ]]
}

@test "session-init with no --session-id fails" {
    run "$SCRIPTS/session-init"
    [[ "$status" -ne 0 ]]
}

@test "session-init rejects a path traversal session ID" {
    run "$SCRIPTS/session-init" --session-id "../escape"
    [[ "$status" -ne 0 ]]
}

@test "session-file resolves a session without creating it" {
    run "$SCRIPTS/session-file" --session-id "resolver-1"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "$SESSION_DIR/session-resolver-1.jsonl" ]]
    [[ ! -e "$output" ]]
}

@test "session-file --create creates a private buffer" {
    run "$SCRIPTS/session-file" --session-id "resolver-2" --create
    [[ "$status" -eq 0 ]]
    [[ -f "$output" ]]
    run stat -c '%a' "$output"
    [[ "$output" == "600" ]]
}

@test "session-init tightens a pre-existing world-readable directory" {
    local dir="$SESSION_DIR/wide"
    mkdir -p -m 777 "$dir"
    SESSION_DIR="$dir" run "$SCRIPTS/session-init" --session-id "test-tight"
    [[ "$status" -eq 0 ]]
    run stat -c '%a' "$dir"
    [[ "$output" == "700" ]]
}

# ── session-append ───────────────────────────────────────────────────

@test "session-append adds a user message" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --role user --message "Hello world"
    [[ "$status" -eq 0 ]]
    run cat "$file"
    [[ "$output" == *'"role":"user"'* ]]
    [[ "$output" == *'"message":"Hello world"'* ]]
}

@test "session-append adds an assistant message" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --role assistant --message "Hi there"
    [[ "$status" -eq 0 ]]
    run cat "$file"
    [[ "$output" == *'"role":"assistant"'* ]]
    [[ "$output" == *'"message":"Hi there"'* ]]
}

@test "session-append resolves a session ID through the shared API" {
    run "$SCRIPTS/session-init" --session-id "append-id"
    run "$SCRIPTS/session-append" --session-id "append-id" \
        --role user --message "Resolved message"
    [[ "$status" -eq 0 ]]
    run cat "$SESSION_DIR/session-append-id.jsonl"
    [[ "$output" == *"Resolved message"* ]]
}

@test "session-append accumulates multiple messages" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    "$SCRIPTS/session-append" --file "$file" --role user --message "Q1"
    "$SCRIPTS/session-append" --file "$file" --role assistant --message "A1"
    "$SCRIPTS/session-append" --file "$file" --role user --message "Q2"
    local count
    count=$(wc -l < "$file")
    [[ "$count" -eq 3 ]]
}

@test "session-append to nonexistent file exits 0 (no-op)" {
    run "$SCRIPTS/session-append" --file "/nonexistent/buffer.jsonl" --role user --message "Hi"
    [[ "$status" -eq 0 ]]
}

@test "session-append with missing --role fails" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --message "Hi"
    [[ "$status" -ne 0 ]]
}

@test "session-append with missing --message is a no-op" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --role user
    [[ "$status" -eq 0 ]]
    [[ ! -s "$file" ]]
}

@test "session-append with invalid role fails" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --role system --message "Hi"
    [[ "$status" -ne 0 ]]
}

@test "session-append skips empty messages" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-append" --file "$file" --role user --message ""
    [[ "$status" -eq 0 ]]
    # File should still be empty
    [[ ! -s "$file" ]]
}

# ── session-flush (already exists, verify contract) ──────────────────

@test "session-flush with >=3 messages creates observation" {
    local file="$SESSION_DIR/buffer.jsonl"
    echo '{"role":"user","message":"Q1"}' > "$file"
    echo '{"role":"assistant","message":"A1"}' >> "$file"
    echo '{"role":"user","message":"Q2"}' >> "$file"
    echo '{"role":"assistant","message":"A2"}' >> "$file"

    run "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 1 ]]
}

@test "session-flush with <3 messages drops the file" {
    local file="$SESSION_DIR/buffer.jsonl"
    echo '{"role":"user","message":"Q1"}' > "$file"
    echo '{"role":"assistant","message":"A1"}' >> "$file"

    run "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 0 ]]
}

@test "session-flush with empty file removes it" {
    local file="$SESSION_DIR/buffer.jsonl"
    touch "$file"
    run "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
}

@test "session-flush with nonexistent file exits 0" {
    run "$SCRIPTS/session-flush" "/nonexistent/buffer.jsonl"
    [[ "$status" -eq 0 ]]
}

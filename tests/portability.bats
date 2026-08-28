#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "portability lint accepts the shared surface" {
    run "$SCRIPTS/portability-lint"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Portable surface is clean."* ]]
}

@test "portability lint checks known adapters" {
    run "$SCRIPTS/portability-lint" --client claude
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/portability-lint" --client codex
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/portability-lint" --client opencode
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/portability-lint" --client pi
    [[ "$status" -eq 0 ]]
}

@test "portability lint rejects an unknown adapter" {
    run "$SCRIPTS/portability-lint" --client future-harness
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"no adapter"* ]]
}

@test "OpenCode adapter maps lifecycle events to the core API" {
    local adapter="$SCRIPTS/adapters/opencode/knowledge.ts"
    [[ -f "$adapter" ]]
    grep -q 'session.created' "$adapter"
    grep -q 'chat.message' "$adapter"
    grep -q 'session-append' "$adapter"
    grep -q 'session-flush' "$adapter"
}

@test "Pi adapter maps lifecycle events to the core API" {
    local adapter="$SCRIPTS/adapters/pi/knowledge.ts"
    [[ -f "$adapter" ]]
    grep -q 'session_start' "$adapter"
    grep -q 'message_end' "$adapter"
    grep -q 'session-append' "$adapter"
    grep -q 'session-flush' "$adapter"
}

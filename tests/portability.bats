#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "portability lint accepts the shared surface" {
    run "$SCRIPTS/portability-lint"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Portable surface is clean."* ]]
}

@test "portability lint checks supported adapters" {
    run "$SCRIPTS/portability-lint" --client claude
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/portability-lint" --client codex
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/portability-lint" --client pi
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"scripts/adapters/pi/knowledge.ts"* ]]
    [[ "$output" == *"scripts/adapters/pi/package.json"* ]]
}

@test "portability lint rejects an unknown adapter" {
    run "$SCRIPTS/portability-lint" --client future-harness
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"no adapter"* ]]
}

@test "portability lint avoids GNU-only path utilities" {
    run grep -E 'readlink -f|sort -z|find .* -maxdepth' "$SCRIPTS/portability-lint"
    [[ "$status" -ne 0 ]]
}

@test "supported host adapters are present for lifecycle tests" {
    [[ -x "$SCRIPTS/adapters/claude/session-start" ]]
    [[ -x "$SCRIPTS/adapters/codex/session-start" ]]
    [[ -f "$SCRIPTS/adapters/pi/knowledge.ts" ]]
    [[ -f "$SCRIPTS/adapters/pi/package.json" ]]
    [[ -f "$SCRIPTS/adapters/pi/package-lock.json" ]]
}

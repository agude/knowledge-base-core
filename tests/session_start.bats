#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "session-start outputs CLAUDE.md content" {
    run bash -c 'echo "{\"session_id\":\"test-1\"}" | KNOWLEDGE_OBSERVE=0 "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Knowledge Base"* ]]
}

@test "session-start includes auto-generated topics heading" {
    run bash -c 'echo "{\"session_id\":\"test-2\"}" | KNOWLEDGE_OBSERVE=0 "$SCRIPTS/session-start"'
    [[ "$output" == *"## Topics (auto-generated)"* ]]
}

@test "session-start includes topic list from toc" {
    create_test_article "networking.md" "# Networking

## DNS

Content."
    run bash -c 'echo "{\"session_id\":\"test-3\"}" | KNOWLEDGE_OBSERVE=0 "$SCRIPTS/session-start"'
    [[ "$output" == *"Networking"* ]]
}

@test "session-start includes content CLAUDE.md when present" {
    echo "# Project Rules" > "$TEST_CONTENT_DIR/CLAUDE.md"
    run bash -c 'echo "{\"session_id\":\"test-4\"}" | KNOWLEDGE_OBSERVE=0 "$SCRIPTS/session-start"'
    [[ "$output" == *"Project Rules"* ]]
}

@test "session-start sets KNOWLEDGE_OBSERVE=1 by default" {
    local env_file="$TEST_CONTENT_DIR/env_test"
    touch "$env_file"
    run bash -c 'echo "{\"session_id\":\"test-5\"}" | CLAUDE_ENV_FILE='"$env_file"' "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    run cat "$env_file"
    [[ "$output" == *"KNOWLEDGE_OBSERVE=1"* ]]
}

@test "session-start respects KNOWLEDGE_OBSERVE=0" {
    local env_file="$TEST_CONTENT_DIR/env_test"
    touch "$env_file"
    run bash -c 'echo "{\"session_id\":\"test-6\"}" | KNOWLEDGE_OBSERVE=0 CLAUDE_ENV_FILE='"$env_file"' "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    run cat "$env_file"
    [[ "$output" == *"KNOWLEDGE_OBSERVE=0"* ]]
    # Should NOT contain OBSERVE=1
    [[ "$output" != *"KNOWLEDGE_OBSERVE=1"* ]]
}

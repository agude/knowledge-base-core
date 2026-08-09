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

@test "session-start still injects context when jq is missing" {
    local stub="$TEST_CONTENT_DIR/bin"
    mkdir -p "$stub"
    for b in bash cat date find touch mkdir readlink dirname pwd sort awk sed grep wc tr; do
        ln -sf "$(command -v $b)" "$stub/$b" 2>/dev/null || true
    done
    create_test_article "networking.md" "# Networking

## DNS

Content."
    run bash -c 'echo "{\"session_id\":\"test-nojq\"}" | PATH='"$stub"' "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Networking"* ]]
    [[ "$output" == *"## Topics (auto-generated)"* ]]
}

@test "session-start creates the session directory mode 700" {
    local dir="$TEST_CONTENT_DIR/sessions"
    run bash -c 'echo "{\"session_id\":\"test-mode\"}" | SESSION_DIR='"$dir"' "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    run stat -c '%a' "$dir"
    [[ "$output" == "700" ]]
}

@test "session-start creates the buffer mode 600" {
    local dir="$TEST_CONTENT_DIR/sessions"
    run bash -c 'echo "{\"session_id\":\"test-fmode\"}" | SESSION_DIR='"$dir"' "$SCRIPTS/session-start"'
    run stat -c '%a' "$dir/session-test-fmode.jsonl"
    [[ "$output" == "600" ]]
}

@test "session-start tightens a pre-existing world-readable directory" {
    local dir="$TEST_CONTENT_DIR/sessions"
    mkdir -p -m 777 "$dir"
    run bash -c 'echo "{\"session_id\":\"test-tighten\"}" | SESSION_DIR='"$dir"' "$SCRIPTS/session-start"'
    run stat -c '%a' "$dir"
    [[ "$output" == "700" ]]
}

@test "session-start still injects context when the session dir is unwritable" {
    local blocked="$TEST_CONTENT_DIR/blocked"
    touch "$blocked"
    run bash -c 'echo "{\"session_id\":\"test-blocked\"}" | SESSION_DIR='"$blocked"' "$SCRIPTS/session-start"'
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Knowledge Base"* ]]
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

#!/usr/bin/env bats

# Integration tests for multi-turn session capture.
#
# These tests simulate the full hook sequence across multiple turns
# to verify that session files accumulate correctly and flush only
# at session end.

load test_helper

setup() {
    setup_content_dir
    export SESSION_DIR="$(mktemp -d)"
    export SESSION_ID="test-session-$$"
    export SESSION_FILE="$SESSION_DIR/session-${SESSION_ID}.jsonl"
}

teardown() {
    teardown_content_dir
    [[ -d "$SESSION_DIR" ]] && rm -rf "$SESSION_DIR"
}

# Helper to run session-prompt (UserPromptSubmit hook)
run_session_prompt() {
    local prompt="$1"
    echo "{\"session_id\":\"$SESSION_ID\",\"prompt\":\"$prompt\"}" | \
        KNOWLEDGE_OBSERVE=1 \
        "$SCRIPTS/adapters/claude/session-prompt"
}

# Helper to run session-stop (Stop hook)
run_session_stop() {
    local message="$1"
    echo "{\"session_id\":\"$SESSION_ID\",\"last_assistant_message\":\"$message\"}" | \
        KNOWLEDGE_OBSERVE=1 \
        "$SCRIPTS/adapters/claude/session-stop"
}

# Helper to run session-end (SessionEnd hook)
run_session_end() {
    echo "{\"session_id\":\"$SESSION_ID\",\"reason\":\"user_quit\"}" | \
        KNOWLEDGE_OBSERVE=1 \
        "$SCRIPTS/adapters/claude/session-end"
}

@test "session file persists after session-stop" {
    # Create session file (simulating session-start)
    touch "$SESSION_FILE"

    # Turn 1
    run_session_prompt "Hello"
    run_session_stop "Hi there"

    # Session file should still exist after stop
    [[ -f "$SESSION_FILE" ]]
}

@test "session file accumulates messages across turns" {
    touch "$SESSION_FILE"

    # Turn 1
    run_session_prompt "First question"
    run_session_stop "First answer"

    # Turn 2
    run_session_prompt "Second question"
    run_session_stop "Second answer"

    # Should have 4 messages
    local count
    count=$(wc -l < "$SESSION_FILE")
    [[ "$count" -eq 4 ]]
}

@test "multi-turn session creates observation with all messages" {
    touch "$SESSION_FILE"

    # Turn 1
    run_session_prompt "What is 2+2?"
    run_session_stop "4"

    # Turn 2
    run_session_prompt "And 3+3?"
    run_session_stop "6"

    # Flush via session-end
    run_session_end

    # Should have created an observation
    local obs_count
    obs_count=$(ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l)
    [[ "$obs_count" -eq 1 ]]

    # Observation should mention 4 messages
    local obs_file
    obs_file=$(ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md | head -1)
    grep -q "4 messages" "$obs_file"
}

@test "session-end drops a one-exchange transcript" {
    touch "$SESSION_FILE"
    run_session_prompt "What is 2+2?"
    run_session_stop "4"
    run_session_end

    [[ ! -f "$SESSION_FILE" ]]
    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 0 ]]
}

@test "KNOWLEDGE_MIN_MESSAGES=0 keeps a one-exchange transcript" {
    touch "$SESSION_FILE"
    run_session_prompt "What is 2+2?"
    run_session_stop "4"
    echo "{\"session_id\":\"$SESSION_ID\",\"reason\":\"user_quit\"}" | \
        KNOWLEDGE_OBSERVE=1 KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/adapters/claude/session-end"

    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 1 ]]
}

@test "session-end keeps a transcript at the threshold" {
    touch "$SESSION_FILE"
    run_session_prompt "First"
    run_session_stop "Answer"
    run_session_prompt "Second"
    run_session_end

    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 1 ]]
}

@test "session-end cleans up session file after flushing" {
    touch "$SESSION_FILE"
    run_session_prompt "Test"
    run_session_stop "Response"
    run_session_prompt "More"
    run_session_stop "Answer"
    run_session_end

    # Session file should be deleted after flush
    [[ ! -f "$SESSION_FILE" ]]
    run bash -c 'ls -1 "$TEST_CONTENT_DIR/observations/pending/"*.md 2>/dev/null | wc -l'
    [[ "$output" -eq 1 ]]
}

@test "session-stop recreates a swept buffer" {
    run run_session_stop "Response"
    [[ "$status" -eq 0 ]]
    [[ -f "$SESSION_FILE" ]]
    grep -q "Response" "$SESSION_FILE"
}

@test "session-prompt recreates a swept buffer" {
    run run_session_prompt "Hello"
    [[ "$status" -eq 0 ]]
    [[ -f "$SESSION_FILE" ]]
    grep -q "Hello" "$SESSION_FILE"
}

@test "capture continues after the orphan sweep removes the buffer" {
    touch "$SESSION_FILE"
    run_session_prompt "Before the sweep"
    run_session_stop "First answer"

    # An hour-idle buffer swept by another session starting up
    rm -f "$SESSION_FILE"

    run_session_prompt "After the sweep"
    run_session_stop "Second answer"

    [[ -f "$SESSION_FILE" ]]
    local count
    count=$(wc -l < "$SESSION_FILE")
    [[ "$count" -eq 2 ]]
    grep -q "After the sweep" "$SESSION_FILE"
}

@test "capture stays off when session-start never ran" {
    run bash -c 'echo "{\"session_id\":\"'"$SESSION_ID"'\",\"prompt\":\"Hi\"}" | "$SCRIPTS/adapters/claude/session-prompt"'
    [[ "$status" -eq 0 ]]
    [[ ! -f "$SESSION_FILE" ]]
}

@test "capture stays off when KNOWLEDGE_OBSERVE=0" {
    run bash -c 'echo "{\"session_id\":\"'"$SESSION_ID"'\",\"prompt\":\"Hi\"}" | KNOWLEDGE_OBSERVE=0 "$SCRIPTS/adapters/claude/session-prompt"'
    [[ "$status" -eq 0 ]]
    [[ ! -f "$SESSION_FILE" ]]
}

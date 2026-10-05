#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "doctor reports a passing retrieval and capture setup" {
    export SESSION_DIR="$TEST_CONTENT_DIR/sessions"
    mkdir -p "$SESSION_DIR"
    chmod 700 "$SESSION_DIR"

    run "$SCRIPTS/doctor" --require retrieval --require capture
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"PASS [retrieval]"* ]]
    [[ "$output" == *"sort supports -z NUL-delimited ordering"* ]]
    [[ "$output" == *"sort supports -V version ordering"* ]]
    [[ "$output" == *"find supports -maxdepth bounded scans"* ]]
    [[ "$output" == *"readlink supports -f entrypoint resolution"* ]]
    [[ "$output" == *"stdin capture and JSON round-trip smoke test passed"* ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -type f | wc -l)" -eq 0 ]]
}

@test "doctor checks the installed adapters when required" {
    fake_bin="$TEST_CONTENT_DIR/fake-node-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\n[ "$1" = "-p" ] || exit 1\nprintf "22.19.0\\n"\n' > "$fake_bin/node"
    chmod +x "$fake_bin/node"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require adapters
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"PASS [adapters] claude adapter is executable: session-start"* ]]
    [[ "$output" == *"PASS [adapters] Pi adapter file is present: package-lock.json"* ]]
    [[ "$output" == *"PASS [adapters] Node.js 22.19.0 supports the Pi adapter"* ]]
}

@test "doctor rejects Node.js 22.18 for the Pi adapter" {
    fake_bin="$TEST_CONTENT_DIR/fake-node-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\n[ "$1" = "-p" ] || exit 1\nprintf "22.18.0\\n"\n' > "$fake_bin/node"
    chmod +x "$fake_bin/node"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require adapters
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Node.js 22.18.0 is below the Pi requirement >=22.19.0"* ]]
}

@test "doctor accepts newer supported Node.js versions" {
    fake_bin="$TEST_CONTENT_DIR/fake-node-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\n[ "$1" = "-p" ] || exit 1\nprintf "23.0.0\\n"\n' > "$fake_bin/node"
    chmod +x "$fake_bin/node"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require adapters
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"PASS [adapters] Node.js 23.0.0 supports the Pi adapter"* ]]
}

@test "doctor rejects malformed Node.js version output" {
    fake_bin="$TEST_CONTENT_DIR/fake-node-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\n[ "$1" = "-p" ] || exit 1\nprintf "not-a-version\\n"\n' > "$fake_bin/node"
    chmod +x "$fake_bin/node"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require adapters
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Node.js not-a-version is below the Pi requirement >=22.19.0"* ]]
}

@test "doctor makes a requested missing content root fatal" {
    export KB_CONTENT_DIR="$TEST_CONTENT_DIR/missing"

    run "$SCRIPTS/doctor" --require curation
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"content root does not exist"* ]]
    [[ "$output" == *"required failure"* ]]
}

@test "doctor uses warnings for unrequested installation findings" {
    export SESSION_DIR="$TEST_CONTENT_DIR/sessions"
    mkdir -p "$SESSION_DIR"
    chmod 700 "$SESSION_DIR"

    run "$SCRIPTS/doctor" --require retrieval
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"WARN [curation]"* ]]
}

@test "doctor fails retrieval when date parsing returns no value" {
    fake_bin="$TEST_CONTENT_DIR/fake-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\nexit 1\n' > "$fake_bin/date"
    chmod +x "$fake_bin/date"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require retrieval
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"date cannot parse YYYY-MM-DD freshness dates"* ]]
}

@test "doctor fails retrieval when sort features are unavailable" {
    fake_bin="$TEST_CONTENT_DIR/fake-sort-bin"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\nexit 1\n' > "$fake_bin/sort"
    chmod +x "$fake_bin/sort"

    run env PATH="$fake_bin:$PATH" "$SCRIPTS/doctor" --require retrieval
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"sort does not support -z NUL-delimited ordering"* ]]
    [[ "$output" == *"sort does not support -V version ordering"* ]]
}

@test "doctor makes a missing retrieval JSON encoder dependency fatal" {
    local isolated_bin="$TEST_CONTENT_DIR/no-od-bin" command_name
    mkdir -p "$isolated_bin"
    for command_name in awk bash basename cat chmod cmp date dirname env find \
        git jq ln mkdir mktemp readlink rm sed sort stat touch tr wc; do
        ln -s "$(command -v "$command_name")" "$isolated_bin/$command_name"
    done
    export SESSION_DIR="$TEST_CONTENT_DIR/sessions"
    mkdir -p "$SESSION_DIR"
    chmod 700 "$SESSION_DIR"

    run env PATH="$isolated_bin" bash -c 'command -v od'
    [[ "$status" -ne 0 ]]
    [[ -z "$output" ]]

    run env PATH="$isolated_bin" "$SCRIPTS/doctor" --require retrieval
    [[ "$status" -ne 0 ]]
    [[ "$output" == *'FAIL [retrieval] missing command: od'* ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -type f | wc -l)" -eq 0 ]]
}

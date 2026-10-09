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

@test "session-init can persist initialization after a buffer sweep" {
    run "$SCRIPTS/session-init" --session-id "persistent" --persist-initialization
    local path="$output"
    rm "$path"

    run env -u KNOWLEDGE_OBSERVE "$SCRIPTS/session-append" \
        --session-id "persistent" --role user --message "Recovered"
    [[ "$status" -eq 0 ]]
    [[ -f "$path" ]]
    run cat "$path"
    [[ "$output" == *"Recovered"* ]]
}

@test "session-flush clears persisted initialization after normal completion" {
    run "$SCRIPTS/session-init" --session-id "clear-marker" --persist-initialization
    local path="$output"
    echo '{"role":"user","message":"Q1"}' > "$path"
    echo '{"role":"assistant","message":"A1"}' >> "$path"

    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$path"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$SESSION_DIR/session-clear-marker.initialized" ]]
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

@test "session-append reports buffer creation failure when capture is enabled" {
    local blocked_directory="$SESSION_DIR/blocked"
    printf 'retain this file\n' > "$blocked_directory"

    run env KNOWLEDGE_OBSERVE=1 SESSION_DIR="$blocked_directory" \
        "$SCRIPTS/session-append" --session-id allocation-failure \
        --role user --message "durable evidence"
    [[ "$status" -ne 0 ]]
    [[ -n "$output" ]]
    [[ "$(cat "$blocked_directory")" == 'retain this file' ]]
    [[ ! -e "$SESSION_DIR/session-allocation-failure.jsonl" ]]
}

@test "session-append skips an uninitialized session without creating a buffer" {
    run env -u KNOWLEDGE_OBSERVE -u KNOWLEDGE_SESSION_FILE \
        "$SCRIPTS/session-append" --session-id never-initialized \
        --role user --message "uncaptured message"
    [[ "$status" -eq 0 ]]
    [[ -z "$output" ]]
    [[ ! -e "$SESSION_DIR/session-never-initialized.jsonl" ]]
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

@test "session-append reads a large multiline message from stdin" {
    local file="$SESSION_DIR/stdin.jsonl"
    local message="$SESSION_DIR/message.txt"
    touch "$file"
    awk 'BEGIN { for (i = 1; i <= 160000; i++) printf "x"; printf "\n\n\n" }' > "$message"

    run bash -c 'cat "$1" | "$2" --file "$3" --role user --message -' \
        _ "$message" "$SCRIPTS/session-append" "$file"
    [[ "$status" -eq 0 ]]
    local decoded="$SESSION_DIR/decoded.txt"
    jq -j '.message' "$file" > "$decoded"
    cmp -s "$message" "$decoded"
}

@test "session-append rejects repeated message options" {
    local file="$SESSION_DIR/repeated-message.jsonl"
    touch "$file"

    run "$SCRIPTS/session-append" --file "$file" --role user \
        --message first --message second
    [[ "$status" -ne 0 ]]
    [[ ! -s "$file" ]]
}

@test "session-append rejects mixed stdin and argument message options" {
    local file="$SESSION_DIR/mixed-message.jsonl"
    touch "$file"

    run bash -c 'printf "%s" stdin | "$1" --file "$2" --role user \
        --message - --message argument' _ "$SCRIPTS/session-append" "$file"
    [[ "$status" -ne 0 ]]
    [[ ! -s "$file" ]]
}

@test "session-append fallback escapes control characters without jq" {
    local file="$SESSION_DIR/no-jq.jsonl"
    local fake_bin="$SESSION_DIR/bin"
    mkdir -p "$fake_bin"
    mkdir "$fake_bin/jq"
    for command in awk bash cat date dirname mktemp od pwd readlink rm; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    touch "$file"

    run /usr/bin/env PATH="$fake_bin" "$SCRIPTS/session-append" --file "$file" \
        --role user --message $'line 1\nline 2\t"\\\001'
    [[ "$status" -eq 0 ]]
    run jq -e '.message | contains("line 1\nline 2\t\"") and
        (explode | index(1) != null) and (explode | index(92) != null)' "$file"
    [[ "$status" -eq 0 ]]
}

@test "session-append fallback preserves Unicode and trailing newlines without jq" {
    local file="$SESSION_DIR/no-jq-round-trip.jsonl"
    local message="$SESSION_DIR/no-jq-message.txt"
    local decoded="$SESSION_DIR/no-jq-decoded.txt"
    local fake_bin="$SESSION_DIR/bin"
    mkdir -p "$fake_bin"
    for command in awk bash cat date dirname mktemp od pwd readlink rm; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    printf 'café\n雪\n\n' > "$message"
    touch "$file"

    run bash -c 'cat "$1" | /usr/bin/env PATH="$2" "$3" --file "$4" \
        --role user --message -' _ "$message" "$fake_bin" "$SCRIPTS/session-append" "$file"
    [[ "$status" -eq 0 ]]
    jq -j '.message' "$file" > "$decoded"
    cmp -s "$message" "$decoded"
}

@test "session-append does not append when od is missing" {
    local file="$SESSION_DIR/missing-od.jsonl"
    local fake_bin="$SESSION_DIR/bin"
    mkdir -p "$fake_bin"
    for command in awk bash cat date dirname mktemp pwd readlink rm; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    touch "$file"

    run /usr/bin/env PATH="$fake_bin" "$SCRIPTS/session-append" --file "$file" \
        --role user --message "missing encoder"
    [[ "$status" -ne 0 ]]
    [[ ! -s "$file" ]]
}

@test "session-append does not append partial output from a failing od" {
    local file="$SESSION_DIR/failing-od.jsonl"
    local fake_bin="$SESSION_DIR/bin"
    mkdir -p "$fake_bin"
    for command in awk bash cat date dirname mktemp pwd readlink rm; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    cat > "$fake_bin/od" <<'EOF'
#!/usr/bin/env bash
printf '20\n'
exit 1
EOF
    chmod 700 "$fake_bin/od"
    touch "$file"

    run /usr/bin/env PATH="$fake_bin" "$SCRIPTS/session-append" --file "$file" \
        --role user --message "failing encoder"
    [[ "$status" -ne 0 ]]
    [[ ! -s "$file" ]]
}

@test "session-append returns failure when the buffer cannot be written" {
    local file="$SESSION_DIR/read-only.jsonl"
    touch "$file"
    chmod u-w "$file"
    run "$SCRIPTS/session-append" --file "$file" --role user --message "blocked"
    chmod u+w "$file"
    [[ "$status" -ne 0 ]]
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

# Hooks run without KB_CONTENT_DIR, so the default content path must
# resolve. An empty buffer exits before writing, so the real default
# content directory is never touched.
@test "session-flush runs without KB_CONTENT_DIR" {
    local file="$SESSION_DIR/session-default-root.jsonl"
    touch "$file"
    run env -u KB_CONTENT_DIR "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
}

# The same hook environment must also persist a transcript. Copy the
# scripts into an isolated checkout so the default <root>/content path
# is a test repo rather than this checkout's own content directory.
@test "session-flush commits through the default content path" {
    local root="$BATS_TEST_TMPDIR/checkout"
    mkdir -p "$root/scripts"
    find "$SCRIPTS" -maxdepth 1 -type f -exec cp {} "$root/scripts/" \;
    mv "$TEST_CONTENT_DIR" "$root/content"
    TEST_CONTENT_DIR="$root/content"

    local file="$SESSION_DIR/session-default-commit.jsonl"
    echo '{"role":"user","message":"Q1"}' > "$file"
    echo '{"role":"assistant","message":"A1"}' >> "$file"
    echo '{"role":"user","message":"Q2"}' >> "$file"

    run env -u KB_CONTENT_DIR -u REPO_ROOT "$root/scripts/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]

    run git -C "$root/content" log -1 --format=%s
    [[ "$output" == "Observe: Session transcript (3 messages)" ]]
    run git -C "$root/content" status --porcelain
    [[ -z "$output" ]]
    run git -C "$root/content" ls-files 'observations/pending/*.md'
    [[ "$(printf '%s\n' "$output" | grep -c .)" -eq 1 ]]
}

@test "session-flush returns failure and keeps the buffer when observe fails" {
    local file="$SESSION_DIR/observe-failure.jsonl"
    echo '{"role":"user","message":"Q1"}' > "$file"
    echo '{"role":"assistant","message":"A1"}' >> "$file"
    echo '{"role":"user","message":"Q2"}' >> "$file"
    local pending_dir="$TEST_CONTENT_DIR/observations/pending"
    chmod u-w "$pending_dir"
    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    chmod u+w "$pending_dir"
    [[ "$status" -ne 0 ]]
    [[ -f "$file" ]]

    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
}

@test "session-flush keeps the buffer when jq is unavailable" {
    local file="$SESSION_DIR/missing-jq.jsonl"
    local original="$SESSION_DIR/missing-jq.original"
    local expected_transcript="$SESSION_DIR/missing-jq.transcript"
    local expected_body="$SESSION_DIR/missing-jq.expected-body"
    local actual_body="$SESSION_DIR/missing-jq.actual-body"
    local fake_bin="$SESSION_DIR/bin"
    local temp_dir="$SESSION_DIR/tmp"
    local original_path="$PATH"
    local observation second_marker
    mkdir -p "$fake_bin" "$temp_dir"
    for command in bash cat date dirname mktemp readlink rm; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    touch "$file"
    printf 'question line 1\nquestion line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    printf 'answer line 1\nanswer line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role assistant --message -
    printf 'follow-up\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    cp "$file" "$original"
    jq -r '"### " + .role + "\n\n" + .message + "\n\n"' \
        "$file" > "$expected_transcript"

    run env PATH="$fake_bin" TMPDIR="$temp_dir" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -ne 0 ]]
    cmp -s "$original" "$file"
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 0 ]]
    [[ ! -e "$temp_dir"/knowledge-transcript.* ]]

    run env PATH="$original_path" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$file" ]]
    observation="$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | head -n 1)"
    second_marker="$(grep -n '^---$' "$observation" | sed -n '2p' | cut -d: -f1)"
    tail -n "+$((second_marker + 1))" "$observation" > "$actual_body"
    {
        printf '\n'
        cat "$expected_transcript"
        printf '\n'
    } > "$expected_body"
    cmp -s "$expected_body" "$actual_body"
}

@test "session-flush retains the buffer when observe commit is rejected" {
    local file="$SESSION_DIR/rejected-commit.jsonl"
    local hook="$TEST_CONTENT_DIR/.git/hooks/pre-commit"
    mkdir -p "$(dirname "$hook")"
    cat > "$hook" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
    chmod 700 "$hook"
    printf '%s\n' \
        '{"role":"user","message":"Q1"}' \
        '{"role":"assistant","message":"A1"}' \
        '{"role":"user","message":"Q2"}' > "$file"

    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ "$status" -ne 0 ]]
    [[ -f "$file" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]

    rm -f "$hook"
    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 2 ]]
}

@test "session-flush keeps the buffer when interrupted during parsing" {
    local file="$SESSION_DIR/interrupted.jsonl"
    local original="$SESSION_DIR/interrupted.original"
    local expected_transcript="$SESSION_DIR/interrupted.transcript"
    local expected_body="$SESSION_DIR/interrupted.expected-body"
    local actual_body="$SESSION_DIR/interrupted.actual-body"
    local fake_bin="$SESSION_DIR/bin"
    local temp_dir="$SESSION_DIR/tmp"
    local jq_pid_file="$SESSION_DIR/jq.pid"
    local original_path="$PATH"
    local flush_pid flush_status jq_pid observation second_marker
    mkdir -p "$fake_bin" "$temp_dir"
    for command in bash cat date dirname mktemp readlink rm sleep; do
        ln -s "$(command -v "$command")" "$fake_bin/$command"
    done
    cat > "$fake_bin/jq" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$BASHPID" > "$JQ_PID_FILE"
printf 'partial transcript'
while :; do sleep 1; done
EOF
    chmod 700 "$fake_bin/jq"
    printf '%s\n' \
        '{"role":"user","message":"Q1"}' \
        '{"role":"assistant","message":"A1"}' \
        '{"role":"user","message":"Q2"}' > "$file"
    cp "$file" "$original"
    jq -r '"### " + .role + "\n\n" + .message + "\n\n"' \
        "$file" > "$expected_transcript"

    env PATH="$fake_bin" TMPDIR="$temp_dir" JQ_PID_FILE="$jq_pid_file" \
        KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file" \
        > "$SESSION_DIR/flush-output" 2>&1 &
    flush_pid=$!
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [[ -f "$jq_pid_file" ]] && break
        sleep 0.1
    done
    [[ -f "$jq_pid_file" ]]
    jq_pid="$(cat "$jq_pid_file")"
    kill -TERM "$flush_pid" 2>/dev/null || true
    kill -TERM "$jq_pid" 2>/dev/null || true
    if wait "$flush_pid"; then
        flush_status=0
    else
        flush_status=$?
    fi

    [[ "$flush_status" -eq 130 ]]
    cmp -s "$original" "$file"
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 0 ]]
    [[ ! -e "$temp_dir"/knowledge-transcript.* ]]

    run env PATH="$original_path" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$file" ]]
    observation="$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | head -n 1)"
    second_marker="$(grep -n '^---$' "$observation" | sed -n '2p' | cut -d: -f1)"
    tail -n "+$((second_marker + 1))" "$observation" > "$actual_body"
    {
        printf '\n'
        cat "$expected_transcript"
        printf '\n'
    } > "$expected_body"
    cmp -s "$expected_body" "$actual_body"
}

@test "session-flush keeps the buffer when interrupted during observation writing" {
    local file="$SESSION_DIR/interrupted-write.jsonl"
    local original="$SESSION_DIR/interrupted-write.original"
    local expected_transcript="$SESSION_DIR/interrupted-write.transcript"
    local expected_body="$SESSION_DIR/interrupted-write.expected-body"
    local actual_body="$SESSION_DIR/interrupted-write.actual-body"
    local fake_bin="$SESSION_DIR/write-bin"
    local cat_pid_file="$SESSION_DIR/cat.pid"
    local observe_pid_file="$SESSION_DIR/observe.pid"
    local original_path="$PATH"
    local flush_pid flush_status cat_pid observe_pid observation second_marker
    mkdir -p "$fake_bin"
    cat > "$fake_bin/cat" <<'EOF'
#!/usr/bin/env bash
if [[ -n "${CAT_STAGE_FILE:-}" && "$1" == *knowledge-observation.* ]]; then
    printf '%s\n' "$BASHPID" > "$CAT_STAGE_FILE"
    printf '%s\n' "$PPID" > "$OBSERVE_PID_FILE"
    printf 'partial observation'
    while :; do sleep 1; done
fi
exec /bin/cat "$@"
EOF
    chmod 700 "$fake_bin/cat"
    touch "$file"
    printf 'question line 1\nquestion line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    printf 'answer line 1\nanswer line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role assistant --message -
    printf 'follow-up\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    cp "$file" "$original"
    jq -r '"### " + .role + "\n\n" + .message + "\n\n"' \
        "$file" > "$expected_transcript"

    env PATH="$fake_bin:$original_path" CAT_STAGE_FILE="$cat_pid_file" \
        OBSERVE_PID_FILE="$observe_pid_file" \
        KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file" \
        > "$SESSION_DIR/flush-output" 2>&1 &
    flush_pid=$!
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [[ -f "$cat_pid_file" ]] && break
        sleep 0.1
    done
    [[ -f "$cat_pid_file" ]]
    cat_pid="$(cat "$cat_pid_file")"
    observe_pid="$(cat "$observe_pid_file")"
    kill -TERM "$flush_pid" 2>/dev/null || true
    kill -TERM "$observe_pid" 2>/dev/null || true
    kill -TERM "$cat_pid" 2>/dev/null || true
    if wait "$flush_pid"; then
        flush_status=0
    else
        flush_status=$?
    fi

    [[ "$flush_status" -ne 0 ]]
    cmp -s "$original" "$file"
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 0 ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '.observation.*' -type f | wc -l)" -eq 0 ]]

    run env PATH="$fake_bin:$original_path" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$file" ]]
    observation="$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | head -n 1)"
    second_marker="$(grep -n '^---$' "$observation" | sed -n '2p' | cut -d: -f1)"
    tail -n "+$((second_marker + 1))" "$observation" > "$actual_body"
    {
        printf '\n'
        cat "$expected_transcript"
        printf '\n'
    } > "$expected_body"
    cmp -s "$expected_body" "$actual_body"
}

@test "session-flush retains evidence when the observation body copy fails" {
    local file="$SESSION_DIR/failed-copy.jsonl"
    local original="$SESSION_DIR/failed-copy.original"
    local expected_transcript="$SESSION_DIR/failed-copy.transcript"
    local expected_body="$SESSION_DIR/failed-copy.expected-body"
    local actual_body="$SESSION_DIR/failed-copy.actual-body"
    local fake_bin="$SESSION_DIR/copy-bin"
    local copy_marker="$SESSION_DIR/copy-failed"
    local scratch_dir="$SESSION_DIR/copy-tmp"
    local real_cat observation second_marker
    real_cat="$(command -v cat)"
    mkdir -p "$fake_bin" "$scratch_dir"
    cat > "$fake_bin/cat" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == *knowledge-observation.* ]]; then
    printf 'body copy failed\n' > "$BODY_COPY_MARKER"
    printf 'partial evidence\n'
    exit 7
fi
exec "$BODY_COPY_CAT" "$@"
EOF
    chmod 700 "$fake_bin/cat"
    touch "$file"
    printf 'question line 1\nquestion line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    printf 'answer line 1\nanswer line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role assistant --message -
    cp "$file" "$original"
    jq -r '"### " + .role + "\n\n" + .message + "\n\n"' \
        "$file" > "$expected_transcript"

    run env PATH="$fake_bin:$PATH" TMPDIR="$scratch_dir" \
        BODY_COPY_MARKER="$copy_marker" BODY_COPY_CAT="$real_cat" \
        KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ -f "$copy_marker" ]]
    [[ "$status" -ne 0 ]]
    cmp -s "$original" "$file"
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -type f | wc -l)" -eq 0 ]]
    [[ "$(cd "$TEST_CONTENT_DIR" && git rev-list --count HEAD)" -eq 1 ]]
    [[ "$(find "$scratch_dir" -mindepth 1 | wc -l)" -eq 0 ]]

    run env TMPDIR="$scratch_dir" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$file" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
    [[ "$(cd "$TEST_CONTENT_DIR" && git rev-list --count HEAD)" -eq 2 ]]
    observation="$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | head -n 1)"
    second_marker="$(grep -n '^---$' "$observation" | sed -n '2p' | cut -d: -f1)"
    tail -n "+$((second_marker + 1))" "$observation" > "$actual_body"
    {
        printf '\n'
        cat "$expected_transcript"
        printf '\n'
    } > "$expected_body"
    cmp -s "$expected_body" "$actual_body"
}

@test "session-flush keeps the buffer when observation commit is interrupted" {
    local file="$SESSION_DIR/interrupted-commit.jsonl"
    local original="$SESSION_DIR/interrupted-commit.original"
    local expected_transcript="$SESSION_DIR/interrupted-commit.transcript"
    local expected_body="$SESSION_DIR/interrupted-commit.expected-body"
    local actual_body="$SESSION_DIR/interrupted-commit.actual-body"
    local hook="$TEST_CONTENT_DIR/.git/hooks/pre-commit"
    local hook_pid_file="$SESSION_DIR/hook.pid"
    local original_path="$PATH"
    local flush_pid flush_status hook_pid observation second_marker
    mkdir -p "$(dirname "$hook")"
    cat > "$hook" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$BASHPID" > "$HOOK_PID_FILE"
while :; do sleep 1; done
EOF
    chmod 700 "$hook"
    touch "$file"
    printf 'question line 1\nquestion line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    printf 'answer line 1\nanswer line 2\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role assistant --message -
    printf 'follow-up\n\n' |
        "$SCRIPTS/session-append" --file "$file" --role user --message -
    cp "$file" "$original"
    jq -r '"### " + .role + "\n\n" + .message + "\n\n"' \
        "$file" > "$expected_transcript"

    env PATH="$original_path" HOOK_PID_FILE="$hook_pid_file" \
        KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file" \
        > "$SESSION_DIR/flush-output" 2>&1 &
    flush_pid=$!
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [[ -f "$hook_pid_file" ]] && break
        sleep 0.1
    done
    [[ -f "$hook_pid_file" ]]
    hook_pid="$(cat "$hook_pid_file")"
    kill -TERM "$flush_pid" 2>/dev/null || true
    kill -TERM "$hook_pid" 2>/dev/null || true
    if wait "$flush_pid"; then
        flush_status=0
    else
        flush_status=$?
    fi

    [[ "$flush_status" -ne 0 ]]
    cmp -s "$original" "$file"
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 1 ]]
    [[ "$(cd "$TEST_CONTENT_DIR" && git rev-list --count HEAD)" -eq 1 ]]

    rm -f "$hook"
    run env PATH="$original_path" KNOWLEDGE_MIN_MESSAGES=0 \
        "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -e "$file" ]]
    [[ "$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | wc -l)" -eq 2 ]]
    [[ "$(cd "$TEST_CONTENT_DIR" && git rev-list --count HEAD)" -eq 2 ]]
    for observation in "$TEST_CONTENT_DIR"/observations/pending/*.md; do
        second_marker="$(grep -n '^---$' "$observation" | sed -n '2p' | cut -d: -f1)"
        tail -n "+$((second_marker + 1))" "$observation" > "$actual_body"
        {
            printf '\n'
            cat "$expected_transcript"
            printf '\n'
        } > "$expected_body"
        cmp -s "$expected_body" "$actual_body"
    done
}

@test "session-flush streams a large transcript and preserves its source" {
    local file="$SESSION_DIR/large.jsonl"
    local message="$SESSION_DIR/large-message.txt"
    local decoded="$SESSION_DIR/large-decoded.txt"
    local transcript="$SESSION_DIR/large-transcript.txt"
    local extracted="$SESSION_DIR/large-extracted.txt"
    awk 'BEGIN { for (i = 1; i <= 160000; i++) printf "large-evidence-"; printf "\n\n\n" }' > "$message"
    touch "$file"

    run bash -c 'cat "$1" | "$2" --file "$3" --role user --message -' \
        _ "$message" "$SCRIPTS/session-append" "$file"
    [[ "$status" -eq 0 ]]
    jq -j '.message' "$file" > "$decoded"
    cmp -s "$message" "$decoded"

    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ "$status" -eq 0 ]]
    [[ ! -f "$file" ]]
    local observation
    observation="$(find "$TEST_CONTENT_DIR/observations/pending" -name '*.md' -type f | head -n 1)"
    [[ -n "$observation" ]]
    awk 'BEGIN { frontmatter=0 } /^---$/ { frontmatter++; next } frontmatter >= 2 { print }' \
        "$observation" > "$transcript"
    prefix_bytes="$(printf '\n### user\n\n' | wc -c)"
    message_bytes="$(wc -c < "$message")"
    dd if="$transcript" of="$extracted" bs=1 skip="$prefix_bytes" \
        count="$message_bytes" 2>/dev/null
    cmp -s "$message" "$extracted"
}

@test "session-flush keeps malformed JSONL for recovery" {
    local file="$SESSION_DIR/malformed.jsonl"
    printf '%s\n' '{"role":"user","message":"valid"}' 'not json' > "$file"

    run env KNOWLEDGE_MIN_MESSAGES=0 "$SCRIPTS/session-flush" "$file"
    [[ "$status" -ne 0 ]]
    [[ -f "$file" ]]
    [[ "$(cat "$file")" == *'not json'* ]]
}

@test "session-flush validates malformed JSON before applying the message threshold" {
    local file="$SESSION_DIR/short-malformed.jsonl"
    printf '%s\n' '{"role":"user","message":"valid"}' 'not json' > "$file"

    run "$SCRIPTS/session-flush" "$file"
    [[ "$status" -ne 0 ]]
    [[ -f "$file" ]]
}

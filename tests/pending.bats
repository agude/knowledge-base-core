#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "pending reports no observations when the directory is missing" {
    rm -rf "$TEST_CONTENT_DIR/observations/pending"
    run "$SCRIPTS/pending"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "No pending observations." ]]
}

@test "pending --count reports 0 when the directory is missing" {
    rm -rf "$TEST_CONTENT_DIR/observations/pending"
    run "$SCRIPTS/pending" --count
    [[ "$status" -eq 0 ]]
    [[ "$output" == "0" ]]
}

@test "pending shows 0 when empty" {
    run "$SCRIPTS/pending" --count
    [[ "$output" == "0" ]]
}

@test "pending --count returns correct number" {
    create_test_observation "a.md" "First" "Body one"
    create_test_observation "b.md" "Second" "Body two"
    run "$SCRIPTS/pending" --count
    [[ "$output" == "2" ]]
}

@test "pending lists titles" {
    create_test_observation "a.md" "First observation" "Body"
    run "$SCRIPTS/pending"
    [[ "$output" == *"First observation"* ]]
    [[ "$output" == *"1 pending"* ]]
}

@test "pending --full shows file content" {
    create_test_observation "a.md" "Test" "Full body text here"
    run "$SCRIPTS/pending" --full
    [[ "$output" == *"Full body text here"* ]]
}

@test "pending --preview reports age, type counts, volume, and topic hints" {
    create_test_article "networking.md" "# Networking Setup"
    create_test_observation "a.md" "Networking failure" "The Networking Setup needs attention."
    cat > "$TEST_CONTENT_DIR/observations/pending/transcript.md" <<'EOF'
---
title: "Session transcript"
source: session-transcript
created: 2026-05-01T00:00:00Z
---

Transcript body.
EOF

    run env FRESHNESS_TODAY_EPOCH=1788566400 "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Batch-selectable items: 2"* ]]
    [[ "$output" == *"Oldest pending age: 146 day(s) (2026-04-12; a.md)"* ]]
    [[ "$output" == *"Observation items: 1 ("* ]]
    [[ "$output" == *"Transcript items: 1 ("* ]]
    [[ "$output" == *"Input volume: "*" bytes)"* ]]
    [[ "$output" == *"Topic hints (hints only; no LLM):"* ]]
    [[ "$output" == *"Networking Setup (1 pending item(s))"* ]]
    [[ "$output" == *"Metadata warnings: none"* ]]
}

@test "pending --preview is bounded for malformed and large inputs" {
    printf '%s\n' 'title: Broken metadata' 'created: not-a-date' > \
        "$TEST_CONTENT_DIR/observations/pending/broken.md"
    {
        echo '---'
        echo 'title: "Large transcript"'
        echo 'source: session-transcript'
        echo 'created: 2026-05-01T00:00:00Z'
        echo '---'
        awk 'BEGIN { for (i = 0; i < 20000; i++) printf "x" }'
        echo
    } > "$TEST_CONTENT_DIR/observations/pending/large.md"

    run env FRESHNESS_TODAY_EPOCH=1788566400 "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Batch-selectable items: 2"* ]]
    [[ "$output" == *"Oldest pending age: 127 day(s)"* ]]
    [[ "$output" == *"Transcript items: 1 ("* ]]
    [[ "$output" == *"Metadata warnings: 1 malformed file(s)"* ]]
    [[ "$output" == *"broken.md: malformed frontmatter"* ]]
    [[ "$output" != *"xxxxxxxxxx"* ]]
    [[ "${#output}" -lt 2000 ]]
}

@test "pending keeps recursive listing and bounds preview selection" {
    create_test_observation "top-level.md" "Top-level observation" "Body"
    mkdir -p "$TEST_CONTENT_DIR/observations/pending/nested"
    cat > "$TEST_CONTENT_DIR/observations/pending/nested/hidden.md" <<'EOF'
---
title: "Nested observation"
source: session
created: 2025-01-01T00:00:00Z
---

Body
EOF

    run "$SCRIPTS/pending" --count
    [[ "$status" -eq 0 ]]
    [[ "$output" == "2" ]]
    run "$SCRIPTS/pending" --full
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Nested observation"* ]]

    run "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Batch-selectable items: 1"* ]]
    [[ "$output" == *"Oldest pending age: 147 day(s) (2026-04-12; top-level.md)"* ]]
}

@test "pending --preview decodes escaped topic labels" {
    cat > "$TEST_CONTENT_DIR/observations/pending/escaped.md" <<'EOF'
---
title: "Escaped topic"
source: session
created: 2026-04-12T00:00:00Z
topic: "Team \"Core\""
---

Body
EOF

    run "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *'Team "Core" (1 pending item(s))'* ]]
    [[ "$output" != *'Team \\"Core\\"'* ]]
}

@test "pending --preview caps metadata and topic corpus work" {
    for ((i = 1; i <= 320; i++)); do
        create_test_article "topics/topic-$i.md" "# Topic $i"
    done
    {
        echo '---'
        echo 'title: "Large transcript"'
        echo 'source: session-transcript'
        echo 'created: 2026-05-01T00:00:00Z'
        echo '---'
        echo 'Topic'
        awk 'BEGIN { for (i = 0; i < 262144; i++) printf "x" }'
        echo
    } > "$TEST_CONTENT_DIR/observations/pending/large.md"

    run env FRESHNESS_TODAY_EPOCH=1788566400 "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Batch-selectable items: 1"* ]]
    [[ "$output" == *"Transcript items: 1 ("* ]]
    [[ "$output" == *"Topic hints (hints only; no LLM):"* ]]
    [[ "$output" == *"topic article metadata capped at 256 file(s)"* ]]
    [[ "$output" == *"Topic 1 (1 pending item(s))"* ]]
    [[ "$(grep -c 'pending item(s))' <<< "$output")" -eq 8 ]]
    [[ "$output" != *"xxxxxxxxxx"* ]]
    [[ "${#output}" -lt 2000 ]]
}

@test "pending --preview reports an empty queue without warnings" {
    run "$SCRIPTS/pending" --preview
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Batch-selectable items: 0"* ]]
    [[ "$output" == *"Oldest pending age: unknown"* ]]
    [[ "$output" == *"Topic hints (hints only; no LLM):"* ]]
    [[ "$output" == *"none available"* ]]
    [[ "$output" == *"Metadata warnings: none"* ]]
}

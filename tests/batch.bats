#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

commit_observations() {
    (cd "$TEST_CONTENT_DIR" && git add observations/ && git commit -q -m "add observations")
}

@test "batch selects only observations present at start" {
    create_test_observation a.md "A" "Body A"
    create_test_observation b.md "B" "Body B"
    commit_observations
    run "$SCRIPTS/batch" start
    [[ "$status" -eq 0 ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<< "$output")"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition ephemeral a.md --no-commit
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Archived"* ]]
    run "$SCRIPTS/batch" defer "$batch_id" b.md
    [[ "$status" -eq 0 ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/b.md" ]]
    create_test_observation c.md "C" "Body C"
    [[ -f "$TEST_CONTENT_DIR/observations/pending/c.md" ]]
    grep -q 'disposition: ephemeral' "$TEST_CONTENT_DIR/observations/archived/a.md"
}

@test "batch snapshots an explicit selected subset" {
    create_test_observation a.md "A" "Body A"
    create_test_observation b.md "B" "Body B"
    create_test_observation c.md "C" "Body C"
    commit_observations

    run "$SCRIPTS/batch" start --files c.md a.md
    [[ "$status" -eq 0 ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<< "$output")"
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"

    [[ "$(awk -F '\t' 'NR > 1 { print $1 }' "$batch_file" | tr '\n' ' ')" == "c.md a.md " ]]
    ! grep -q $'^b.md\t' "$batch_file"
    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"0 complete, 2 pending, 0 deferred"* ]]
}

@test "batch rejects invalid explicit selections" {
    create_test_observation a.md "A" "Body A"
    commit_observations

    run "$SCRIPTS/batch" start --files a.md missing.md
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"pending observation not found: missing.md"* ]]

    run "$SCRIPTS/batch" start --files a.md a.md
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"duplicate filename: a.md"* ]]

    run "$SCRIPTS/batch" start --files ../a.md
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"not a pending filename: ../a.md"* ]]
}

@test "batch detects changed input and supports deferral" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    printf '\nchanged\n' >> "$TEST_CONTENT_DIR/observations/pending/a.md"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Input changed since batch selection"* ]]
    run "$SCRIPTS/batch" defer "$batch_id" a.md
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"input changed since batch selection"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/a.md" ]]
    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"CHANGED"* ]]
}

@test "repeating batch completion does not overwrite archive" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    original="$(cat "$TEST_CONTENT_DIR/observations/archived/a.md")"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition ephemeral a.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$(cat "$TEST_CONTENT_DIR/observations/archived/a.md")" == "$original" ]]
}

@test "incorporated completion records its destination and batch status" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition incorporated \
        --destination knowledge/topic.md#Section a.md --no-commit
    [[ "$status" -eq 0 ]]
    grep -q 'disposition: incorporated' "$TEST_CONTENT_DIR/observations/archived/a.md"
    grep -q 'destination: knowledge/topic.md#Section' "$TEST_CONTENT_DIR/observations/archived/a.md"
    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 complete, 0 pending, 0 deferred"* ]]
}

@test "archive resumes after the observation move" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    # Model an interrupted archive: the observation moved and already carries
    # the durable disposition, but the manifest row was not updated.
    "$SCRIPTS/archive" --disposition duplicate a.md --no-commit
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    # Restore the pending state in the manifest while retaining the archive.
    awk -F '\t' -v OFS='\t' 'NR == 1 { print; next } { $3="pending"; $4=""; $5=""; print }' "$batch_file" > "$batch_file.tmp"
    mv "$batch_file.tmp" "$batch_file"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Recovered completed archive"* ]]
    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 complete"* ]]
}

@test "batch rejects the compatibility processed disposition" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition processed a.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"requires --disposition incorporated, duplicate, or ephemeral"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/a.md" ]]
}

@test "recovery rejects a non-member archive" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    create_test_observation outsider.md "Outsider" "Body outsider"
    "$SCRIPTS/archive" --disposition duplicate outsider.md --no-commit
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate outsider.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch"* ]]
    grep -q $'a.md\t.*\tpending' "$TEST_CONTENT_DIR/observations/batches/$batch_id"
}

@test "recovery rejects an archive with the wrong original hash" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$("$SCRIPTS/batch" start | sed -n 's/^Created batch: //p')"
    "$SCRIPTS/archive" --disposition duplicate a.md --no-commit
    sed -i 's/^original_sha256: .*/original_sha256: invalid/' "$TEST_CONTENT_DIR/observations/archived/a.md"
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"original hash does not match"* ]]
    grep -q $'a.md\t.*\tpending' "$TEST_CONTENT_DIR/observations/batches/$batch_id"
}

@test "batch status reports dispositions, destinations, and deferred work" {
    create_test_observation a.md "A" "Body A"
    create_test_observation b.md "B" "Body B"
    create_test_observation c.md "C" "Body C"
    commit_observations
    batch_id="$($SCRIPTS/batch start | sed -n 's/^Created batch: //p')"

    "$SCRIPTS/archive" --batch "$batch_id" --disposition incorporated \
        --destination knowledge/topic.md#Section a.md --no-commit
    "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate c.md --no-commit
    "$SCRIPTS/batch" defer "$batch_id" b.md

    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"2 complete, 0 pending, 1 deferred"* ]]
    [[ "$output" == *"Dispositions: incorporated=1, duplicate=1, ephemeral=0"* ]]
    [[ "$output" == *"knowledge/topic.md#Section (1 item(s))"* ]]
    [[ "$output" == *"Deferred work: 1 item(s)"* ]]
    [[ "$output" == *"- b.md"* ]]
}

@test "batch status rejects an invalid persisted disposition" {
    create_test_observation a.md "A" "Body A"
    commit_observations
    batch_id="$($SCRIPTS/batch start | sed -n 's/^Created batch: //p')"
    "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    awk -F '\t' -v OFS='\t' 'NR == 1 { print; next } { $3="complete"; $4="corrupt"; print }' \
        "$batch_file" > "$batch_file.tmp"
    mv "$batch_file.tmp" "$batch_file"

    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Dispositions not recognized: 1"* ]]
    [[ "$output" == *"Batch requires attention: 1 invalid item(s)."* ]]
}

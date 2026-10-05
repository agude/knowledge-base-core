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

@test "budgeted batch rejects changed and excluded inputs without losing evidence" {
    create_test_observation a.md "A" "Body A"
    create_test_observation z.md "Z" "A larger excluded body that does not fit"
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/a.md")"
    batch_id="$($SCRIPTS/batch start --max-bytes "$cap" | sed -n 's/^Created batch: //p')"
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    changed="$TEST_CONTENT_DIR/changed-a.md"

    printf '\nchanged after selection\n' >> "$TEST_CONTENT_DIR/observations/pending/a.md"
    cp "$TEST_CONTENT_DIR/observations/pending/a.md" "$changed"
    create_test_observation arrived.md "Arrived" "Body arrived"

    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Input changed since batch selection"* ]]
    cmp -s "$changed" "$TEST_CONTENT_DIR/observations/pending/a.md"
    [[ ! -e "$TEST_CONTENT_DIR/observations/archived/a.md" ]]
    grep -q $'^a.md\t.*\tpending' "$batch_file"

    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate z.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch: z.md"* ]]
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate arrived.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch: arrived.md"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/z.md" ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/arrived.md" ]]

    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"CHANGED: observations/pending/a.md"* ]]
    [[ "$output" == *"Input budget: $cap bytes"* ]]
    [[ "$output" == *"Selected bytes at creation: $cap"* ]]
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

@test "budgeted archive recovery preserves selection sizes and arrivals" {
    create_test_observation a.md "A" "Body A"
    create_test_observation z.md "Z" "Body Z"
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/a.md")"
    batch_id="$($SCRIPTS/batch start --max-bytes "$cap" | sed -n 's/^Created batch: //p')"
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    meta_file="$batch_file.meta"
    original_meta="$TEST_CONTENT_DIR/${batch_id}.meta.original"
    cp "$meta_file" "$original_meta"
    create_test_observation arrived.md "Arrived" "Body arrived"

    "$SCRIPTS/archive" --disposition duplicate a.md --no-commit
    awk -F '\t' -v OFS='\t' 'NR == 1 { print; next } { $3="pending"; $4=""; $5=""; print }' \
        "$batch_file" > "$batch_file.tmp"
    mv "$batch_file.tmp" "$batch_file"

    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate arrived.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch: arrived.md"* ]]
    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate a.md --no-commit
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Recovered completed archive"* ]]
    cmp -s "$original_meta" "$meta_file"
    grep -q 'Body A' "$TEST_CONTENT_DIR/observations/archived/a.md"
    [[ -f "$TEST_CONTENT_DIR/observations/pending/z.md" ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/arrived.md" ]]

    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 complete, 0 pending, 0 deferred"* ]]
    [[ "$output" == *"Input budget: $cap bytes"* ]]
    [[ "$output" == *"Selected bytes at creation: $cap"* ]]
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

@test "batch start selects deterministic files within a byte budget" {
    create_test_observation a.md "A" "small"
    create_test_observation b.md "B" "a much larger observation body that exceeds the budget"
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/a.md")"

    run "$SCRIPTS/batch" start --max-bytes "$cap"
    [[ "$status" -eq 0 ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<< "$output")"
    [[ "$output" == *"Input budget: $cap bytes"* ]]
    [[ "$output" == *"Skipped oversized: b.md:"* ]]
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    grep -q $'^a.md\t' "$batch_file"
    ! grep -q $'^b.md\t' "$batch_file"
    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Selected bytes at creation: $cap"* ]]
}

@test "batch start and status bound oversized-item reporting" {
    for ((i = 1; i <= 25; i++)); do
        create_test_observation "oversized-$i.md" "Observation $i" "Body $i"
    done
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/oversized-1.md")"

    run "$SCRIPTS/batch" start --max-bytes "$cap"
    [[ "$status" -eq 0 ]]
    [[ "$(grep -c 'Skipped oversized:' <<< "$output")" -le 8 ]]
    [[ "$output" == *"more oversized item(s)"* ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<< "$output")"

    run "$SCRIPTS/batch" status "$batch_id"
    [[ "$status" -eq 0 ]]
    [[ "$(grep -c 'Skipped oversized:' <<< "$output")" -le 8 ]]
    [[ "$output" == *"more oversized item(s)"* ]]
}

@test "batch start rejects an explicit over-budget selection" {
    create_test_observation a.md "A" "observation"
    commit_observations
    run "$SCRIPTS/batch" start --files a.md --max-bytes 0
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"explicit selection is"*"over --max-bytes 0"* ]]
    [[ ! -e "$TEST_CONTENT_DIR/observations/batches"/*.tsv ]]
}

@test "batch start rejects an invalid byte budget" {
    create_test_observation a.md "A" "observation"
    commit_observations
    run "$SCRIPTS/batch" start --max-bytes nope
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"--max-bytes takes a non-negative number"* ]]
}

@test "batch start reports an empty automatic zero-byte selection" {
    create_test_observation a.md "A" "observation"
    commit_observations
    run "$SCRIPTS/batch" start --max-bytes 0
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"no pending observations fit --max-bytes 0"* ]]
    [[ ! -e "$TEST_CONTENT_DIR/observations/batches"/*.tsv ]]
}

@test "batch ordering uses complete creation timestamps before filenames" {
    cat > "$TEST_CONTENT_DIR/observations/pending/a-new.md" <<'EOF'
---
title: "New later observation"
source: test
created: 2026-10-03T23:00:00Z
---

This later observation is intentionally larger than the budget.
EOF
    cat > "$TEST_CONTENT_DIR/observations/pending/z-old.md" <<'EOF'
---
title: "Old observation"
source: test
created: 2026-10-03T01:00:00Z
---

Old.
EOF
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/z-old.md")"

    run "$SCRIPTS/batch" start --max-bytes "$cap"
    [[ "$status" -eq 0 ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<<"$output")"
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    grep -q $'^z-old.md\t' "$batch_file"
    ! grep -q $'^a-new.md\t' "$batch_file"
}

@test "batch ordering breaks timestamp ties by filename and puts invalid dates last" {
    create_test_observation "z-equal.md" "Z equal" "Body"
    create_test_observation "a-equal.md" "A equal" "Body"
    create_test_observation "0-invalid.md" "Invalid date" "Body"
    sed -i 's/created: .*/created: not-a-date/' \
        "$TEST_CONTENT_DIR/observations/pending/0-invalid.md"
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/a-equal.md")"

    run "$SCRIPTS/batch" start --max-bytes "$cap"
    [[ "$status" -eq 0 ]]
    batch_id="$(sed -n 's/^Created batch: //p' <<<"$output")"
    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    grep -q $'^a-equal.md\t' "$batch_file"
    ! grep -q $'^z-equal.md\t' "$batch_file"
    ! grep -q $'^0-invalid.md\t' "$batch_file"
}

@test "batch explicit selection distinguishes exact fit from one byte short" {
    create_test_observation "exact.md" "Exact" "Body"
    create_test_observation "short.md" "Short" "Body"
    commit_observations
    exact_size="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/exact.md")"

    run "$SCRIPTS/batch" start --files exact.md --max-bytes "$exact_size"
    [[ "$status" -eq 0 ]]
    exact_batch_id="$(sed -n 's/^Created batch: //p' <<<"$output")"
    [[ -f "$TEST_CONTENT_DIR/observations/batches/$exact_batch_id" ]]

    run "$SCRIPTS/batch" start --files short.md --max-bytes "$((exact_size - 1))"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"over --max-bytes $((exact_size - 1))"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/short.md" ]]
}

@test "legacy manifests remain usable without budget metadata" {
    create_test_observation legacy.md "Legacy" "Body legacy"
    create_test_observation budgeted.md "Budgeted" "Body budgeted"
    commit_observations
    legacy_cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/legacy.md")"
    budgeted_cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/budgeted.md")"
    legacy_id="$($SCRIPTS/batch start --files legacy.md --max-bytes "$legacy_cap" | sed -n 's/^Created batch: //p')"
    budgeted_id="$($SCRIPTS/batch start --files budgeted.md --max-bytes "$budgeted_cap" | sed -n 's/^Created batch: //p')"
    legacy_file="$TEST_CONTENT_DIR/observations/batches/$legacy_id"
    budgeted_file="$TEST_CONTENT_DIR/observations/batches/$budgeted_id"
    [[ -f "$legacy_file.meta" ]]
    [[ -f "$budgeted_file.meta" ]]
    rm "$legacy_file.meta"

    run "$SCRIPTS/batch" status "$legacy_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"0 complete, 1 pending, 0 deferred"* ]]
    [[ "$output" != *"Selected bytes at creation"* ]]
    run "$SCRIPTS/batch" status "$budgeted_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Input budget: $budgeted_cap bytes"* ]]
    [[ "$output" == *"Selected bytes at creation: $budgeted_cap"* ]]

    run "$SCRIPTS/archive" --batch "$legacy_id" --disposition duplicate legacy.md --no-commit
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/archive" --batch "$budgeted_id" --disposition duplicate budgeted.md --no-commit
    [[ "$status" -eq 0 ]]
    run "$SCRIPTS/batch" status "$legacy_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 complete, 0 pending, 0 deferred"* ]]
    run "$SCRIPTS/batch" status "$budgeted_id"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"1 complete, 0 pending, 0 deferred"* ]]
}

@test "batch excludes concurrent arrivals and rejects excluded completion" {
    create_test_observation "a-selected.md" "Selected" "Body"
    create_test_observation "z-excluded.md" "Excluded" "Body"
    commit_observations
    cap="$(stat -c '%s' "$TEST_CONTENT_DIR/observations/pending/a-selected.md")"
    batch_id="$($SCRIPTS/batch start --max-bytes "$cap" | sed -n 's/^Created batch: //p')"
    create_test_observation "arrived.md" "Arrived later" "Body"

    batch_file="$TEST_CONTENT_DIR/observations/batches/$batch_id"
    grep -q $'^a-selected.md\t' "$batch_file"
    ! grep -q $'^z-excluded.md\t' "$batch_file"
    ! grep -q $'^arrived.md\t' "$batch_file"

    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate \
        z-excluded.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch: z-excluded.md"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/z-excluded.md" ]]

    run "$SCRIPTS/archive" --batch "$batch_id" --disposition duplicate \
        arrived.md --no-commit
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a member of batch: arrived.md"* ]]
    [[ -f "$TEST_CONTENT_DIR/observations/pending/arrived.md" ]]
}

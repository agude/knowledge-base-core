#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

ARTICLE='---
title: "Networking"
---

# Networking

## DNS Resolution

How DNS works.

### Recursive Lookup

Recursive resolver details.

### Caching

TTL and cache behavior.

## TCP Handshake

Three-way handshake.

### Client Hello

SYN packet.

### Server Hello

SYN-ACK packet.

## TLS

TLS overview.'

@test "section --number extracts H2 by count" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --number 2
    [[ "$output" == *"## TCP Handshake"* ]]
    [[ "$output" == *"Three-way handshake"* ]]
    [[ "$output" == *"Client Hello"* ]]
    [[ "$output" != *"## TLS"* ]]
}

@test "section --number with dot notation extracts H3" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --number 2.1
    [[ "$output" == *"### Client Hello"* ]]
    [[ "$output" == *"SYN packet"* ]]
    [[ "$output" != *"Server Hello"* ]]
}

@test "section --number 1.2 gets second H3 under first H2" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --number 1.2
    [[ "$output" == *"### Caching"* ]]
    [[ "$output" == *"TTL"* ]]
    [[ "$output" != *"Recursive"* ]]
}

@test "section --heading does substring match" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --heading "DNS"
    [[ "$output" == *"## DNS Resolution"* ]]
    [[ "$output" == *"How DNS works"* ]]
}

@test "section --heading --exact requires full match" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --heading "DNS" --exact
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Heading not found"* ]]
}

@test "section --heading --exact matches full heading" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --heading "DNS Resolution" --exact
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"## DNS Resolution"* ]]
}

@test "section fails for nonexistent number" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file knowledge/net.md --number 99
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"not found"* ]]
}

@test "section resolves bare filename" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --file net.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"## DNS Resolution"* ]]
}

@test "section default output labels freshness and provenance" {
    create_test_article "old.md" $'---\nverified: 2020-01-01\nsources:\n  - observations/archived/evidence.md\n---\n\n# Old\n\n## Details\n\nHistorical details.'
    run "$SCRIPTS/section" --file knowledge/old.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"corpus=curated article"* ]]
    [[ "$output" == *"freshness=stale"* ]]
    [[ "$output" == *"refs=observations/archived/evidence.md (article)"* ]]
}

@test "section exposes unresolved conflicts separately from freshness" {
    fixture="$BATS_TEST_DIRNAME/fixtures/lint/corrections"
    cp -R "$fixture/knowledge/." "$TEST_CONTENT_DIR/knowledge/"
    cp -R "$fixture/observations/." "$TEST_CONTENT_DIR/observations/"

    run "$SCRIPTS/section" --json --file knowledge/corrections.md \
        --heading "Unresolved conflict"
    [[ "$status" -eq 0 ]]
    run jq -e '.freshness.status == "fresh" and .conflict.status == "unresolved"' <<<"$output"
    [[ "$status" -eq 0 ]]

    run "$SCRIPTS/section" --file knowledge/corrections.md \
        --heading "Unresolved conflict"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Freshness: curated article; verified=2026-09-05; ttl=60d; freshness=fresh"* ]]
    [[ "$output" == *"Conflict: status=unresolved"* ]]
}

@test "section text-only preserves the body without metadata" {
    create_test_article "net.md" "$ARTICLE"
    run "$SCRIPTS/section" --text-only --file knowledge/net.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == "## DNS Resolution"* ]]
    [[ "$output" != *"Metadata:"* ]]
}

@test "section --top retrieves the preamble before the first H2" {
    create_test_article "top.md" '---
title: "Top"
---

# Top

Preamble text.

## Details

H2 text.'
    run "$SCRIPTS/section" --text-only --file knowledge/top.md --top
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"# Top"* ]]
    [[ "$output" == *"Preamble text."* ]]
    [[ "$output" != *"## Details"* ]]

    run "$SCRIPTS/section" --json --file knowledge/top.md --top
    [[ "$status" -eq 0 ]]
    run jq -e '.locator.number == null and .locator.heading == "top" and .locator.command == "--top" and .locator.level == null and (.content | contains("Preamble text."))' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "section --title retrieves the frontmatter title" {
    create_test_article "title.md" '---
title: "A quoted title"
---

# Heading

Body.'
    run "$SCRIPTS/section" --text-only --file knowledge/title.md --title
    [[ "$status" -eq 0 ]]
    [[ "$output" == "A quoted title" ]]

    run "$SCRIPTS/section" --json --file knowledge/title.md --title
    [[ "$status" -eq 0 ]]
    run jq -e '.locator.number == null and .locator.heading == "A quoted title" and .locator.command == "--title" and .locator.level == null and .content == "A quoted title\n"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "section JSON includes locator, freshness, provenance, and multiline content" {
    create_test_article "résumé notes.md" $'---\ntitle: "Résumé Notes"\nverified: 2020-01-01\nttl: people\nsources:\n  - "observations/archived/evidence file.md"\n---\n\n# Résumé Notes\n\n## Cité\n\nLine "one".\nLine two.'
    run "$SCRIPTS/section" --json --file "knowledge/résumé notes.md" --heading Cité
    [[ "$status" -eq 0 ]]
    json="$output"
    run jq -e '.path == "knowledge/résumé notes.md" and .corpus == "curated article" and .locator.heading == "Cité" and .freshness.status == "stale" and .freshness.ttl_days == 14 and .provenance.references[0] == "observations/archived/evidence file.md" and (.content | contains("Line \"one\".\nLine two."))' <<<"$json"
    [[ "$status" -eq 0 ]]
}

@test "section JSON includes section metadata and section provenance" {
    create_test_article "section-metadata.md" $'---\ntitle: "Section Metadata"\nverified: 2026-10-03\n---\n\n# Section Metadata\n\n## Current\n\n<!-- kb-section: verified=2026-10-03; status=current; supersedes=2 -->\nCurrent guidance.\n\n## Historical\n\n<!-- kb-section: verified=2026-01-01; status=superseded; sources=observations/archived/old.md -->\nHistorical guidance.'
    run env FRESHNESS_TODAY_EPOCH=1790985600 "$SCRIPTS/section" --json \
        --file knowledge/section-metadata.md --number 2
    [[ "$status" -eq 0 ]]
    run jq -e '.section_metadata.status == "superseded" and (.section_metadata.supersedes == null) and .section_metadata.source_scope == "section" and .provenance.scope == "section" and .freshness.status == "stale"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "section H3 inherits metadata from its H2" {
    fixture="$BATS_TEST_DIRNAME/fixtures/section-metadata"
    cp "$fixture/knowledge/metadata.md" "$TEST_CONTENT_DIR/knowledge/"
    cp -R "$fixture/observations/." "$TEST_CONTENT_DIR/observations/"
    run "$SCRIPTS/section" --json --file knowledge/metadata.md --number 2.1
    [[ "$status" -eq 0 ]]
    run jq -e '.section_metadata.status == "superseded" and .section_metadata.verified == "2026-01-01" and .section_metadata.scope == "section" and .freshness.status == "stale"' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "section metadata reports per-field inheritance" {
    create_test_article "field-origins.md" $'---\ntitle: "Field Origins"\nverified: 2026-10-03\nttl: domain\n---\n\n# Field Origins\n\n## Status override\n\n<!-- kb-section: status=superseded -->\nHistorical guidance.'
    run "$SCRIPTS/section" --json --file knowledge/field-origins.md --number 1
    [[ "$status" -eq 0 ]]
    run jq -e '
        .section_metadata.scope == "section" and
        .section_metadata.field_scopes.status == "section" and
        .section_metadata.field_scopes.verified == "article" and
        .section_metadata.field_scopes.ttl == "article"
    ' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "section metadata marks unclosed and contradictory comments invalid" {
    create_test_article "malformed-sections.md" $'---\ntitle: "Malformed Sections"\nverified: 2026-10-03\n---\n\n# Malformed Sections\n\n## Unclosed\n\n<!-- kb-section: verified=2026-01-01; status=superseded\nHistorical guidance.'
    run "$SCRIPTS/section" --json --file knowledge/malformed-sections.md --number 1
    [[ "$status" -eq 0 ]]
    run jq -e '.section_metadata.valid == false and .section_metadata.status == "superseded" and .freshness.status == "invalid"' <<< "$output"
    [[ "$status" -eq 0 ]]

    create_test_article "duplicate-sections.md" $'---\ntitle: "Duplicate Sections"\nverified: 2026-10-03\n---\n\n# Duplicate Sections\n\n## Contradictory\n\n<!-- kb-section: status=current; status=superseded -->\nContradictory guidance.'
    run "$SCRIPTS/section" --json --file knowledge/duplicate-sections.md --number 1
    [[ "$status" -eq 0 ]]
    run jq -e '.section_metadata.valid == false and (.section_metadata.invalid | contains("conflicting values for field"))' <<< "$output"
    [[ "$status" -eq 0 ]]
}

@test "section references returns the complete provenance list" {
    create_test_article "many-sources.md" $'---\ntitle: "Many Sources"\nsources:\n  - observations/evidence-1.md\n  - observations/evidence-2.md\n  - observations/evidence-3.md\n  - observations/evidence-4.md\n  - observations/evidence-5.md\n  - observations/evidence-6.md\n  - observations/evidence-7.md\n---\n\n# Many Sources\n\n## Facts\n\nDetails.'
    run "$SCRIPTS/section" --references --json --file knowledge/many-sources.md
    [[ "$status" -eq 0 ]]
    run jq -e '.provenance | (.references | length == 7) and .reference_count == 7 and .references_truncated == false' <<<"$output"
    [[ "$status" -eq 0 ]]
}

@test "article references enforce output byte budgets" {
    create_test_article "many-sources.md" $'---\ntitle: "Many Sources"\nsources:\n  - observations/evidence-1.md\n  - observations/evidence-2.md\n---\n\n# Many Sources\n\nDetails.'
    run "$SCRIPTS/section" --references --json --max-bytes 1 \
        --file knowledge/many-sources.md
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"complete references response"* ]]
}

@test "section rejects an invalid byte budget" {
    create_test_article "budget.md" '# Budget

## Evidence

Content.'
    run "$SCRIPTS/section" --max-bytes nope --file knowledge/budget.md --number 1
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"--max-bytes takes a non-negative number"* ]]
}

@test "section JSON byte budgets preserve metadata and complete lines" {
    body="$(printf 'Complete line %02d with enough text to exceed the output budget.\n' \
        1 2 3 4 5 6 7 8 9 10)"
    create_test_article "budget.md" "---
title: \"Budget\"
verified: 2026-10-03
---

# Budget

## Evidence

<!-- kb-section: status=current -->
$body"
    run bash -c '"$1" --json --max-bytes 800 --file knowledge/budget.md --number 1 >"$2" 2>"$3"' \
        _ "$SCRIPTS/section" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    jq -e '.section_metadata.available == true and .content_truncated == true and .omitted_content_bytes > 0 and (.content | contains("## Evidence")) and (.content | contains("content truncated"))' \
        "$TEST_CONTENT_DIR/out.json" >/dev/null
    [[ "$(wc -c < "$TEST_CONTENT_DIR/out.json" | tr -d '[:space:]')" -le 800 ]]
}

@test "section JSON byte budgets serialize each candidate before accepting a line" {
    body='x
y
z
q
line 01 with enough content.
line 02 with enough content.
line 03 with enough content.
line 04 with enough content.
line 05 with enough content.
line 06 with enough content.
line 07 with enough content.
line 08 with enough content.
line 09 with enough content.
line 10 with enough content.'
    create_test_article "a.md" "---
title: \"Budget\"
verified: 2026-10-03
---

# Budget

## Evidence

$body"
    run bash -c '"$1" --json --max-bytes 751 --file knowledge/a.md --number 1 >"$2" 2>"$3"' \
        _ "$SCRIPTS/section" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    [[ "$(wc -c < "$TEST_CONTENT_DIR/out.json" | tr -d '[:space:]')" -le 751 ]]
    jq -e '.content_truncated == true and
        (.content | contains("## Evidence")) and
        (.content | contains("x\ny\n")) and
        (.content | contains("z\n") | not) and
        .omitted_content_bytes > 0' "$TEST_CONTENT_DIR/out.json" >/dev/null
}

@test "section text-only byte budgets signal truncation" {
    body="$(printf 'Complete line %02d with enough text to exceed the output budget.\n' \
        1 2 3 4 5 6 7 8 9 10)"
    create_test_article "budget.md" "# Budget

## Evidence

$body"
    run "$SCRIPTS/section" --text-only --max-bytes 180 \
        --file knowledge/budget.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"content truncated"* ]]
}

@test "section text budgets clean scratch files after finalizer allocation failures" {
    local fake_bin="$TEST_CONTENT_DIR/allocation-bin"
    local scratch_dir="$TEST_CONTENT_DIR/allocation-tmp"
    local failure_marker="$TEST_CONTENT_DIR/allocation-failed"
    local real_mktemp body mode stage
    local -a mode_args
    real_mktemp="$(command -v mktemp)"
    body="$(printf 'Complete line %02d with enough text to exceed the output budget.\n' {1..40})"
    create_test_article "budget-cleanup.md" "# Budget Cleanup

## Evidence

$body"
    mkdir -p "$fake_bin" "$scratch_dir"
    cat > "$fake_bin/mktemp" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "$SECTION_FAILURE_TMP"/knowledge-section.*/"$SECTION_FAILURE_STAGE".* ]]; then
    printf 'allocation failed\n' > "$SECTION_FAILURE_MARKER"
    echo 'injected section allocation failure' >&2
    exit 23
fi
exec "$SECTION_REAL_MKTEMP" "$@"
EOF
    chmod 700 "$fake_bin/mktemp"

    for mode in text text-only; do
        mode_args=()
        [[ "$mode" != text-only ]] || mode_args+=(--text-only)
        run env TMPDIR="$scratch_dir" "$SCRIPTS/section" "${mode_args[@]}" \
            --max-bytes 512 --file knowledge/budget-cleanup.md --number 1
        [[ "$status" -eq 0 ]]
        [[ "$output" == *"content truncated"* ]]
        [[ "$(find "$scratch_dir" -mindepth 1 | wc -l)" -eq 0 ]]

        for stage in bounded candidate; do
            rm -f "$failure_marker"
            run bash -c '
                output="$1"; shift
                "$@" >"$output"
            ' _ "$TEST_CONTENT_DIR/allocation.out" env \
                PATH="$fake_bin:$PATH" TMPDIR="$scratch_dir" \
                SECTION_FAILURE_TMP="$scratch_dir" SECTION_FAILURE_STAGE="$stage" \
                SECTION_FAILURE_MARKER="$failure_marker" SECTION_REAL_MKTEMP="$real_mktemp" \
                "$SCRIPTS/section" "${mode_args[@]}" --max-bytes 512 \
                --file knowledge/budget-cleanup.md --number 1
            [[ -f "$failure_marker" ]]
            [[ "$status" -ne 0 ]]
            [[ ! -s "$TEST_CONTENT_DIR/allocation.out" ]]
            [[ "$(find "$scratch_dir" -mindepth 1 | wc -l)" -eq 0 ]]
        done
    done
}

@test "section text budgets clean scratch files after finalizer write failures" {
    local fake_bin="$TEST_CONTENT_DIR/write-bin"
    local scratch_dir="$TEST_CONTENT_DIR/write-tmp"
    local failure_marker="$TEST_CONTENT_DIR/write-failed"
    local real_cp body mode
    local -a mode_args
    real_cp="$(command -v cp)"
    body="$(printf 'Complete line %02d with enough text to exceed the output budget.\n' {1..40})"
    create_test_article "budget-cleanup.md" "# Budget Cleanup

## Evidence

$body"
    mkdir -p "$fake_bin" "$scratch_dir"
    cat > "$fake_bin/cp" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "$SECTION_FAILURE_TMP"/knowledge-section.*/bounded.* ]]; then
    printf 'write failed\n' > "$SECTION_FAILURE_MARKER"
    printf 'partial budget candidate\n' > "$2"
    echo 'injected section write failure' >&2
    exit 24
fi
exec "$SECTION_REAL_CP" "$@"
EOF
    chmod 700 "$fake_bin/cp"

    for mode in text text-only; do
        mode_args=()
        [[ "$mode" != text-only ]] || mode_args+=(--text-only)
        rm -f "$failure_marker"
        run bash -c '
            output="$1"; shift
            "$@" >"$output"
        ' _ "$TEST_CONTENT_DIR/write.out" env PATH="$fake_bin:$PATH" \
            TMPDIR="$scratch_dir" SECTION_FAILURE_TMP="$scratch_dir" \
            SECTION_FAILURE_MARKER="$failure_marker" SECTION_REAL_CP="$real_cp" \
            "$SCRIPTS/section" "${mode_args[@]}" --max-bytes 512 \
            --file knowledge/budget-cleanup.md --number 1
        [[ -f "$failure_marker" ]]
        [[ "$status" -ne 0 ]]
        [[ ! -s "$TEST_CONTENT_DIR/write.out" ]]
        [[ "$(find "$scratch_dir" -mindepth 1 | wc -l)" -eq 0 ]]
    done
}

@test "section text budgets preserve metadata and a contiguous body prefix" {
    first_line="Do not perform this action until the current deployment has been verified and the rollback procedure is ready."
    second_line="Proceed with the action only after verification and record the completed change in the deployment log for later review."
    create_test_article "budget.md" "---
title: Budget
verified: 2026-10-03
---

# Budget

## Evidence

<!-- kb-section: status=unresolved; sources=observations/archived/evidence.md -->
$first_line
$second_line"
    full_file="$TEST_CONTENT_DIR/section.txt"
    "$SCRIPTS/section" --file knowledge/budget.md --number 1 >"$full_file"
    marker_bytes="$(printf '%s\n' '[content truncated: retrieve without --max-bytes]' | wc -c | tr -d '[:space:]')"
    prefix_bytes="$(awk -v target="$first_line" '{total += length($0) + 1} $0 == target { print total; exit }' "$full_file")"
    cap=$((prefix_bytes + marker_bytes))

    run "$SCRIPTS/section" --max-bytes "$cap" --file knowledge/budget.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Freshness:"* ]]
    [[ "$output" == *"Conflict: status=unresolved"* ]]
    [[ "$output" == *"Provenance:"* ]]
    [[ "$output" == *"$first_line"* ]]
    [[ "$output" != *"$second_line"* ]]
    [[ "$output" == *"content truncated"* ]]
}

@test "section text budgets handle a large bounded prefix" {
    body="$(printf 'Large bounded line %04d with enough content to exceed the cap.\n' \
        {1..1000})"
    create_test_article "large-budget.md" "# Large Budget

## Evidence

$body"

    run "$SCRIPTS/section" --text-only --max-bytes 4096 \
        --file knowledge/large-budget.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Large bounded line 0001"* ]]
    [[ "$output" == *"content truncated"* ]]
    [[ "$output" != *"Large bounded line 1000"* ]]
}

@test "section truncation closes an open fenced block before its marker" {
    fenced_body="$(printf 'echo line %02d\n' {1..30})"
    create_test_article "fenced-budget.md" "# Budget

## Evidence

\`\`\`bash
$fenced_body\`\`\`
"

    run bash -c '"$1" --json --max-bytes 800 --file knowledge/fenced-budget.md --number 1 >"$2" 2>"$3"' \
        _ "$SCRIPTS/section" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    run jq -e '.content_truncated == true and
        (.content | contains("echo line 01")) and
        (.content | test("```\\n\\[content truncated"))' \
        "$TEST_CONTENT_DIR/out.json"
    [[ "$status" -eq 0 ]]

    run bash -c '"$1" --max-bytes 800 --file knowledge/fenced-budget.md --number 1 >"$2" 2>"$3"' \
        _ "$SCRIPTS/section" "$TEST_CONTENT_DIR/out.txt" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    grep -q $'```\n\[content truncated:' "$TEST_CONTENT_DIR/out.txt"

    run "$SCRIPTS/section" --text-only --max-bytes 180 \
        --file knowledge/fenced-budget.md --number 1
    [[ "$status" -eq 0 ]]
    [[ "$output" == *$'```\n[content truncated:'* ]]
}

@test "section budget keeps a first oversized body line whole" {
    long_line="$(printf 'x%.0s' {1..1200})"
    create_test_article "long-first-line.md" "# Budget

## Evidence

$long_line
Second line."
    run bash -c '"$1" --json --max-bytes 800 --file knowledge/long-first-line.md --number 1 >"$2" 2>"$3"' \
        _ "$SCRIPTS/section" "$TEST_CONTENT_DIR/out.json" "$TEST_CONTENT_DIR/out.err"
    [[ "$status" -eq 0 ]]
    run jq -e --arg line "$long_line" '.content_truncated == true and
        (.content | contains("## Evidence")) and
        (.content | contains($line) | not)' "$TEST_CONTENT_DIR/out.json"
    [[ "$status" -eq 0 ]]
}

@test "section output modes honor exact and one-byte-short budgets" {
    body="$(printf 'Budget line %02d with enough content to force truncation.\n' \
        1 2 3 4 5 6 7 8 9 10)"
    create_test_article "budget-matrix.md" "# Budget

## Evidence

$body"

    for mode in json text text-only; do
        mode_args=()
        case "$mode" in
            json) mode_args+=(--json) ;;
            text-only) mode_args+=(--text-only) ;;
        esac
        full_file="$TEST_CONTENT_DIR/full-$mode"
        exact_file="$TEST_CONTENT_DIR/exact-$mode"
        short_file="$TEST_CONTENT_DIR/short-$mode"
        "$SCRIPTS/section" "${mode_args[@]}" --file knowledge/budget-matrix.md \
            --number 1 >"$full_file"
        exact="$(wc -c < "$full_file" | tr -d '[:space:]')"
        run bash -c '
            script="$1"; output="$2"; error="$3"; shift 3
            "$script" "$@" >"$output" 2>"$error"
        ' _ "$SCRIPTS/section" "$exact_file" "$TEST_CONTENT_DIR/exact.err" \
            "${mode_args[@]}" --max-bytes "$exact" \
            --file knowledge/budget-matrix.md --number 1
        [[ "$status" -eq 0 ]]
        run cmp "$full_file" "$exact_file"
        [[ "$status" -eq 0 ]]

        short=$((exact - 1))
        run bash -c '
            script="$1"; output="$2"; error="$3"; shift 3
            "$script" "$@" >"$output" 2>"$error"
        ' _ "$SCRIPTS/section" "$short_file" "$TEST_CONTENT_DIR/short.err" \
            "${mode_args[@]}" --max-bytes "$short" \
            --file knowledge/budget-matrix.md --number 1
        [[ "$status" -eq 0 ]]
        used="$(wc -c < "$short_file" | tr -d '[:space:]')"
        [[ "$used" -le "$short" ]]
        if [[ "$mode" == json ]]; then
            jq -e '.content_truncated == true and .max_bytes == ('$short')' \
                "$short_file" >/dev/null
        else
            grep -q 'content truncated' "$short_file"
        fi
    done
}

@test "section metadata ignores inline examples and rejects misplaced comments" {
    create_test_article "placement.md" $'---\ntitle: Placement\nverified: 2026-10-04\n---\n# Placement\n\n## Inline\n<!-- kb-section: status=current -->\nExample `<!-- kb-section: status=unresolved -->` in prose.\n\n## Misplaced\nOrdinary body.\n<!-- kb-section: status=superseded -->'
    run "$SCRIPTS/section" --file knowledge/placement.md --number 1 --json
    [[ "$status" -eq 0 ]]
    jq -e '.section_metadata.status == "current" and .section_metadata.valid and .conflict.status == "none"' <<< "$output"
    run "$SCRIPTS/section" --file knowledge/placement.md --number 2 --json
    [[ "$status" -eq 0 ]]
    jq -e '.section_metadata.status == "current" and (.section_metadata.valid | not) and (.section_metadata.invalid | contains("placement"))' <<< "$output"
}

@test "section metadata before the first section reports invalid placement" {
    create_test_article "leading-metadata.md" $'---\ntitle: Leading\nverified: 2026-10-04\n---\n# Leading\n<!-- kb-section: status=unresolved -->\n\n## Evidence\nA fact.'
    run "$SCRIPTS/section" --file knowledge/leading-metadata.md --number 1 --json
    [[ "$status" -eq 0 ]]
    jq -e '.section_metadata.status == "current" and (.section_metadata.valid | not) and (.section_metadata.invalid | contains("placement"))' <<< "$output"
}

@test "section reference formats agree for every selector" {
    create_test_article "reference-selectors.md" $'---\ntitle: Reference selectors\nverified: 2026-10-04\nsources:\n  - observations/archived/article.md\n---\n# References\nPreamble.\n\n## Parent\n<!-- kb-section: sources=observations/archived/section.md -->\nBody.\n\n### Child\nChild body.\n\n#### Detail\nDetail body.'
    local selector selected expected="$TEST_CONTENT_DIR/expected-refs" actual="$TEST_CONTENT_DIR/actual-refs"
    local -a args
    for selector in top title parent child detail; do
        case "$selector" in
            top) args=(--top) ;;
            title) args=(--title) ;;
            parent) args=(--number 1) ;;
            child) args=(--number 1.1) ;;
            detail) args=(--heading Detail --exact) ;;
        esac
        "$SCRIPTS/section" --file knowledge/reference-selectors.md "${args[@]}" --section-references --json | jq -r '.provenance.references[]' > "$expected"
        "$SCRIPTS/section" --file knowledge/reference-selectors.md "${args[@]}" --section-references > "$actual"
        cmp "$expected" "$actual"
    done
}

@test "section ignores metadata comments followed by prose on the closing line" {
    local comment
    for comment in '<!-- kb-section: status=unresolved --> Inline evidence.' \
        $'<!-- kb-section:\nstatus=unresolved\n--> Inline evidence.'; do
        create_test_article "inline-closing.md" "---
title: Inline closing
verified: 2026-10-04
---
## Service
$comment
Body evidence."
        run "$SCRIPTS/section" --file knowledge/inline-closing.md --number 1 --json
        [[ "$status" -eq 0 ]]
        jq -e '.section_metadata.status == "current" and
            .section_metadata.scope == "article" and
            .conflict.status == "none" and
            (.content | contains("Inline evidence."))' <<< "$output"
    done
}

@test "section treats a leading-zero numeric TTL as decimal days" {
    create_test_article "decimal-ttl.md" $'---\ntitle: Decimal TTL\nverified: 2026-10-04\n---\n## Service\n<!-- kb-section: ttl=08 -->\nBody evidence.'
    local json_file="$TEST_CONTENT_DIR/ttl.json"
    local error_file="$TEST_CONTENT_DIR/ttl.stderr"
    # 2026-10-15 UTC: the section is eleven days old, beyond its eight-day TTL.
    run env FRESHNESS_TODAY_EPOCH=1792022400 bash -c '
        "$1" --file knowledge/decimal-ttl.md --number 1 --json > "$2" 2> "$3"
    ' _ "$SCRIPTS/section" "$json_file" "$error_file"
    [[ "$status" -eq 0 ]]
    jq -e '.section_metadata.valid and .freshness.ttl_days == 8 and
        .freshness.age_days == 11 and .freshness.status == "stale"' "$json_file"
    [[ ! -s "$error_file" ]]
}

@test "section metadata retains standalone closing delimiters with CRLF endings" {
    create_test_article "crlf-metadata.md" $'## Service\r\n<!-- kb-section: verified=2026-10-04; status=unresolved -->\r\nNeedle evidence.\r'
    local command
    for command in section search; do
        local -a args
        if [[ "$command" == section ]]; then
            args=(--file knowledge/crlf-metadata.md --number 1)
        else
            args=(--path knowledge/crlf-metadata.md Needle)
        fi
        run "$SCRIPTS/$command" --json "${args[@]}"
        [[ "$status" -eq 0 ]]
        jq -e '(if .results then .results[0] else . end) |
            .section_metadata.verified == "2026-10-04" and
            .section_metadata.valid and .conflict.status == "unresolved"' <<< "$output"
    done
}

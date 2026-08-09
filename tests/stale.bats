#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

@test "stale --count prints only a number" {
    create_test_article "old.md" '---
verified: 2020-01-01
---

# Old'
    create_test_article "fresh.md" "---
verified: $(date -u +%Y-%m-%d)
---

# Fresh"
    run "$SCRIPTS/stale" --count
    [[ "$status" -eq 0 ]]
    [[ "$output" == "1" ]]
}

@test "stale --count includes articles with no verified date" {
    create_test_article "nodate.md" "# No Date"
    run "$SCRIPTS/stale" --count
    [[ "$output" == "1" ]]
}

@test "stale --count prints 0 for a clean base" {
    create_test_article "fresh.md" "---
verified: $(date -u +%Y-%m-%d)
---

# Fresh"
    run "$SCRIPTS/stale" --count
    [[ "$status" -eq 0 ]]
    [[ "$output" == "0" ]]
}

@test "stale reports nothing when no articles exist" {
    run "$SCRIPTS/stale"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"No stale articles"* ]]
}

@test "stale reports nothing for recently verified article" {
    today="$(date -u +%Y-%m-%d)"
    create_test_article "fresh.md" "---
title: \"Fresh\"
verified: $today
---

# Fresh

## Section

Content."
    run "$SCRIPTS/stale"
    [[ "$output" == *"No stale articles"* ]]
}

@test "stale flags article with old verified date" {
    create_test_article "old.md" "---
title: \"Old\"
verified: 2020-01-01
---

# Old

## Section

Content."
    run "$SCRIPTS/stale"
    [[ "$output" == *"knowledge/old.md"* ]]
    [[ "$output" == *"2020-01-01"* ]]
}

@test "stale flags article with no verified date" {
    create_test_article "nodate.md" "---
title: \"No Date\"
---

# No Date

## Section

Content."
    run "$SCRIPTS/stale"
    [[ "$output" == *"[no verified]"* ]]
    [[ "$output" == *"knowledge/nodate.md"* ]]
}

@test "stale --days overrides threshold" {
    # Create article verified 10 days ago
    ten_days_ago="$(date -u -d '10 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-10d +%Y-%m-%d)"
    create_test_article "recent.md" "---
title: \"Recent\"
verified: $ten_days_ago
---

# Recent

## Section

Content."

    # Default threshold (60 days) — should not be stale
    run "$SCRIPTS/stale"
    [[ "$output" == *"No stale articles"* ]]

    # Custom threshold (5 days) — should be stale
    run "$SCRIPTS/stale" --days 5
    [[ "$output" == *"knowledge/recent.md"* ]]
}

@test "stale --path scopes to subdirectory" {
    create_test_article "top.md" "---
title: \"Top\"
verified: 2020-01-01
---

# Top

## Section

Content."
    create_test_article "sub/deep.md" "---
title: \"Deep\"
verified: 2020-01-01
---

# Deep

## Section

Content."

    run "$SCRIPTS/stale" --path knowledge/sub
    [[ "$output" == *"knowledge/sub/deep.md"* ]]
    [[ "$output" != *"knowledge/top.md"* ]]
}

@test "stale shows correct day count" {
    create_test_article "old.md" "---
title: \"Old\"
verified: 2020-01-01
---

# Old

## Section

Content."
    run "$SCRIPTS/stale"
    # Should show a large number of days
    [[ "$output" =~ [0-9]{3,}[[:space:]]+days ]]
}

@test "stale honors a numeric ttl" {
    # 30 days old: stale at ttl 14, fresh at ttl 90.
    d="$(date -u -d '30 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-30d +%Y-%m-%d)"
    create_test_article "short.md" "---
verified: $d
ttl: 14
---

# Short"
    create_test_article "long.md" "---
verified: $d
ttl: 90
---

# Long"
    run "$SCRIPTS/stale"
    [[ "$output" == *"short.md"* ]]
    [[ "$output" != *"long.md"* ]]
}

@test "stale maps named ttl values" {
    d="$(date -u -d '30 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-30d +%Y-%m-%d)"
    create_test_article "who.md" "---
verified: $d
ttl: people
---

# Who"
    create_test_article "rules.md" "---
verified: $d
ttl: domain
---

# Rules"
    run "$SCRIPTS/stale"
    [[ "$output" == *"who.md"* ]]
    [[ "$output" != *"rules.md"* ]]
}

@test "stale falls back to 60 days without a ttl" {
    d="$(date -u -d '90 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-90d +%Y-%m-%d)"
    create_test_article "plain.md" "---
verified: $d
---

# Plain"
    run "$SCRIPTS/stale"
    [[ "$output" == *"plain.md"* ]]
    [[ "$output" == *"ttl 60d"* ]]
}

@test "stale ignores an unparseable ttl and uses the default" {
    d="$(date -u -d '90 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-90d +%Y-%m-%d)"
    create_test_article "weird.md" "---
verified: $d
ttl: whenever
---

# Weird"
    run "$SCRIPTS/stale"
    [[ "$output" == *"ttl 60d"* ]]
}

@test "stale --days overrides ttl" {
    d="$(date -u -d '30 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-30d +%Y-%m-%d)"
    create_test_article "long.md" "---
verified: $d
ttl: 365
---

# Long"
    run "$SCRIPTS/stale" --days 10
    [[ "$output" == *"long.md"* ]]
}

@test "stale reads synced for source documents" {
    d="$(date -u -d '90 days ago' +%Y-%m-%d 2>/dev/null || date -u -v-90d +%Y-%m-%d)"
    mkdir -p "$TEST_CONTENT_DIR/sources"
    cat > "$TEST_CONTENT_DIR/sources/manual.md" <<EOF
---
title: "Vendor Manual"
synced: $d
---

# Vendor Manual
EOF
    run "$SCRIPTS/stale" --path sources
    [[ "$output" == *"manual.md"* ]]
    [[ "$output" == *"synced:"* ]]
}

@test "stale reports a source document with no synced date" {
    mkdir -p "$TEST_CONTENT_DIR/sources"
    echo "# No Date" > "$TEST_CONTENT_DIR/sources/manual.md"
    run "$SCRIPTS/stale" --path sources
    [[ "$output" == *"[no synced]"* ]]
}

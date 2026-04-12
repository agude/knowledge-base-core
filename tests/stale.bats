#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

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
    [[ "$output" == *"[no date]"* ]]
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

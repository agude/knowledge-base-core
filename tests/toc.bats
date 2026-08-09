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

Details on recursive lookups.

### Caching

TTL and cache behavior.

## TCP Handshake

Three-way handshake.

## TLS

TLS overview.'

@test "toc --depth 1 shows only H1" {
    create_test_article "networking.md" "$ARTICLE"
    run "$SCRIPTS/toc" --depth 1
    [[ "$output" == *"Networking"* ]]
    [[ "$output" != *"DNS Resolution"* ]]
}

@test "toc --depth 2 shows H1 and numbered H2s" {
    create_test_article "networking.md" "$ARTICLE"
    run "$SCRIPTS/toc" --depth 2
    [[ "$output" == *"1. DNS Resolution"* ]]
    [[ "$output" == *"2. TCP Handshake"* ]]
    [[ "$output" == *"3. TLS"* ]]
    [[ "$output" != *"Recursive"* ]]
}

@test "toc --depth 3 shows dot-numbered H3s" {
    create_test_article "networking.md" "$ARTICLE"
    run "$SCRIPTS/toc" --depth 3
    [[ "$output" == *"1.1. Recursive Lookup"* ]]
    [[ "$output" == *"1.2. Caching"* ]]
}

@test "toc --flat omits file grouping" {
    create_test_article "networking.md" "$ARTICLE"
    run "$SCRIPTS/toc" --flat
    [[ "$output" != *"[knowledge"* ]]
    [[ "$output" == *"Networking"* ]]
}

@test "toc shows nothing for empty knowledge dir" {
    run "$SCRIPTS/toc"
    [[ "$status" -eq 0 ]]
}

@test "toc --path scopes to a subdirectory" {
    create_test_article "sub/topic.md" "# Sub Topic

## Section One

Content."
    run "$SCRIPTS/toc" --path knowledge/sub
    [[ "$output" == *"Sub Topic"* ]]
    [[ "$output" == *"1. Section One"* ]]
}

@test "toc --map lists areas with counts" {
    create_test_article "home/a.md" "# A"
    create_test_article "home/b.md" "# B"
    create_test_article "shell/c.md" "# C"
    run "$SCRIPTS/toc" --map
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"knowledge/home/"* ]]
    [[ "$output" == *"knowledge/shell/"* ]]
    [[ "$output" == *"3 articles"* ]]
}

@test "toc --map counts nested directories in their parent" {
    create_test_article "home/a.md" "# A"
    create_test_article "home/remodel/b.md" "# B"
    create_test_article "home/remodel/c.md" "# C"
    run "$SCRIPTS/toc" --map
    [[ "$output" =~ knowledge/home/[[:space:]]+3 ]]
    [[ "$output" =~ remodel/[[:space:]]+2 ]]
}

@test "toc --map omits directories with no articles" {
    create_test_article "home/a.md" "# A"
    mkdir -p "$TEST_CONTENT_DIR/knowledge/empty"
    run "$SCRIPTS/toc" --map
    [[ "$output" != *"empty/"* ]]
}

@test "toc --map reports files loose at the root" {
    create_test_article "loose.md" "# Loose"
    create_test_article "home/a.md" "# A"
    run "$SCRIPTS/toc" --map
    [[ "$output" == *"loose files"* ]]
    [[ "$output" == *"2 articles"* ]]
}

@test "toc --map is far smaller than --depth 1" {
    for i in 1 2 3 4 5 6 7 8; do
        create_test_article "area/topic$i.md" "# Topic $i"
    done
    map_size=$("$SCRIPTS/toc" --map | wc -c)
    full_size=$("$SCRIPTS/toc" --depth 1 | wc -c)
    [[ "$map_size" -lt "$full_size" ]]
}

@test "toc h3 counter resets per H2" {
    create_test_article "multi.md" "# Multi

## First

### A

### B

## Second

### C"
    run "$SCRIPTS/toc" --depth 3
    [[ "$output" == *"1.1. A"* ]]
    [[ "$output" == *"1.2. B"* ]]
    [[ "$output" == *"2.1. C"* ]]
}

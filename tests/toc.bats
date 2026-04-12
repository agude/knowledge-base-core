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

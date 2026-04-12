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

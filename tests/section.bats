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

@test "section references returns the complete provenance list" {
    create_test_article "many-sources.md" $'---\ntitle: "Many Sources"\nsources:\n  - observations/evidence-1.md\n  - observations/evidence-2.md\n  - observations/evidence-3.md\n  - observations/evidence-4.md\n  - observations/evidence-5.md\n  - observations/evidence-6.md\n  - observations/evidence-7.md\n---\n\n# Many Sources\n\n## Facts\n\nDetails.'
    run "$SCRIPTS/section" --references --json --file knowledge/many-sources.md
    [[ "$status" -eq 0 ]]
    run jq -e '.provenance | (.references | length == 7) and .reference_count == 7 and .references_truncated == false' <<<"$output"
    [[ "$status" -eq 0 ]]
}

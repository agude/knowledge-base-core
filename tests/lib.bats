#!/usr/bin/env bats

load test_helper

setup() { setup_content_dir; }
teardown() { teardown_content_dir; }

# _lib.sh reads REPO_ROOT under `set -u`. The test helper always exports
# KB_CONTENT_DIR, which hides a missing REPO_ROOT from every other test.
@test "every script that sources _lib.sh sets REPO_ROOT first" {
    local script missing=()
    for script in "$SCRIPTS"/* "$SCRIPTS"/adapters/*/*; do
        [[ -f "$script" && "${script##*/}" != _lib.sh ]] || continue
        grep -q '^[[:space:]]*source "$SCRIPT_DIR/_lib.sh"' "$script" || continue
        awk '
            /^[[:space:]]*REPO_ROOT=/ { found = 1 }
            /^[[:space:]]*source "\$SCRIPT_DIR\/_lib.sh"/ { exit !found }
        ' "$script" || missing+=("${script#"$SCRIPTS"/}")
    done
    if (( ${#missing[@]} > 0 )); then
        printf 'missing REPO_ROOT: %s\n' "${missing[@]}" >&2
        return 1
    fi
}

@test "ttl_days normalizes decimal days and bounds seconds arithmetic" {
    source "$SCRIPTS/_lib.sh"
    run ttl_days 08
    [[ "$status" -eq 0 && "$output" == 8 ]]
    run ttl_days 000
    [[ "$status" -eq 0 && "$output" == 0 ]]
    run ttl_days 106751991167300
    [[ "$status" -eq 0 && "$output" == 106751991167300 ]]
    local unsupported
    for unsupported in 106751991167301 9223372036854775808; do
        run ttl_days "$unsupported"
        [[ "$status" -eq 0 && -z "$output" ]]
    done
}

@test "string byte counts preserve locale and match file counts" {
    source "$SCRIPTS/_lib.sh"
    local controls="" code character large value expected actual
    local original_locale="${LC_ALL-}"
    local output_file="$TEST_CONTENT_DIR/byte-count"
    # Shell strings cannot represent NUL; all other control bytes are supported.
    for (( code=1; code<32; code++ )); do
        printf -v character '%b' "\\$(printf '%03o' "$code")"
        controls+="$character"
    done
    printf -v large '%300000s' ''
    for value in '' ASCII 'café 世界' $'line\n\n' "$controls" "$large"; do
        expected="$(printf '%s' "$value" | wc -c)"
        byte_count_text "$value" > "$output_file"
        actual="$(cat "$output_file")"
        [[ "$actual" -eq "$expected" ]]
        [[ "${LC_ALL-}" == "$original_locale" ]]
    done
}

@test "retrieval marks out-of-range article and section TTLs invalid" {
    create_test_article "ttl-range.md" $'---\ntitle: TTL range\nverified: 2026-10-04\nttl: 106751991167301\n---\n## Service\n<!-- kb-section: ttl=9223372036854775808 -->\nEvidence.'
    local selector
    for selector in --title --number; do
        local -a args=("$selector")
        [[ "$selector" != --number ]] || args+=(1)
        run "$SCRIPTS/section" --file knowledge/ttl-range.md "${args[@]}" --json
        [[ "$status" -eq 0 ]]
        jq -e '.freshness.status == "invalid" and .freshness.ttl_days == null' <<< "$output"
    done
}

# --- show_help ---

@test "show_help extracts comment header" {
    local script="$TEST_CONTENT_DIR/test-script.sh"
    cat > "$script" <<'SCRIPT'
#!/usr/bin/env bash
#
# test-script - A test script.
#
# Does something useful.
#
# Usage:
#   test-script [--flag]

set -euo pipefail
SCRIPT
    source "$SCRIPTS/_lib.sh"
    run show_help "$script"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"test-script - A test script."* ]]
    [[ "$output" == *"Usage:"* ]]
    [[ "$output" != *"set -euo pipefail"* ]]
}

# --- need_arg ---

@test "need_arg fails when no argument follows flag" {
    source "$SCRIPTS/_lib.sh"
    run need_arg "--title" 1
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"requires an argument"* ]]
}

@test "need_arg succeeds when argument follows flag" {
    source "$SCRIPTS/_lib.sh"
    run need_arg "--title" 2
    [[ "$status" -eq 0 ]]
}

@test "parse_nonnegative_decimal normalizes leading zeroes" {
    source "$SCRIPTS/_lib.sh"
    run parse_nonnegative_decimal "--max-bytes" 01000
    [[ "$status" -eq 0 ]]
    [[ "$output" == "1000" ]]

    run parse_nonnegative_decimal "--max-bytes" 000
    [[ "$status" -eq 0 ]]
    [[ "$output" == "0" ]]
}

@test "parse_nonnegative_decimal rejects overflow" {
    source "$SCRIPTS/_lib.sh"
    run parse_nonnegative_decimal "--max-bytes" 999999999999999999999999999999
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"exceeds the supported integer range"* ]]
}

@test "sha256_file falls back to shasum" {
    local fake_bin="$TEST_CONTENT_DIR/hash-bin" file="$TEST_CONTENT_DIR/hash.txt"
    mkdir -p "$fake_bin"
    printf 'hash me\n' > "$file"
    ln -s "$(command -v shasum)" "$fake_bin/shasum"
    ln -s "$(command -v awk)" "$fake_bin/awk"
    expected="$(sha256sum "$file" | awk '{print $1}')"

    run env PATH="$fake_bin" /bin/bash -c \
        'source "$1"; sha256_file "$2"' _ "$SCRIPTS/_lib.sh" "$file"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "$expected" ]]
}

# --- yaml_escape ---

@test "yaml_escape escapes double quotes" {
    source "$SCRIPTS/_lib.sh"
    result="$(yaml_escape 'say "hello"')"
    [[ "$result" == 'say \"hello\"' ]]
}

@test "yaml_escape escapes backslashes" {
    source "$SCRIPTS/_lib.sh"
    result="$(yaml_escape 'path\to\file')"
    [[ "$result" == 'path\\to\\file' ]]
}

# --- frontmatter_field ---

@test "frontmatter_field extracts unquoted value" {
    create_test_article "fm-test.md" "---
source: session
---"
    source "$SCRIPTS/_lib.sh"
    result="$(frontmatter_field "source" "$TEST_CONTENT_DIR/knowledge/fm-test.md")"
    [[ "$result" == "session" ]]
}

@test "frontmatter_field extracts quoted value" {
    create_test_article "fm-test.md" '---
title: "Hello World"
---'
    source "$SCRIPTS/_lib.sh"
    result="$(frontmatter_field "title" "$TEST_CONTENT_DIR/knowledge/fm-test.md")"
    [[ "$result" == "Hello World" ]]
}

@test "frontmatter_field returns 1 for missing field" {
    create_test_article "fm-test.md" "---
title: test
---"
    source "$SCRIPTS/_lib.sh"
    run frontmatter_field "missing" "$TEST_CONTENT_DIR/knowledge/fm-test.md"
    [[ "$status" -ne 0 ]]
}

# --- locked_commit ---

@test "locked_commit commits only the named paths" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    create_test_article "staged-by-someone-else.md" "# Draft"
    git -C "$TEST_CONTENT_DIR" add knowledge/staged-by-someone-else.md

    source "$SCRIPTS/_lib.sh"
    run locked_commit "Observe: Obs" "observations/pending/20260412T000000-aaaa.md"
    [[ "$status" -eq 0 ]]

    files="$(git -C "$TEST_CONTENT_DIR" show --name-only --format='' HEAD)"
    [[ "$files" == *"observations/pending/20260412T000000-aaaa.md"* ]]
    [[ "$files" != *"staged-by-someone-else"* ]]
}

@test "locked_commit returns nonzero when the commit is rejected" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    cat > "$TEST_CONTENT_DIR/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
echo "rejected by test hook" >&2
exit 1
HOOK
    chmod +x "$TEST_CONTENT_DIR/.git/hooks/pre-commit"

    source "$SCRIPTS/_lib.sh"
    run locked_commit "Observe: Obs" "observations/pending/20260412T000000-aaaa.md"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"commit failed"* ]]
}

@test "locked_commit releases the lock after a rejected commit" {
    create_test_observation "20260412T000000-aaaa.md" "Obs" "Body"
    cat > "$TEST_CONTENT_DIR/.git/hooks/pre-commit" <<'HOOK'
#!/usr/bin/env bash
exit 1
HOOK
    chmod +x "$TEST_CONTENT_DIR/.git/hooks/pre-commit"

    source "$SCRIPTS/_lib.sh"
    run locked_commit "Observe: Obs" "observations/pending/20260412T000000-aaaa.md"
    [[ ! -d "$TEST_CONTENT_DIR/.observe.lock" ]]
}

# --- resolve_path ---

@test "resolve_path finds knowledge-relative path" {
    create_test_article "topic.md" "# Topic"
    source "$SCRIPTS/_lib.sh"
    result="$(resolve_path "knowledge/topic.md")"
    [[ "$result" == "knowledge/topic.md" ]]
}

@test "resolve_path prepends knowledge/ for bare filename" {
    create_test_article "topic.md" "# Topic"
    source "$SCRIPTS/_lib.sh"
    result="$(resolve_path "topic.md")"
    [[ "$result" == "knowledge/topic.md" ]]
}

@test "resolve_path fails for nonexistent file" {
    source "$SCRIPTS/_lib.sh"
    run resolve_path "no-such-file.md"
    [[ "$status" -ne 0 ]]
}

# --- path containment ---
#
# The PreToolUse hook auto-approves these scripts, so their arguments are
# part of the security boundary.

@test "resolve_path refuses a path escaping the content root" {
    source "$SCRIPTS/_lib.sh"
    run resolve_path "../../../../etc/passwd"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"outside the knowledge base"* ]]
}

@test "resolve_path refuses an absolute path outside the content root" {
    source "$SCRIPTS/_lib.sh"
    run resolve_path "/etc/passwd"
    [[ "$status" -ne 0 ]]
}

@test "resolve_path refuses a symlink pointing out of the content root" {
    ln -s /etc/passwd "$TEST_CONTENT_DIR/knowledge/sneaky.md"
    source "$SCRIPTS/_lib.sh"
    run resolve_path "knowledge/sneaky.md"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"outside the knowledge base"* ]]
}

@test "resolve_path still accepts ordinary paths" {
    create_test_article "topic.md" "# Topic"
    source "$SCRIPTS/_lib.sh"
    run resolve_path "topic.md"
    [[ "$status" -eq 0 ]]
    [[ "$output" == "knowledge/topic.md" ]]
}

@test "section refuses to read outside the content root" {
    run "$SCRIPTS/section" --file ../../../../etc/passwd --number 1
    [[ "$status" -ne 0 ]]
}

@test "toc refuses to scan outside the content root" {
    run "$SCRIPTS/toc" --path ../../../../etc
    [[ "$status" -ne 0 ]]
}

@test "archive refuses a filename containing a path" {
    outside="$TEST_CONTENT_DIR/../outside-$$.md"
    echo "not yours" > "$outside"
    run "$SCRIPTS/archive" "../outside-$$.md"
    [[ "$status" -ne 0 ]]
    [[ -f "$outside" ]]
    rm -f "$outside"
}

@test "resolve refuses a question filename containing a path" {
    run "$SCRIPTS/resolve" --file "../../etc/passwd"
    [[ "$status" -ne 0 ]]
    [[ "$output" == *"Not a question filename"* ]]
}

@test "streaming JSON encoder round trips all bytes without scratch allocation" {
    local input="$TEST_CONTENT_DIR/bytes" encoded="$TEST_CONTENT_DIR/encoded.json"
    local decoded="$TEST_CONTENT_DIR/decoded" fake_bin="$TEST_CONTENT_DIR/encoder-bin"
    local code
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\necho unexpected-scratch-allocation >&2\nexit 23\n' > "$fake_bin/mktemp"
    chmod 700 "$fake_bin/mktemp"
    for (( code=0; code<32; code++ )); do
        printf '%b' "\\$(printf '%03o' "$code")"
    done > "$input"
    printf '%s\n\n' 'Unicode café 日本語; quotes " and backslashes \' >> "$input"
    run env PATH="$fake_bin:$PATH" bash -c 'set -euo pipefail; source "$1"; json_quote_file "$2" > "$3"' _ "$SCRIPTS/_lib.sh" "$input" "$encoded"
    [[ "$status" -eq 0 ]]
    jq -j . "$encoded" > "$decoded"
    cmp "$input" "$decoded"
    run env PATH="$fake_bin:$PATH" bash -c 'set -euo pipefail; source "$1"; json_quote "$2" > "$3"' _ "$SCRIPTS/_lib.sh" $'café\t"\\\n\n' "$encoded"
    [[ "$status" -eq 0 ]]
    printf '%s' $'café\t"\\\n\n' > "$input"
    jq -j . "$encoded" > "$decoded"
    cmp "$input" "$decoded"
    : > "$input"
    run env PATH="$fake_bin:$PATH" bash -c 'set -euo pipefail; source "$1"; json_quote_file "$2"' _ "$SCRIPTS/_lib.sh" "$input"
    [[ "$status" -eq 0 && "$output" == '""' ]]
}

@test "streaming JSON encoder propagates partial upstream failure without pipefail" {
    local fake_bin="$TEST_CONTENT_DIR/od-bin" input="$TEST_CONTENT_DIR/input"
    mkdir -p "$fake_bin"
    printf '#!/bin/sh\nprintf " 61 62\\n"\nexit 23\n' > "$fake_bin/od"
    chmod 700 "$fake_bin/od"
    printf 'abc' > "$input"
    run env PATH="$fake_bin:$PATH" bash -c 'source "$1"; json_quote_file "$2"' _ "$SCRIPTS/_lib.sh" "$input"
    [[ "$status" -ne 0 ]]
}

@test "metadata cache restores selected sections and full articles without rereading" {
    create_test_article "cache-a.md" $'---\ntitle: Cache A\nverified: 2026-10-04\nttl: domain\nsources:\n  - observations/archived/article-a.md\n---\n# A\n\n## Parent\n<!-- kb-section: status=superseded; sources=observations/archived/a-first.md, observations/archived/a-second.md -->\nA body.\n\n### Child\nInherited body.'
    create_test_article "cache-b.md" $'---\ntitle: Cache B\nverified: 2026-01-01\n---\n# B\n\n## Current\nB body.'
    source "$SCRIPTS/_lib.sh"
    SECTION_METADATA_CACHE_ENABLED=true
    retrieval_metadata_for_file knowledge/cache-a.md "$TEST_CONTENT_DIR/knowledge/cache-a.md"
    section_metadata_for_file knowledge/cache-a.md "$TEST_CONTENT_DIR/knowledge/cache-a.md" 1
    retrieval_metadata_for_file knowledge/cache-b.md "$TEST_CONTENT_DIR/knowledge/cache-b.md"
    section_metadata_for_file knowledge/cache-b.md "$TEST_CONTENT_DIR/knowledge/cache-b.md" 1
    rm "$TEST_CONTENT_DIR/knowledge/cache-a.md"
    section_metadata_for_file knowledge/cache-a.md "$TEST_CONTENT_DIR/knowledge/cache-a.md" 1.1
    [[ "$SECTION_METADATA_STATUS" == superseded ]]
    [[ "$SECTION_METADATA_VERIFIED" == 2026-10-04 ]]
    [[ "$PROVENANCE_SCOPE" == section ]]
    [[ "${PROVENANCE_REFERENCES[*]}" == 'observations/archived/a-first.md observations/archived/a-second.md' ]]
    section_metadata_for_file knowledge/cache-a.md "$TEST_CONTENT_DIR/knowledge/cache-a.md"
    [[ "${#SECTION_META_STATUS[@]}" -eq 2 ]]
    [[ "$PROVENANCE_SCOPE" == article ]]
    [[ "${PROVENANCE_REFERENCES[*]}" == observations/archived/article-a.md ]]
}

@test "retrieval loads article state once before lazy section parsing" {
    create_test_article "lazy-a.md" $'---\ntitle: Lazy A\nverified: 2026-10-04\nttl: 08\nstatus: superseded\neffective: 2026-10-01\nsources:\n  - observations/archived/article-a.md\n---\n## Parent\nEvidence.\n### Child\nInherited evidence.'
    create_test_article "lazy-b.md" $'---\ntitle: Lazy B\nverified: 2026-01-01\n---\n## Current\nEvidence.'
    source "$SCRIPTS/_lib.sh"
    SECTION_METADATA_CACHE_ENABLED=true
    retrieval_metadata_for_file knowledge/lazy-a.md "$TEST_CONTENT_DIR/knowledge/lazy-a.md"
    [[ -z "${SECTION_META_CACHE_LOCATORS[knowledge/lazy-a.md]}" ]]
    retrieval_metadata_for_file knowledge/lazy-b.md "$TEST_CONTENT_DIR/knowledge/lazy-b.md" 1

    # A later section selector may read the body, but must reuse article state.
    freshness_for_file() { return 1; }
    conflict_status_for_file() { return 1; }
    provenance_for_file() { return 1; }
    retrieval_metadata_for_file knowledge/lazy-a.md "$TEST_CONTENT_DIR/knowledge/lazy-a.md" 1.1
    [[ "$SECTION_METADATA_STATUS" == superseded ]]
    [[ "$SECTION_METADATA_TTL" == 08 ]]
    [[ "$SECTION_METADATA_EFFECTIVE" == 2026-10-01 ]]
    [[ "${PROVENANCE_REFERENCES[*]}" == observations/archived/article-a.md ]]
    [[ "$FRESHNESS_DATE_VALUE" == 2026-10-04 ]]
    rm "$TEST_CONTENT_DIR/knowledge/lazy-a.md"
    retrieval_metadata_for_file knowledge/lazy-a.md "$TEST_CONTENT_DIR/knowledge/lazy-a.md"
    [[ "$SECTION_METADATA_AVAILABLE" == false ]]
    [[ "$PROVENANCE_SCOPE" == article ]]
    [[ "${PROVENANCE_REFERENCES[*]}" == observations/archived/article-a.md ]]
}

@test "article cache preserves interleaved question and archive provenance" {
    create_test_question "open.md" "Open question"
    create_test_observation "archived.md" "Archived observation" "Evidence"
    mv "$TEST_CONTENT_DIR/observations/pending/archived.md" "$TEST_CONTENT_DIR/observations/archived/archived.md"
    sed -i '/^source:/a disposition: incorporated\ndestination: knowledge/service.md' \
        "$TEST_CONTENT_DIR/observations/archived/archived.md"
    source "$SCRIPTS/_lib.sh"
    SECTION_METADATA_CACHE_ENABLED=true
    retrieval_metadata_for_file questions/open/open.md "$TEST_CONTENT_DIR/questions/open/open.md"
    retrieval_metadata_for_file observations/archived/archived.md "$TEST_CONTENT_DIR/observations/archived/archived.md"
    [[ "$PROVENANCE_DISPOSITION" == incorporated ]]
    [[ "$PROVENANCE_DESTINATION" == knowledge/service.md ]]
    rm "$TEST_CONTENT_DIR/questions/open/open.md" "$TEST_CONTENT_DIR/observations/archived/archived.md"
    retrieval_metadata_for_file questions/open/open.md "$TEST_CONTENT_DIR/questions/open/open.md"
    [[ "$RESULT_CORPUS" == question && "$PROVENANCE_STATE" == open ]]
    [[ -z "$PROVENANCE_DISPOSITION" && -z "$PROVENANCE_DESTINATION" ]]
    retrieval_metadata_for_file observations/archived/archived.md "$TEST_CONTENT_DIR/observations/archived/archived.md"
    [[ "$PROVENANCE_DISPOSITION" == incorporated ]]
    [[ "$PROVENANCE_DESTINATION" == knowledge/service.md ]]
    [[ -z "$PROVENANCE_STATE" ]]
}

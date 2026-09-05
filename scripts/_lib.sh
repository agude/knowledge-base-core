#!/usr/bin/env bash
#
# _lib.sh - Shared functions for knowledge base scripts.
#
# Source this after setting REPO_ROOT:
#   SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
#   REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
#   source "$SCRIPT_DIR/_lib.sh"
#
# Sets CONTENT_DIR (defaults to $REPO_ROOT/content, overridable via
# KB_CONTENT_DIR env var). All content paths go through CONTENT_DIR.

CONTENT_DIR="${KB_CONTENT_DIR:-$REPO_ROOT/content}"

# show_help - Print the comment-header help block from a script.
#
# Extracts lines between the shebang and the first blank line, stripping
# the leading "# " or "#" prefix. Uses awk for macOS/Linux portability.
#
# Usage (inside a -h|--help case arm):
#   show_help "$0"
show_help() {
    awk 'NR==1{next} /^$/{exit} {sub(/^# ?/,""); print}' "$1"
}

# need_arg - Verify that a flag's required value is present.
#
# Call inside argument-parsing loops before accessing $2.
#
# Usage:
#   --flag) need_arg "$1" "$#"; VALUE="$2"; shift 2 ;;
need_arg() {
    if (( $2 < 2 )); then
        echo "Option $1 requires an argument" >&2
        exit 1
    fi
}

# path_is_contained - True when a path resolves inside the content root.
#
# The command-approval hook auto-approves these scripts, so their arguments are
# part of the security boundary: without this, `section --file
# ../../../../etc/passwd` reads outside the knowledge base with no
# permission prompt, and `toc --path ../../..` walks the filesystem.
#
# Compares canonicalized paths, so symlinks pointing out are caught too.
path_is_contained() {
    local target="$1" root real

    root="$(cd "$CONTENT_DIR" 2>/dev/null && pwd -P)" || return 1
    real="$(canonicalize "$target")" || return 1

    [[ "$real" == "$root" || "$real" == "$root"/* ]]
}

# canonicalize - Absolute path with symlinks resolved.
#
# readlink -f would do this, but BSD readlink has no -f. Follows the
# final component too: a symlink inside the content root pointing at
# /etc/passwd is exactly the case path_is_contained exists to catch.
canonicalize() {
    local target="$1" link dir base hops=0

    while [[ -L "$target" ]] && (( hops < 40 )); do
        link="$(readlink "$target")" || return 1
        if [[ "$link" == /* ]]; then
            target="$link"
        else
            target="$(dirname "$target")/$link"
        fi
        hops=$((hops + 1))
    done

    if [[ -d "$target" ]]; then
        ( cd "$target" 2>/dev/null && pwd -P ) || return 1
        return 0
    fi

    dir="$(cd "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
    base="$(basename "$target")"
    echo "$dir/$base"
}

# resolve_path - Normalize a path to be relative to the content root.
#
# Handles: absolute paths, content-relative paths, knowledge/-relative paths,
# and bare filenames (searched under knowledge/ only).
#
# Refuses anything that resolves outside the content root.
#
# Prints the resolved content-relative path on success.
# Returns 1 if not found; prints error to stderr if ambiguous or escaping.
#
# Usage — check the status explicitly; do NOT write
#   resolved="$(resolve_path "$p")" && VAR=...
# because `set -e` exempts every command in a && list except the last, so
# a failure there silently leaves the caller holding the raw path:
#
#   if ! resolved="$(resolve_path "$path")"; then
#       exit 1
#   fi
#   VAR="$CONTENT_DIR/$resolved"
resolve_path() {
    local input="$1"

    # Strip absolute content root prefix
    input="${input#"$CONTENT_DIR/"}"

    # Exists relative to content root
    if [[ -e "$CONTENT_DIR/$input" ]]; then
        if ! path_is_contained "$CONTENT_DIR/$input"; then
            echo "Refusing path outside the knowledge base: $1" >&2
            return 1
        fi
        echo "$input"
        return 0
    fi

    # Try prepending knowledge/
    if [[ "$input" != knowledge/* ]] && [[ "$input" != sources/* ]] \
        && [[ "$input" != observations/* ]] && [[ "$input" != questions/* ]]; then
        if [[ -e "$CONTENT_DIR/knowledge/$input" ]]; then
            if ! path_is_contained "$CONTENT_DIR/knowledge/$input"; then
                echo "Refusing path outside the knowledge base: $1" >&2
                return 1
            fi
            echo "knowledge/$input"
            return 0
        fi
    fi

    # Basename search under knowledge/, sources/, observations/, questions/
    local base matches count
    base="$(basename "$input")"
    matches="$(find "$CONTENT_DIR/knowledge" "$CONTENT_DIR/sources" \
        "$CONTENT_DIR/observations" "$CONTENT_DIR/questions" \
        -name "$base" 2>/dev/null)"

    if [[ -z "$matches" ]]; then
        return 1
    fi

    count="$(echo "$matches" | wc -l | tr -d ' ')"

    if (( count == 1 )); then
        if ! path_is_contained "$matches"; then
            echo "Refusing path outside the knowledge base: $1" >&2
            return 1
        fi
        echo "${matches#"$CONTENT_DIR/"}"
        return 0
    fi

    echo "Ambiguous match for '$base' — $count files found:" >&2
    local m
    while IFS= read -r m; do
        echo "  ${m#"$CONTENT_DIR/"}" >&2
    done <<< "$matches"
    return 1
}

# break_stale_git_lock - Remove git's index.lock if stale (>5 min old, no holder).
#
# Git's index.lock survives process kills (SIGKILL, crashes). This checks
# age and whether any git process is running before removing.
#
# Usage: break_stale_git_lock /path/to/repo
break_stale_git_lock() {
    local repo_dir="$1"
    local lockfile="$repo_dir/.git/index.lock"

    [[ -f "$lockfile" ]] || return 0

    # Check if any git process is running in this repo
    if pgrep -f "git.*$repo_dir" >/dev/null 2>&1; then
        return 0
    fi

    # Break if older than 5 minutes
    if find "$lockfile" -maxdepth 0 -mmin +5 2>/dev/null | grep -q .; then
        rm -f "$lockfile"
        echo "Removed stale git lock: $lockfile" >&2
    fi
}

# locked_commit - Commit given paths with a lock to serialize concurrent writes.
#
# Commits ONLY the named paths. A bare `git commit` would sweep up whatever
# else happened to be staged — an observe firing mid-curation would carry
# the curator's staged articles into a "Observe: session transcript" commit.
#
# The pathspec form builds a temporary index, so a pre-commit hook that
# modifies files cannot write back into this commit. That is fine for the
# capture scripts, which only ever commit observations/ and questions/;
# curation commits knowledge/ through the full index instead.
#
# Uses a PID file inside the lock dir to detect and break stale locks
# left by killed processes. Registers an EXIT trap as a safety net;
# clears it after the explicit cleanup to avoid stealing another
# process's lock. Git operations run in a subshell to avoid leaking
# a cd into the caller.
#
# Also cleans up stale .git/index.lock files before git operations.
#
# Returns the git exit status, so a rejecting hook is visible to callers
# instead of leaving a file written but uncommitted.
#
# Usage:
#   locked_commit "message" path1 [path2 ...]
acquire_lock() {
    local lockdir="$CONTENT_DIR/.observe.lock"
    local pidfile="$lockdir/pid"
    local retries=30

    while ! mkdir "$lockdir" 2>/dev/null; do
        # Break stale locks left by dead processes
        if [[ -f "$pidfile" ]]; then
            local owner
            owner="$(cat "$pidfile" 2>/dev/null || echo "")"
            if [[ -n "$owner" ]] && ! kill -0 "$owner" 2>/dev/null; then
                rm -rf "$lockdir"
                continue
            fi
        fi
        retries=$((retries - 1))
        if (( retries <= 0 )); then
            echo "Could not acquire lock" >&2
            return 1
        fi
        sleep 1
    done

    echo $$ > "$pidfile"
    trap 'rm -rf "'"$CONTENT_DIR"'/.observe.lock" 2>/dev/null || true' EXIT

    # Clean up stale git locks before operating
    break_stale_git_lock "$CONTENT_DIR"
    return 0
}

release_lock() {
    rm -rf "$CONTENT_DIR/.observe.lock" 2>/dev/null || true
    trap - EXIT
}

locked_commit() {
    local message="$1"
    shift

    acquire_lock || return 1

    local rc=0
    (
        cd "$CONTENT_DIR"
        for p in "$@"; do
            git add "$p"
        done
        git commit -q -m "$message" -- "$@"
    ) || rc=$?

    release_lock

    if (( rc != 0 )); then
        echo "locked_commit: commit failed ($rc) for: $message" >&2
    fi
    return $rc
}

# locked_commit_index - Commit everything staged, under the same lock.
#
# For curation, which edits articles the pre-commit hook then stamps and
# re-stages. A pathspec commit builds a temporary index and would discard
# that stamping, so this one deliberately commits the whole index — and
# takes the lock so a concurrent observe cannot slip a file in between.
#
# Usage:
#   locked_commit_index "message" path1 [path2 ...]
locked_commit_index() {
    local message="$1"
    shift

    acquire_lock || return 1

    local rc=0
    (
        cd "$CONTENT_DIR"
        for p in "$@"; do
            [[ -e "$p" ]] || continue
            git add -A "$p"
        done
        git commit -q -m "$message"
    ) || rc=$?

    release_lock

    if (( rc != 0 )); then
        echo "locked_commit_index: commit failed ($rc) for: $message" >&2
    fi
    return $rc
}

# session_dir - Path holding per-session observation buffers.
#
# Every user prompt of every session passes through these files, so the
# directory must not be a predictable shared path: on a multi-user host
# whoever creates /tmp/knowledge-sessions first receives the transcript
# stream. Prefer XDG_RUNTIME_DIR, which is already per-user and mode 700;
# fall back to a uid-scoped name under /tmp for macOS.
#
# SESSION_DIR overrides it (the tests set it).
#
# Usage: dir="$(session_dir)"
session_dir() {
    if [[ -n "${SESSION_DIR:-}" ]]; then
        echo "$SESSION_DIR"
        return 0
    fi
    echo "${XDG_RUNTIME_DIR:-/tmp}/knowledge-sessions-$(id -u)"
}

# instruction_file - Select the canonical instruction file in a directory.
#
# AGENTS.md is the portable name. CLAUDE.md is retained as a compatibility
# name for installations that have not migrated yet. Prefer AGENTS.md when
# both exist so every client uses the same source.
instruction_file() {
    local dir="$1"

    if [[ -f "$dir/AGENTS.md" ]]; then
        echo "$dir/AGENTS.md"
    elif [[ -f "$dir/CLAUDE.md" ]]; then
        echo "$dir/CLAUDE.md"
    fi
}

# ensure_session_dir - Create the session directory, private, and verify it.
#
# Returns 1 if the directory cannot be created or is owned by someone
# else, so callers can skip capture instead of writing prompts somewhere
# another user can read.
ensure_session_dir() {
    local dir="$1"

    # umask, not `mkdir -m`: with -p, -m applies only to the deepest
    # directory, and there must be no window where the path is readable.
    ( umask 077 && mkdir -p "$dir" ) 2>/dev/null || return 1
    [[ -d "$dir" ]] || return 1
    [[ -O "$dir" ]] || return 1

    # A pre-existing directory keeps its old mode; tighten it.
    chmod 700 "$dir" 2>/dev/null || true
    return 0
}

# session_file_path - Return the canonical path for a session buffer.
#
# Session IDs are supplied by host clients. Restrict them to filename-safe
# characters before interpolating them into a path; callers must not be able
# to escape the private session directory.
session_file_path() {
    local dir="$1" id="$2"

    [[ "$id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 1
    printf '%s/session-%s.jsonl\n' "$dir" "$id"
}

# session_buffer_path - Path to a session's buffer, recreating it if gone.
#
# The buffer's existence used to gate capture: session-prompt and
# session-stop exited when the file was missing. But session-start
# flushes and deletes buffers older than an hour, and mtime only advances
# on a recorded turn — so a session idle for an hour (a terminal left
# open) had its buffer swept by the next session to start, and then
# captured nothing for the rest of its life, silently and permanently.
#
# Recreate instead. A swept session resumes into a second observation,
# which is honest about what happened; capturing nothing is not.
#
# Only recreate when session-start actually ran for this session: it sets
# both KNOWLEDGE_OBSERVE=1 and KNOWLEDGE_SESSION_FILE. Otherwise capture
# stays off.
#
# Prints the path; returns 1 when capture should be skipped.
#
# Usage:
#   file="$(session_buffer_path "$dir" "$id")" || exit 0
session_buffer_path() {
    local dir="$1" id="$2"
    local file

    file="$(session_file_path "$dir" "$id")" || return 1

    if [[ -f "$file" ]]; then
        echo "$file"
        return 0
    fi

    if [[ "${KNOWLEDGE_OBSERVE:-}" != "1" ]] \
        && [[ -z "${KNOWLEDGE_SESSION_FILE:-}" ]]; then
        return 1
    fi

    ensure_session_dir "$dir" || return 1
    touch "$file" 2>/dev/null || return 1
    chmod 600 "$file" 2>/dev/null || true

    echo "$file"
    return 0
}

# --- Markdown heading parsing -------------------------------------------
#
# A `#` line inside a fenced code block is a shell comment, not a heading.
# Parsers that ignore fences invent topics in `toc` and truncate `section`
# at the first commented command. Both scripts read files line by line, so
# the state lives in globals: call md_heading_reset before each file, then
# md_heading on every line.

MD_FENCE_OPEN=false
MD_FENCE_CHAR=""
MD_FENCE_LEN=0
# Outputs of md_heading, read by the scripts that source this file.
# shellcheck disable=SC2034
MD_HEADING_LEVEL=0
# shellcheck disable=SC2034
MD_HEADING_TEXT=""

# Up to three leading spaces, then a run of three or more ` or ~.
_MD_FENCE_RE='^[[:blank:]]{0,3}(`{3,}|~{3,})[[:blank:]]*(.*)$'

# md_heading_reset - Clear fence state. Call once per file.
md_heading_reset() {
    MD_FENCE_OPEN=false
    MD_FENCE_CHAR=""
    MD_FENCE_LEN=0
}

# _md_fence_track - Update fence state for one line.
#
# Returns 0 if the line is a fence delimiter, 1 otherwise.
_md_fence_track() {
    local line="$1" marker info char len

    [[ "$line" =~ $_MD_FENCE_RE ]] || return 1

    marker="${BASH_REMATCH[1]}"
    info="${BASH_REMATCH[2]}"
    char="${marker:0:1}"
    len=${#marker}

    if [[ "$MD_FENCE_OPEN" == false ]]; then
        # A backtick fence may not carry backticks in its info string.
        if [[ "$char" == '`' ]] && [[ "$info" == *'`'* ]]; then
            return 1
        fi
        MD_FENCE_OPEN=true
        MD_FENCE_CHAR="$char"
        MD_FENCE_LEN=$len
        return 0
    fi

    # Only a bare marker of the same character and at least the same
    # length closes the block; anything else is content.
    if [[ "$char" == "$MD_FENCE_CHAR" ]] && (( len >= MD_FENCE_LEN )) \
        && [[ -z "${info//[[:blank:]]/}" ]]; then
        md_heading_reset
    fi
    return 0
}

# md_heading - Classify one line, skipping fenced code blocks.
#
# Returns 0 and sets MD_HEADING_LEVEL and MD_HEADING_TEXT when the line is
# an ATX heading outside a fence. Returns 1 otherwise.
#
# Usage:
#   md_heading_reset
#   while IFS= read -r line; do
#       md_heading "$line" || continue
#       ...
#   done < "$file"
md_heading() {
    local line="$1"

    _md_fence_track "$line" && return 1
    [[ "$MD_FENCE_OPEN" == true ]] && return 1
    [[ "$line" =~ ^(#{1,6})[[:space:]]+(.*) ]] || return 1

    # shellcheck disable=SC2034  # read by callers after md_heading returns
    MD_HEADING_LEVEL=${#BASH_REMATCH[1]}
    local text="${BASH_REMATCH[2]}"

    # ATX headings may close with hashes: `## Title ##`. Strip them, or
    # toc prints a name that `section --heading --exact` cannot match,
    # and toc output is documented as section's input.
    text="${text%"${text##*[![:space:]]}"}"
    if [[ "$text" =~ ^(.*[^#[:space:]])[[:space:]]+#+$ ]]; then
        text="${BASH_REMATCH[1]}"
    elif [[ "$text" =~ ^#+$ ]]; then
        text=""
    fi

    # shellcheck disable=SC2034
    MD_HEADING_TEXT="$text"
    return 0
}

# yaml_escape - Escape a string for safe use in double-quoted YAML values.
#
# Handles backslashes and double quotes. Sufficient for single-line shell
# arguments (--title values); does not handle newlines or other YAML specials.
#
# Usage:
#   safe="$(yaml_escape "$title")"
#   echo "title: \"$safe\""
yaml_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    echo "$s"
}

# frontmatter_field - Extract a field from YAML frontmatter.
#
# Reads a markdown file's frontmatter block (between --- delimiters) and
# returns the value of the named field. Handles double-quoted values and
# reverses yaml_escape escaping.
#
# Usage:
#   title="$(frontmatter_field "title" "$file")"
frontmatter_field() {
    local field="$1" file="$2"
    local in_fm=false

    while IFS= read -r line; do
        if [[ "$line" == "---" ]]; then
            if [[ "$in_fm" == false ]]; then
                in_fm=true
                continue
            else
                return 1
            fi
        fi
        if [[ "$in_fm" == true ]] && [[ "$line" =~ ^${field}:[[:space:]]*(.*) ]]; then
            local value="${BASH_REMATCH[1]}"
            # Strip surrounding double quotes and reverse yaml_escape
            if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                value="${BASH_REMATCH[1]}"
                value="${value//\\\"/\"}"
                value="${value//\\\\/\\}"
            fi
            echo "$value"
            return 0
        fi
    done < "$file"

    return 1
}

# --- Retrieval metadata -------------------------------------------------

DEFAULT_FRESHNESS_DAYS=60
MAX_DISPLAYED_PROVENANCE_REFERENCES=5

# ttl_days - Map a frontmatter `ttl:` value to a number of days.
#
# Prints nothing for an unrecognized value, so callers can use the default.
ttl_days() {
    case "$1" in
        people|status)  echo 14 ;;
        process)        echo 60 ;;
        domain)         echo 180 ;;
        ''|*[!0-9]*)    echo "" ;;
        *)              echo "$1" ;;
    esac
}

# date_to_epoch - Convert YYYY-MM-DD to seconds since epoch.
#
# Works with both GNU date and BSD date. The caller decides whether an empty
# result means a missing or malformed date.
date_to_epoch() {
    local date_value="$1"

    date -u -d "$date_value" +%s 2>/dev/null && return
    date -u -j -f "%Y-%m-%d" "$date_value" +%s 2>/dev/null && return
    echo ""
}

# freshness_for_file - Populate shared freshness metadata for a content file.
#
# The globals are intentionally used instead of parsing a tab-delimited
# result. Frontmatter values are user content and can contain spaces or tabs.
# Pass an optional numeric threshold to implement stale --days. Tests and
# deterministic callers may set FRESHNESS_TODAY_EPOCH to a fixed UTC epoch.
#
# Outputs:
#   FRESHNESS_DATE_FIELD, FRESHNESS_DATE_VALUE, FRESHNESS_TTL_VALUE,
#   FRESHNESS_TTL_DAYS, FRESHNESS_STATUS, FRESHNESS_AGE_DAYS.
freshness_for_file() {
    local relpath="$1" file="$2" threshold_override="${3:-}"
    local raw_date date_value date_epoch ttl_raw threshold_days
    local today_epoch age_seconds

    FRESHNESS_DATE_FIELD=""
    FRESHNESS_DATE_VALUE=""
    FRESHNESS_TTL_VALUE=""
    FRESHNESS_TTL_DAYS=""
    FRESHNESS_STATUS="not-applicable"
    FRESHNESS_AGE_DAYS=""

    case "$relpath" in
        knowledge/*) FRESHNESS_DATE_FIELD="verified" ;;
        sources/*)   FRESHNESS_DATE_FIELD="synced" ;;
        *)           return 0 ;;
    esac

    raw_date="$(frontmatter_field "$FRESHNESS_DATE_FIELD" "$file" 2>/dev/null || true)"
    FRESHNESS_DATE_VALUE="$raw_date"

    ttl_raw="$(frontmatter_field ttl "$file" 2>/dev/null || true)"
    threshold_days="$(ttl_days "$ttl_raw")"
    if [[ -z "$threshold_days" ]]; then
        threshold_days="$DEFAULT_FRESHNESS_DAYS"
    fi
    FRESHNESS_TTL_DAYS="$threshold_days"
    if [[ -n "$ttl_raw" ]] && [[ -n "$(ttl_days "$ttl_raw")" ]]; then
        FRESHNESS_TTL_VALUE="$ttl_raw"
    else
        FRESHNESS_TTL_VALUE="default"
    fi

    if [[ -z "$raw_date" ]]; then
        FRESHNESS_STATUS="unknown"
        return 0
    fi

    date_value="${raw_date%T*}"
    date_epoch="$(date_to_epoch "$date_value")"
    if [[ -z "$date_epoch" ]]; then
        FRESHNESS_STATUS="invalid"
        return 0
    fi

    if [[ -n "$threshold_override" ]]; then
        threshold_days="$threshold_override"
        FRESHNESS_TTL_VALUE="override"
        FRESHNESS_TTL_DAYS="$threshold_days"
    fi

    today_epoch="${FRESHNESS_TODAY_EPOCH:-}"
    if [[ -z "$today_epoch" ]]; then
        today_epoch="$(date -u +%s)"
        FRESHNESS_TODAY_EPOCH="$today_epoch"
    fi

    age_seconds=$((today_epoch - date_epoch))
    FRESHNESS_AGE_DAYS=$((age_seconds / 86400))
    if (( age_seconds > threshold_days * 86400 )); then
        FRESHNESS_STATUS="stale"
    else
        FRESHNESS_STATUS="fresh"
    fi
}

# corpus_type_for_path - Classify a content-relative path for retrieval.
corpus_type_for_path() {
    case "$1" in
        knowledge/*)             echo "curated article" ;;
        sources/*)               echo "source document" ;;
        observations/pending/*)  echo "pending observation" ;;
        observations/archived/*) echo "archive" ;;
        questions/open/*)        echo "question" ;;
        questions/resolved/*)    echo "question" ;;
        questions/*)             echo "question" ;;
        *)                       echo "unknown" ;;
    esac
}

# provenance_for_file - Populate provenance metadata for a content record.
#
# `sources:` on a knowledge article is article-level evidence, not proof that
# every individual sentence came from every listed observation. This scope is
# exposed to structured consumers so they cannot mistake an article reference
# for claim-level citation.
provenance_for_file() {
    local relpath="$1" file="$2" line value in_frontmatter=false in_sources=false

    PROVENANCE_SCOPE="record"
    PROVENANCE_LABEL=""
    PROVENANCE_REFERENCES=()
    PROVENANCE_DISPLAY_REFERENCES=()
    PROVENANCE_REFERENCE_COUNT=0
    PROVENANCE_REFERENCES_TRUNCATED=false
    PROVENANCE_STATE=""
    PROVENANCE_DISPOSITION=""
    PROVENANCE_DESTINATION=""

    case "$relpath" in
        knowledge/*)
            PROVENANCE_SCOPE="article"
            PROVENANCE_LABEL="article-level references"
            ;;
        sources/*)
            PROVENANCE_SCOPE="document"
            PROVENANCE_LABEL="document-level reference"
            value="$(frontmatter_field canonical "$file" 2>/dev/null || true)"
            [[ -n "$value" ]] && PROVENANCE_REFERENCES+=("$value")
            ;;
        observations/pending/*)
            PROVENANCE_SCOPE="observation"
            PROVENANCE_LABEL="uncurated evidence"
            ;;
        observations/archived/*)
            PROVENANCE_SCOPE="archive"
            PROVENANCE_LABEL="archived evidence"
            ;;
        questions/open/*)
            PROVENANCE_SCOPE="question"
            PROVENANCE_LABEL="unresolved knowledge gap"
            PROVENANCE_STATE="open"
            ;;
        questions/resolved/*)
            PROVENANCE_SCOPE="question"
            PROVENANCE_LABEL="resolved question record"
            PROVENANCE_STATE="resolved"
            ;;
        questions/*)
            PROVENANCE_SCOPE="question"
            PROVENANCE_LABEL="question record"
            PROVENANCE_STATE="unknown"
            ;;
        *)
            PROVENANCE_SCOPE="record"
            ;;
    esac

    # Parse the simple YAML list used by the curation frontmatter without
    # loading the article body. List items remain separate even when they
    # contain spaces.
    while IFS= read -r line; do
        if [[ "$line" == "---" ]]; then
            if [[ "$in_frontmatter" == false ]]; then
                in_frontmatter=true
            else
                break
            fi
            continue
        fi
        [[ "$in_frontmatter" == true ]] || continue

        if [[ "$line" =~ ^sources:[[:space:]]*$ ]]; then
            in_sources=true
            continue
        fi
        if [[ "$in_sources" == true ]]; then
            if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+(.*)$ ]]; then
                value="${BASH_REMATCH[1]}"
                if [[ "$value" =~ ^\"(.*)\"$ ]]; then
                    value="${BASH_REMATCH[1]}"
                    value="${value//\\\"/\"}"
                    value="${value//\\\\/\\}"
                fi
                PROVENANCE_REFERENCES+=("$value")
                continue
            fi
            in_sources=false
        fi
    done < "$file"

    if [[ "$relpath" == observations/archived/* ]]; then
        PROVENANCE_DISPOSITION="$(frontmatter_field disposition "$file" 2>/dev/null || true)"
        PROVENANCE_DESTINATION="$(frontmatter_field destination "$file" 2>/dev/null || true)"
    fi

    PROVENANCE_REFERENCE_COUNT=${#PROVENANCE_REFERENCES[@]}
    local reference_index
    for reference_index in "${!PROVENANCE_REFERENCES[@]}"; do
        if (( reference_index >= MAX_DISPLAYED_PROVENANCE_REFERENCES )); then
            PROVENANCE_REFERENCES_TRUNCATED=true
            break
        fi
        PROVENANCE_DISPLAY_REFERENCES+=("${PROVENANCE_REFERENCES[$reference_index]}")
    done
}

# retrieval_metadata_for_file - Populate every field used by retrieval tools.
retrieval_metadata_for_file() {
    local relpath="$1" file="$2"

    RESULT_CORPUS="$(corpus_type_for_path "$relpath")"
    freshness_for_file "$relpath" "$file"
    provenance_for_file "$relpath" "$file"
}

# json_escape_value - Escape one shell value for use inside a JSON string.
#
# This preserves UTF-8 and escapes the JSON-significant characters plus the
# control characters that can occur in multiline Markdown.
json_escape_value() {
    awk '
    function escape(s,    i, c, out) {
        for (i = 1; i <= length(s); i++) {
            c = substr(s, i, 1)
            if (c == "\\") out = out "\\\\"
            else if (c == "\"") out = out "\\\""
            else if (c == "\t") out = out "\\t"
            else if (c == "\r") out = out "\\r"
            else if (c == "\b") out = out "\\b"
            else if (c == "\f") out = out "\\f"
            else out = out c
        }
        return out
    }
    { if (seen) printf "\\n"; printf "%s", escape($0); seen = 1 }
    '
}

# json_escape_file - Escape a text file while retaining its line breaks.
json_escape_file() {
    awk '
    function escape(s,    i, c, out) {
        for (i = 1; i <= length(s); i++) {
            c = substr(s, i, 1)
            if (c == "\\") out = out "\\\\"
            else if (c == "\"") out = out "\\\""
            else if (c == "\t") out = out "\\t"
            else if (c == "\r") out = out "\\r"
            else if (c == "\b") out = out "\\b"
            else if (c == "\f") out = out "\\f"
            else out = out c
        }
        return out
    }
    { if (seen) printf "\\n"; printf "%s", escape($0); seen = 1 }
    END { if (seen) printf "\\n" }
    ' "$1"
}

json_quote() {
    printf '"'
    printf '%s' "$1" | json_escape_value
    printf '"'
}

json_quote_file() {
    printf '"'
    json_escape_file "$1"
    printf '"'
}

json_nullable_string() {
    if [[ -n "$1" ]]; then
        json_quote "$1"
    else
        printf 'null'
    fi
}

json_references() {
    local reference first=true

    printf '['
    if [[ "${1:-}" == all ]]; then
        for reference in "${PROVENANCE_REFERENCES[@]}"; do
            if [[ "$first" == false ]]; then printf ','; fi
            json_quote "$reference"
            first=false
        done
    else
        for reference in "${PROVENANCE_DISPLAY_REFERENCES[@]}"; do
            if [[ "$first" == false ]]; then printf ','; fi
            json_quote "$reference"
            first=false
        done
    fi
    printf ']'
}

json_provenance() {
    local reference_mode="${1:-display}"
    local references_truncated="$PROVENANCE_REFERENCES_TRUNCATED"

    if [[ "$reference_mode" == all ]]; then
        references_truncated=false
    fi

    printf '{"scope":'
    json_quote "$PROVENANCE_SCOPE"
    printf ',"label":'
    json_nullable_string "$PROVENANCE_LABEL"
    printf ',"references":'
    json_references "$reference_mode"
    printf ',"reference_count":%d,"references_truncated":%s' \
        "$PROVENANCE_REFERENCE_COUNT" "$references_truncated"
    if [[ -n "$PROVENANCE_STATE" ]]; then
        printf ',"state":'
        json_quote "$PROVENANCE_STATE"
    fi
    if [[ -n "$PROVENANCE_DISPOSITION" ]]; then
        printf ',"disposition":'
        json_quote "$PROVENANCE_DISPOSITION"
    fi
    if [[ -n "$PROVENANCE_DESTINATION" ]]; then
        printf ',"destination":'
        json_quote "$PROVENANCE_DESTINATION"
    fi
    printf '}'
}

json_freshness() {
    printf '{"field":'
    json_nullable_string "$FRESHNESS_DATE_FIELD"
    printf ',"value":'
    json_nullable_string "$FRESHNESS_DATE_VALUE"
    printf ',"ttl":'
    json_nullable_string "$FRESHNESS_TTL_VALUE"
    printf ',"ttl_days":'
    if [[ -n "$FRESHNESS_TTL_DAYS" ]]; then
        printf '%s' "$FRESHNESS_TTL_DAYS"
    else
        printf 'null'
    fi
    printf ',"status":'
    json_quote "$FRESHNESS_STATUS"
    printf ',"age_days":'
    if [[ -n "$FRESHNESS_AGE_DAYS" ]]; then
        printf '%s' "$FRESHNESS_AGE_DAYS"
    else
        printf 'null'
    fi
    printf '}'
}

freshness_metadata_text() {
    local date_display ttl_display

    if [[ -n "$FRESHNESS_DATE_FIELD" ]]; then
        date_display="${FRESHNESS_DATE_VALUE:-unknown}"
        ttl_display="${FRESHNESS_TTL_DAYS}d"
        printf '%s; %s=%s; ttl=%s; freshness=%s' \
            "$RESULT_CORPUS" "$FRESHNESS_DATE_FIELD" "$date_display" \
            "$ttl_display" "$FRESHNESS_STATUS"
    else
        printf '%s' "$RESULT_CORPUS"
        [[ -n "$PROVENANCE_LABEL" ]] && printf '; %s' "$PROVENANCE_LABEL"
    fi
    return 0
}

retrieval_metadata_text() {
    local refs_display="" reference hidden_reference_count

    freshness_metadata_text

    if ((${#PROVENANCE_DISPLAY_REFERENCES[@]} > 0)); then
        for reference in "${PROVENANCE_DISPLAY_REFERENCES[@]}"; do
            if [[ -n "$refs_display" ]]; then refs_display+=", "; fi
            refs_display+="$reference"
        done
        if [[ "$PROVENANCE_REFERENCES_TRUNCATED" == true ]]; then
            hidden_reference_count=$((PROVENANCE_REFERENCE_COUNT - MAX_DISPLAYED_PROVENANCE_REFERENCES))
            printf '; refs=%s (+%d more; %s)' "$refs_display" \
                "$hidden_reference_count" "$PROVENANCE_SCOPE"
        else
            printf '; refs=%s (%s)' "$refs_display" "$PROVENANCE_SCOPE"
        fi
    elif [[ -n "$PROVENANCE_LABEL" ]]; then
        printf '; refs=none (%s)' "$PROVENANCE_SCOPE"
    fi

    [[ -n "$PROVENANCE_STATE" ]] && printf '; state=%s' "$PROVENANCE_STATE"
    [[ -n "$PROVENANCE_DISPOSITION" ]] && \
        printf '; disposition=%s' "$PROVENANCE_DISPOSITION"
    [[ -n "$PROVENANCE_DESTINATION" ]] && \
        printf '; destination=%s' "$PROVENANCE_DESTINATION"
    return 0
}

provenance_metadata_text() {
    local refs_display="" reference hidden_reference_count

    if ((${#PROVENANCE_DISPLAY_REFERENCES[@]} > 0)); then
        for reference in "${PROVENANCE_DISPLAY_REFERENCES[@]}"; do
            if [[ -n "$refs_display" ]]; then refs_display+=", "; fi
            refs_display+="$reference"
        done
        if [[ "$PROVENANCE_REFERENCES_TRUNCATED" == true ]]; then
            hidden_reference_count=$((PROVENANCE_REFERENCE_COUNT - MAX_DISPLAYED_PROVENANCE_REFERENCES))
            printf 'refs=%s (+%d more; %s)' "$refs_display" \
                "$hidden_reference_count" "$PROVENANCE_SCOPE"
        else
            printf 'refs=%s (%s)' "$refs_display" "$PROVENANCE_SCOPE"
        fi
    else
        printf 'refs=none (%s)' "$PROVENANCE_SCOPE"
    fi

    [[ -n "$PROVENANCE_STATE" ]] && printf '; state=%s' "$PROVENANCE_STATE"
    [[ -n "$PROVENANCE_DISPOSITION" ]] && \
        printf '; disposition=%s' "$PROVENANCE_DISPOSITION"
    [[ -n "$PROVENANCE_DESTINATION" ]] && \
        printf '; destination=%s' "$PROVENANCE_DESTINATION"
    return 0
}

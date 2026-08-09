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

# resolve_path - Normalize a path to be relative to the content root.
#
# Handles: absolute paths, content-relative paths, knowledge/-relative paths,
# and bare filenames (searched under knowledge/ only).
#
# Prints the resolved content-relative path on success.
# Returns 1 if not found; prints error to stderr if ambiguous.
#
# Usage:
#   resolved="$(resolve_path "$path")" && VAR="$CONTENT_DIR/$resolved"
resolve_path() {
    local input="$1"

    # Strip absolute content root prefix
    input="${input#"$CONTENT_DIR/"}"

    # Exists relative to content root
    if [[ -e "$CONTENT_DIR/$input" ]]; then
        echo "$input"
        return 0
    fi

    # Try prepending knowledge/
    if [[ "$input" != knowledge/* ]] && [[ "$input" != sources/* ]] \
        && [[ "$input" != observations/* ]] && [[ "$input" != questions/* ]]; then
        if [[ -e "$CONTENT_DIR/knowledge/$input" ]]; then
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
        echo "${matches#"$CONTENT_DIR/"}"
        return 0
    fi

    echo "Ambiguous match for '$base' — $count files found:" >&2
    echo "$matches" | sed "s|^$CONTENT_DIR/|  |" >&2
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
locked_commit() {
    local message="$1"
    shift

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

    local rc=0
    (
        cd "$CONTENT_DIR"
        for p in "$@"; do
            git add "$p"
        done
        git commit -q -m "$message" -- "$@"
    ) || rc=$?

    rm -rf "$lockdir" 2>/dev/null || true
    trap - EXIT

    if (( rc != 0 )); then
        echo "locked_commit: commit failed ($rc) for: $message" >&2
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

# ensure_session_dir - Create the session directory, private, and verify it.
#
# Returns 1 if the directory cannot be created or is owned by someone
# else, so callers can skip capture instead of writing prompts somewhere
# another user can read.
ensure_session_dir() {
    local dir="$1"

    mkdir -p -m 700 "$dir" 2>/dev/null || return 1
    [[ -d "$dir" ]] || return 1
    [[ -O "$dir" ]] || return 1

    # A pre-existing directory keeps its old mode; tighten it.
    chmod 700 "$dir" 2>/dev/null || true
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
MD_HEADING_LEVEL=0
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

    MD_HEADING_LEVEL=${#BASH_REMATCH[1]}
    MD_HEADING_TEXT="${BASH_REMATCH[2]}"
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

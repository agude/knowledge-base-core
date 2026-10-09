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

# question_terms - Convert a natural-language question into deterministic
# literal search terms, one per output line.
#
# This is intentionally lexical rather than semantic. Identifiers, paths,
# flags, numbers, dates, negation, and temporal words remain searchable. The
# stopword list removes only grammatical scaffolding; callers must reject an
# empty result instead of turning it into an unbounded search.
question_terms() {
    local question="$1"

    printf '%s' "$question" | awk '
    BEGIN {
        quote_open = 0
        stopwords = "a an and are as at be but by can could did do does for from had has have how i if in is it its me my of on or our please should that the their them there these they this to use was were what when where which who why will with would you your"
        count = split(stopwords, stopword_list, /[[:space:]]+/)
        for (i = 1; i <= count; i++) stop[stopword_list[i]] = 1
    }
    {
        text = tolower($0)
        gsub(/[^[:alnum:]_\/.:@+\-\047]/, " ", text)
        word_count = split(text, words, /[[:space:]]+/)
        for (i = 1; i <= word_count; i++) {
            word = words[i]
            if (word == "") continue
            if (word !~ /^\// && word !~ /^-/) {
                sub(/^[+:]+/, "", word)
                sub(/[+:]+$/, "", word)
            }
            # A final period is normally sentence punctuation. Preserve
            # meaningful periods inside identifiers and paths, including
            # dotted hostnames and version numbers.
            if (word !~ /\/$/) sub(/\.+$/, "", word)
            # Strip quote boundaries across tokens; contractions stay searchable.
            if (word ~ /^\047/) {
                sub(/^\047+/, "", word)
                quote_open = 1
            }
            if (quote_open && word ~ /\047$/) {
                sub(/\047+$/, "", word)
                quote_open = 0
            }
            if (word != "" && !stop[word] && !seen[word]) {
                print word
                seen[word] = 1
            }
        }
    }'
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

# parse_nonnegative_decimal - Validate and normalize a decimal integer.
#
# Bash treats an integer with a leading zero as octal. Normalize the value
# before using it in arithmetic, and reject values that cannot fit in the
# shell's signed integer range.
parse_nonnegative_decimal() {
    local option="$1" value="$2" normalized parsed

    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
        echo "Error: $option takes a non-negative number" >&2
        return 1
    fi

    normalized="${value#"${value%%[!0]*}"}"
    [[ -n "$normalized" ]] || normalized=0
    parsed="$(LC_ALL=C printf '%d' "$normalized" 2>/dev/null)" || {
        echo "Error: $option exceeds the supported integer range" >&2
        return 1
    }
    if [[ "$parsed" != "$normalized" ]]; then
        echo "Error: $option exceeds the supported integer range" >&2
        return 1
    fi

    printf '%s\n' "$normalized"
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
# KNOWLEDGE_LOCK_WAIT sets how many seconds acquire_lock waits for another
# writer (default 30). An adapter whose host gives a hook only a few
# seconds lowers it so a held lock fails inside that budget instead of the
# host killing the hook mid-write.
#
# Usage:
#   locked_commit "message" path1 [path2 ...]
acquire_lock() {
    local lockdir="$CONTENT_DIR/.observe.lock"
    local pidfile="$lockdir/pid"
    local wait waited=0

    wait="$(parse_nonnegative_decimal KNOWLEDGE_LOCK_WAIT "${KNOWLEDGE_LOCK_WAIT:-30}")" \
        || return 1

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
        if (( waited >= wait )); then
            echo "Could not acquire lock" >&2
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
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
    commit_paths "$message" "$@" || rc=$?

    release_lock
    return $rc
}

# commit_paths - Commit only the named paths. The caller must hold the lock.
#
# For a caller that must take the lock before writing the files it commits,
# so that a lock timeout leaves nothing behind.
#
# Usage:
#   commit_paths "message" path1 [path2 ...]
commit_paths() {
    local message="$1"
    shift

    local rc=0
    (
        cd "$CONTENT_DIR"
        for p in "$@"; do
            git add "$p"
        done
        git commit -q -m "$message" -- "$@"
    ) || rc=$?

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

# session_initialization_path - Return the durable initialization marker.
#
# Hosts such as Codex run each lifecycle hook in a fresh process, so an
# enabled environment variable cannot survive a swept buffer. Keep the
# initialization decision beside the session buffer instead.
session_initialization_path() {
    local dir="$1" id="$2"

    [[ "$id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 1
    printf '%s/session-%s.initialized\n' "$dir" "$id"
}

session_mark_initialized() {
    local dir="$1" id="$2" marker

    ensure_session_dir "$dir" || return 1
    marker="$(session_initialization_path "$dir" "$id")" || return 1
    touch "$marker" 2>/dev/null || return 1
    chmod 600 "$marker" 2>/dev/null || true
}

session_is_initialized() {
    local dir="$1" id="$2" marker

    marker="$(session_initialization_path "$dir" "$id")" || return 1
    [[ -f "$marker" && ! -L "$marker" && -O "$marker" ]]
}

# Clear only markers derived from the private session-buffer path. Arbitrary
# files passed to session-flush must never select a neighboring state file.
session_clear_initialization_for_file() {
    local dir file_name id marker
    dir="$(session_dir)"
    file_name="${1##*/}"

    case "$1" in
        "$dir"/session-*.jsonl) ;;
        *) return 0 ;;
    esac

    id="${file_name#session-}"
    id="${id%.jsonl}"
    marker="$(session_initialization_path "$dir" "$id")" || return 0
    rm -f -- "$marker"
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
# Recreate only when session-start initialized capture for this session: it
# sets KNOWLEDGE_OBSERVE=1, provides KNOWLEDGE_SESSION_FILE, or leaves the
# durable marker used by hosts whose hook processes do not share environment.
# An unset value alone still means that capture was never initialized.
#
# Prints the path; returns 2 for an uninitialized session, 1 for a failure.
session_buffer_path() {
    local dir="$1" id="$2"
    local file

    file="$(session_file_path "$dir" "$id")" || {
        echo "session buffer: invalid session ID" >&2
        return 1
    }

    if [[ -f "$file" ]]; then
        echo "$file"
        return 0
    fi

    if [[ "${KNOWLEDGE_OBSERVE:-}" != "1" ]] \
        && [[ -z "${KNOWLEDGE_SESSION_FILE:-}" ]] \
        && ! session_is_initialized "$dir" "$id"; then
        return 2
    fi

    ensure_session_dir "$dir" || {
        echo "session buffer: cannot create session directory $dir" >&2
        return 1
    }
    touch "$file" 2>/dev/null || {
        echo "session buffer: cannot create $file" >&2
        return 1
    }
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
# Numeric days are decimal and must fit when converted to seconds.
# Prints nothing for an unrecognized or unsupported value.
ttl_days() {
    local days
    case "$1" in
        people|status)  echo 14 ;;
        process)        echo 60 ;;
        domain)         echo 180 ;;
        ''|*[!0-9]*)    echo "" ;;
        *)
            days="$(parse_nonnegative_decimal ttl "$1" 2>/dev/null)" || return 0
            # The largest day count whose seconds fit in a signed 64-bit integer.
            if (( days <= 106751991167300 )); then
                printf '%s\n' "$days"
            fi
            ;;
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

# timestamp_to_epoch - Convert a complete ISO timestamp to epoch seconds.
#
# Batch selection uses observation creation time, not only its calendar date.
# Keep date-only values supported for older frontmatter and return an empty
# value when a timestamp cannot be parsed.
timestamp_to_epoch() {
    local timestamp="$1"

    if [[ "$timestamp" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        date_to_epoch "$timestamp"
        return 0
    fi
    date -u -d "$timestamp" +%s 2>/dev/null && return 0
    date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$timestamp" +%s 2>/dev/null && return 0
    date -u -j -f "%Y-%m-%dT%H:%M:%S%z" "$timestamp" +%s 2>/dev/null && return 0
    echo ""
}

# byte_size - Return a file's byte count across GNU and BSD stat.
byte_size() {
    local file="$1" size

    if size="$(stat -c '%s' "$file" 2>/dev/null)" && [[ "$size" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$size"
    elif size="$(stat -f '%z' "$file" 2>/dev/null)" && [[ "$size" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$size"
    else
        LC_ALL=C wc -c < "$file" | awk '{print $1}'
    fi
}

byte_count_text() {
    local LC_ALL=C
    printf '%s\n' "${#1}"
}

# Populate an age-ordered selection for preview or batch creation. The batch
# caller holds the content lock; previews are read-only snapshots.
select_pending_files() {
    local directory="$1" max_bytes="${2:-}" path created epoch size name order_file
    PENDING_SELECTION_FILES=()
    PENDING_SELECTION_SIZES=()
    PENDING_SELECTION_SKIPPED=()
    PENDING_SELECTION_BYTES=0
    [[ -d "$directory" ]] || return 0
    order_file="$(mktemp)" || return 1
    while IFS= read -r -d '' path; do
        created="$(frontmatter_field created "$path" 2>/dev/null || true)"
        epoch="$(timestamp_to_epoch "$created")"
        if [[ -n "$epoch" ]]; then
            printf '0\t%020d\t%s\0' "$epoch" "$path" >> "$order_file"
        else
            printf '1\t0\t%s\0' "$path" >> "$order_file"
        fi
    done < <(find "$directory" -maxdepth 1 -name '*.md' -type f -print0)
    if ! LC_ALL=C sort -z -t $'\t' -k1,1n -k2,2n -k3,3 -o "$order_file" "$order_file"; then
        rm -f "$order_file"
        return 1
    fi
    # shellcheck disable=SC2094  # Failure removes only the disposable input.
    while IFS=$'\t' read -r -d '' _ _ path; do
        if ! size="$(byte_size "$path")"; then
            rm -f "$order_file"
            return 1
        fi
        name="${path##*/}"
        if [[ -z "$max_bytes" ]] || (( PENDING_SELECTION_BYTES + size <= max_bytes )); then
            PENDING_SELECTION_FILES+=("$path")
            PENDING_SELECTION_SIZES+=("$name:$size")
            PENDING_SELECTION_BYTES=$((PENDING_SELECTION_BYTES + size))
        else
            PENDING_SELECTION_SKIPPED+=("$name:$size")
        fi
    done < "$order_file"
    rm -f "$order_file"
}

# sha256_file - Print a file's SHA-256 digest using an available utility.
sha256_file() {
    local file="$1"

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$file" | awk '{print $1}'
        return 0
    fi
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$file" | awk '{print $1}'
        return 0
    fi
    echo "Error: SHA-256 utility is unavailable" >&2
    return 1
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
    FRESHNESS_TTL_RAW=""
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
    FRESHNESS_TTL_RAW="$ttl_raw"
    threshold_days="$(ttl_days "$ttl_raw")"
    if [[ -z "$threshold_days" && "$ttl_raw" =~ ^[0-9]+$ ]]; then
        FRESHNESS_TTL_VALUE="$ttl_raw"
        FRESHNESS_STATUS=invalid
        return 0
    fi
    FRESHNESS_TTL_VALUE="$ttl_raw"
    if [[ -z "$threshold_days" ]]; then
        threshold_days="$DEFAULT_FRESHNESS_DAYS"
        FRESHNESS_TTL_VALUE="default"
    fi
    FRESHNESS_TTL_DAYS="$threshold_days"

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

# conflict_status_for_file - Populate the explicit conflict metadata.
#
# Knowledge articles may set `conflict: unresolved` while claims are still
# being compared. This status is separate from freshness: an article can be
# recently verified and still contain an unresolved contradiction.
conflict_status_for_file() {
    local relpath="$1" file="$2"

    CONFLICT_STATUS="none"
    [[ "$relpath" == knowledge/* ]] || return 0

    CONFLICT_STATUS="$(frontmatter_field conflict "$file" 2>/dev/null || true)"
    [[ -n "$CONFLICT_STATUS" ]] || CONFLICT_STATUS="none"
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
    local relpath="$1" file="$2" selector="${3:-}"

    if [[ -n "$selector" ]]; then
        section_metadata_for_file "$relpath" "$file" "$selector"
        return
    fi
    if [[ "${SECTION_METADATA_CACHE_ENABLED:-false}" == true &&
        -n "${SECTION_META_CACHE_READY[$relpath]:-}" ]]; then
        section_metadata_cache_restore "$relpath" --article
    else
        section_metadata_load_article "$relpath" "$file"
        if [[ "${SECTION_METADATA_CACHE_ENABLED:-false}" == true ]]; then
            section_metadata_cache_store "$relpath" article
        fi
    fi
    section_metadata_select ""
}

# Section metadata uses a small HTML-comment convention immediately after an
# H2 or H3 heading:
#
#   <!-- kb-section: verified=2026-09-01; ttl=domain; effective=2026-08-01; status=current; supersedes=2; sources=observations/archived/example.md -->
#
# Values not present in the comment inherit from article frontmatter. The
# `supersedes` belongs on the newer section and points backward to the older
# section's numeric locator. The older section uses `status=superseded` and
# does not point forward. The comment is ignored inside fenced examples.
# These arrays are shared by
# section, search, stale, and lint so duplicate headings use numeric locators
# rather than heading text.
declare -A SECTION_META_VERIFIED=()
declare -A SECTION_META_TTL=()
declare -A SECTION_META_EFFECTIVE=()
declare -A SECTION_META_STATUS=()
declare -A SECTION_META_SUPERSEDES=()
declare -A SECTION_META_SCOPE=()
declare -A SECTION_META_SOURCE_SCOPE=()
declare -A SECTION_META_SOURCES=()
declare -A SECTION_META_HEADING=()
declare -A SECTION_META_VALID=()
declare -A SECTION_META_INVALID=()
declare -A SECTION_META_FIELD_SCOPE=()
SECTION_META_ARTICLE_PROVENANCE_REFERENCES=()
SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES=()
declare -A SECTION_METADATA_FIELD_SCOPE=()

# Search can revisit a file after parsing another file. Keep each parsed
# metadata set isolated so selecting a later result cannot read another file's
# article or section fields.
declare -A SECTION_META_CACHE_READY=()
# Entries contain article state first, then sections when a selector needs them.
declare -A SECTION_META_CACHE_LOCATORS=()
declare -A SECTION_META_CACHE_VALUES=()
declare -A SECTION_META_CACHE_FIELD_SCOPES=()
declare -A SECTION_META_CACHE_ARTICLE_VALUES=()
declare -A SECTION_META_CACHE_ARTICLE_REFERENCE_INDICES=()
declare -A SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCE_INDICES=()
declare -A SECTION_META_CACHE_ARTICLE_REFERENCES=()
declare -A SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCES=()
SECTION_METADATA_CACHE_SEPARATOR=$'\x1f'

# Keep cache fields and their live variables together. The cache store and
# restore paths consume these definitions so adding a metadata field updates
# both directions in one place.
SECTION_METADATA_CACHE_SECTION_FIELD_MAP=(
    verified:SECTION_META_VERIFIED
    ttl:SECTION_META_TTL
    effective:SECTION_META_EFFECTIVE
    status:SECTION_META_STATUS
    supersedes:SECTION_META_SUPERSEDES
    scope:SECTION_META_SCOPE
    source_scope:SECTION_META_SOURCE_SCOPE
    sources:SECTION_META_SOURCES
    heading:SECTION_META_HEADING
    valid:SECTION_META_VALID
    invalid:SECTION_META_INVALID
)
SECTION_METADATA_CACHE_SECTION_SCOPE_FIELDS=(
    verified ttl effective status supersedes sources
)
SECTION_METADATA_CACHE_ARTICLE_FIELD_MAP=(
    verified:SECTION_META_ARTICLE_VERIFIED
    ttl:SECTION_META_ARTICLE_TTL
    effective:SECTION_META_ARTICLE_EFFECTIVE
    status:SECTION_META_ARTICLE_STATUS
    supersedes:SECTION_META_ARTICLE_SUPERSEDES
    sources:SECTION_META_ARTICLE_SOURCES
    source_scope:SECTION_META_ARTICLE_SOURCE_SCOPE
    freshness_date_field:SECTION_META_ARTICLE_FRESHNESS_DATE_FIELD
    freshness_date_value:SECTION_META_ARTICLE_FRESHNESS_DATE_VALUE
    freshness_ttl_value:SECTION_META_ARTICLE_FRESHNESS_TTL_VALUE
    freshness_ttl_days:SECTION_META_ARTICLE_FRESHNESS_TTL_DAYS
    freshness_status:SECTION_META_ARTICLE_FRESHNESS_STATUS
    freshness_age_days:SECTION_META_ARTICLE_FRESHNESS_AGE_DAYS
    freshness_conflict_status:SECTION_META_ARTICLE_CONFLICT_STATUS
    corpus:SECTION_META_ARTICLE_CORPUS
    provenance_disposition:SECTION_META_ARTICLE_PROVENANCE_DISPOSITION
    provenance_destination:SECTION_META_ARTICLE_PROVENANCE_DESTINATION
    provenance_state:SECTION_META_ARTICLE_PROVENANCE_STATE
    provenance_scope:SECTION_META_ARTICLE_PROVENANCE_SCOPE
    provenance_label:SECTION_META_ARTICLE_PROVENANCE_LABEL
    provenance_reference_count:SECTION_META_ARTICLE_PROVENANCE_REFERENCE_COUNT
    provenance_references_truncated:SECTION_META_ARTICLE_PROVENANCE_REFERENCES_TRUNCATED
)

section_metadata_trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

section_metadata_add_invalid() {
    local locator="$1" detail="$2"
    SECTION_META_VALID["$locator"]=false
    if [[ -n "${SECTION_META_INVALID[$locator]:-}" ]]; then
        SECTION_META_INVALID["$locator"]+="; "
    fi
    SECTION_META_INVALID["$locator"]+="$detail"
}

section_metadata_apply() {
    local locator="$1" raw="$2" base_locator="${3:-}"
    local verified effective ttl status supersedes sources key value pair
    local explicit=false source_scope canonical_key previous_value field
    declare -A seen_fields=()

    if [[ -n "$base_locator" && -n "${SECTION_META_STATUS[$base_locator]+present}" ]]; then
        verified="${SECTION_META_VERIFIED[$base_locator]}"
        ttl="${SECTION_META_TTL[$base_locator]}"
        effective="${SECTION_META_EFFECTIVE[$base_locator]}"
        status="${SECTION_META_STATUS[$base_locator]}"
        supersedes="${SECTION_META_SUPERSEDES[$base_locator]}"
        sources="${SECTION_META_SOURCES[$base_locator]}"
        source_scope="${SECTION_META_SOURCE_SCOPE[$base_locator]}"
        for field in verified ttl effective status supersedes sources; do
            SECTION_META_FIELD_SCOPE["$locator:$field"]="${SECTION_META_FIELD_SCOPE[$base_locator:$field]}"
        done
        [[ "${SECTION_META_SCOPE[$base_locator]}" == section ]] && explicit=true
        SECTION_META_VALID["$locator"]="${SECTION_META_VALID[$base_locator]}"
        SECTION_META_INVALID["$locator"]="${SECTION_META_INVALID[$base_locator]}"
    else
        verified="$SECTION_META_ARTICLE_VERIFIED"
        ttl="$SECTION_META_ARTICLE_TTL"
        effective="$SECTION_META_ARTICLE_EFFECTIVE"
        status="$SECTION_META_ARTICLE_STATUS"
        supersedes="$SECTION_META_ARTICLE_SUPERSEDES"
        sources="$SECTION_META_ARTICLE_SOURCES"
        source_scope="$SECTION_META_ARTICLE_SOURCE_SCOPE"
        for field in verified ttl effective status supersedes sources; do
            SECTION_META_FIELD_SCOPE["$locator:$field"]=article
        done
        SECTION_META_VALID["$locator"]=true
        SECTION_META_INVALID["$locator"]=""
    fi

    while IFS= read -r pair; do
        [[ -n "$pair" ]] || continue
        pair="$(section_metadata_trim "$pair")"
        if [[ "$pair" == *"="* ]]; then
            key="${pair%%=*}"
            value="${pair#*=}"
        elif [[ "$pair" == *":"* ]]; then
            key="${pair%%:*}"
            value="${pair#*:}"
        else
            section_metadata_add_invalid "$locator" "malformed field '$pair'"
            continue
        fi
        key="$(section_metadata_trim "$key")"
        value="$(section_metadata_trim "$value")"
        case "$key" in
            verified|synced) canonical_key=verified ;;
            ttl|effective|status|supersedes|sources) canonical_key="$key" ;;
            *)
                section_metadata_add_invalid "$locator" "unknown field '$key'"
                continue
                ;;
        esac

        if [[ -n "${seen_fields[$canonical_key]+present}" ]]; then
            previous_value="${seen_fields[$canonical_key]}"
            if [[ "$previous_value" != "$value" ]]; then
                section_metadata_add_invalid "$locator" \
                    "conflicting values for field '$canonical_key': '$previous_value' and '$value'"
            fi
        else
            seen_fields["$canonical_key"]="$value"
        fi

        case "$canonical_key" in
            verified) verified="$value" ;;
            ttl) ttl="$value" ;;
            effective) effective="$value" ;;
            status) status="$value" ;;
            supersedes) supersedes="$value" ;;
            sources) sources="$value"; source_scope=section ;;
        esac
        explicit=true
        SECTION_META_FIELD_SCOPE["$locator:$canonical_key"]=section
    done < <(printf '%s\n' "$raw" | tr ';' '\n')

    if [[ -n "$verified" && ! "$verified" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        section_metadata_add_invalid "$locator" "invalid verification date '$verified'"
    elif [[ -n "$verified" ]] && [[ -z "$(date_to_epoch "$verified")" ]]; then
        section_metadata_add_invalid "$locator" "invalid verification date '$verified'"
    fi
    if [[ -n "$effective" && ! "$effective" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        section_metadata_add_invalid "$locator" "invalid effective date '$effective'"
    elif [[ -n "$effective" ]] && [[ -z "$(date_to_epoch "$effective")" ]]; then
        section_metadata_add_invalid "$locator" "invalid effective date '$effective'"
    fi
    if [[ -n "$ttl" ]] && [[ -z "$(ttl_days "$ttl")" ]]; then
        section_metadata_add_invalid "$locator" "invalid ttl '$ttl'"
    fi
    case "$status" in
        current|superseded|unresolved) ;;
        *) section_metadata_add_invalid "$locator" "invalid status '$status'" ;;
    esac

    SECTION_META_VERIFIED["$locator"]="$verified"
    SECTION_META_TTL["$locator"]="$ttl"
    SECTION_META_EFFECTIVE["$locator"]="$effective"
    SECTION_META_STATUS["$locator"]="$status"
    SECTION_META_SUPERSEDES["$locator"]="$supersedes"
    SECTION_META_SCOPE["$locator"]="$([[ "$explicit" == true ]] && echo section || echo article)"
    SECTION_META_SOURCE_SCOPE["$locator"]="$source_scope"
    SECTION_META_SOURCES["$locator"]="$sources"
    SECTION_META_HEADING["$locator"]="${SECTION_META_HEADING[$locator]:-}"
}

section_metadata_load_article() {
    local relpath="$1" file="$2" field

    RESULT_CORPUS="$(corpus_type_for_path "$relpath")"
    freshness_for_file "$relpath" "$file"
    conflict_status_for_file "$relpath" "$file"
    provenance_for_file "$relpath" "$file"

    SECTION_META_ARTICLE_VERIFIED="$FRESHNESS_DATE_VALUE"
    SECTION_META_ARTICLE_TTL="$FRESHNESS_TTL_RAW"
    SECTION_META_ARTICLE_EFFECTIVE=""
    SECTION_META_ARTICLE_STATUS=current
    SECTION_META_ARTICLE_SUPERSEDES=""
    SECTION_META_ARTICLE_SOURCES=""
    for field in "${PROVENANCE_REFERENCES[@]}"; do
        [[ -n "$SECTION_META_ARTICLE_SOURCES" ]] && SECTION_META_ARTICLE_SOURCES+=', '
        SECTION_META_ARTICLE_SOURCES+="$field"
    done
    SECTION_META_ARTICLE_SOURCE_SCOPE=article

    SECTION_META_ARTICLE_FRESHNESS_DATE_FIELD="${FRESHNESS_DATE_FIELD:-}"
    SECTION_META_ARTICLE_FRESHNESS_DATE_VALUE="${FRESHNESS_DATE_VALUE:-}"
    SECTION_META_ARTICLE_FRESHNESS_TTL_VALUE="${FRESHNESS_TTL_VALUE:-}"
    SECTION_META_ARTICLE_FRESHNESS_TTL_DAYS="${FRESHNESS_TTL_DAYS:-}"
    SECTION_META_ARTICLE_FRESHNESS_STATUS="${FRESHNESS_STATUS:-not-applicable}"
    SECTION_META_ARTICLE_FRESHNESS_AGE_DAYS="${FRESHNESS_AGE_DAYS:-}"
    SECTION_META_ARTICLE_CONFLICT_STATUS="${CONFLICT_STATUS:-none}"
    SECTION_META_ARTICLE_PROVENANCE_SCOPE="$PROVENANCE_SCOPE"
    SECTION_META_ARTICLE_PROVENANCE_LABEL="$PROVENANCE_LABEL"
    SECTION_META_ARTICLE_PROVENANCE_REFERENCES=("${PROVENANCE_REFERENCES[@]}")
    SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES=("${PROVENANCE_DISPLAY_REFERENCES[@]}")
    SECTION_META_ARTICLE_PROVENANCE_REFERENCE_COUNT="$PROVENANCE_REFERENCE_COUNT"
    SECTION_META_ARTICLE_PROVENANCE_REFERENCES_TRUNCATED="$PROVENANCE_REFERENCES_TRUNCATED"

    SECTION_META_ARTICLE_CORPUS="$RESULT_CORPUS"
    SECTION_META_ARTICLE_PROVENANCE_DISPOSITION="$PROVENANCE_DISPOSITION"
    SECTION_META_ARTICLE_PROVENANCE_DESTINATION="$PROVENANCE_DESTINATION"
    SECTION_META_ARTICLE_PROVENANCE_STATE="$PROVENANCE_STATE"
}

section_metadata_for_file() {
    local relpath="$1" file="$2" selector="${3:-}"
    local line locator="" in_metadata=false metadata_buffer=""
    local h2_count=0 h3_count=0 level heading parent_locator
    local metadata_allowed=false misplaced_before_heading=false metadata_placement_allowed=false
    local metadata_start='^[[:blank:]]*<!-- kb-section:'

    if [[ "${SECTION_METADATA_CACHE_ENABLED:-false}" == true &&
        "${SECTION_META_CACHE_READY[$relpath]:-}" == sections ]]; then
        section_metadata_cache_restore "$relpath" "$selector"
        section_metadata_select "$selector"
        return 0
    fi

    if [[ "${SECTION_METADATA_CACHE_ENABLED:-false}" == true &&
        "${SECTION_META_CACHE_READY[$relpath]:-}" == article ]]; then
        section_metadata_cache_restore "$relpath" --article
    else
        section_metadata_load_article "$relpath" "$file"
    fi

    SECTION_METADATA_RELPATH="$relpath"
    SECTION_META_VERIFIED=()
    SECTION_META_TTL=()
    SECTION_META_EFFECTIVE=()
    SECTION_META_STATUS=()
    SECTION_META_SUPERSEDES=()
    SECTION_META_SCOPE=()
    SECTION_META_SOURCE_SCOPE=()
    SECTION_META_SOURCES=()
    SECTION_META_HEADING=()
    SECTION_META_VALID=()
    SECTION_META_INVALID=()
    SECTION_META_FIELD_SCOPE=()

    # Freshness already read article dates and TTLs. Other defaults matter only
    # when a section is selected; observation/question freshness has no dates.
    if [[ -z "$SECTION_META_ARTICLE_FRESHNESS_DATE_FIELD" ]]; then
        SECTION_META_ARTICLE_VERIFIED="$(frontmatter_field verified "$file" 2>/dev/null || true)"
        SECTION_META_ARTICLE_TTL="$(frontmatter_field ttl "$file" 2>/dev/null || true)"
    fi
    SECTION_META_ARTICLE_EFFECTIVE="$(frontmatter_field effective "$file" 2>/dev/null || true)"
    SECTION_META_ARTICLE_STATUS="$(frontmatter_field status "$file" 2>/dev/null || true)"
    [[ -n "$SECTION_META_ARTICLE_STATUS" ]] || SECTION_META_ARTICLE_STATUS=current
    SECTION_META_ARTICLE_SUPERSEDES="$(frontmatter_field supersedes "$file" 2>/dev/null || true)"

    md_heading_reset
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$in_metadata" == false ]]; then
            if md_heading "$line"; then
                level="$MD_HEADING_LEVEL"
                heading="$MD_HEADING_TEXT"
                if (( level == 2 )); then
                    h2_count=$((h2_count + 1)); h3_count=0
                    locator="$h2_count"
                    parent_locator=""
                elif (( level == 3 )); then
                    h3_count=$((h3_count + 1))
                    locator="$h2_count.$h3_count"
                    parent_locator="$h2_count"
                else
                    metadata_allowed=false
                    continue
                fi
                SECTION_META_HEADING["$locator"]="$heading"
                section_metadata_apply "$locator" "" "$parent_locator"
                if [[ "$misplaced_before_heading" == true ]]; then
                    section_metadata_add_invalid "$locator" "invalid section metadata placement before first section"
                    misplaced_before_heading=false
                fi
                metadata_allowed=true
                continue
            fi
            if [[ "$MD_FENCE_OPEN" == true ]]; then
                metadata_allowed=false
                continue
            fi
            [[ "$line" =~ ^[[:space:]]*$ ]] && continue
            if [[ ! "$line" =~ $metadata_start ]]; then
                metadata_allowed=false
                continue
            fi
            metadata_placement_allowed="$metadata_allowed"
            metadata_allowed=false
            in_metadata=true
            line="${line#*<!-- kb-section:}"
        fi

        if [[ "$line" == *'-->'* ]]; then
            metadata_buffer+="${line%%-->*}"
            if [[ "${line#*-->}" =~ ^[[:space:]]*$ ]]; then
                if [[ -z "$locator" ]]; then
                    misplaced_before_heading=true
                elif [[ "$metadata_placement_allowed" != true ]]; then
                    section_metadata_add_invalid "$locator" "invalid section metadata placement after body content"
                else
                    section_metadata_apply "$locator" "$metadata_buffer" "$locator"
                fi
            fi
            in_metadata=false
            metadata_buffer=""
        else
            metadata_buffer+="$line"$'\n'
        fi
    done < "$file"

    if [[ "$in_metadata" == true && -n "$locator" ]]; then
        if [[ "$metadata_placement_allowed" == true ]]; then
            section_metadata_apply "$locator" "$metadata_buffer" "$locator"
        fi
        section_metadata_add_invalid "$locator" "unclosed section metadata comment"
    fi

    if [[ "${SECTION_METADATA_CACHE_ENABLED:-false}" == true ]]; then
        section_metadata_cache_store "$relpath"
    fi
    section_metadata_select "$selector"
}

section_metadata_cache_store() {
    local relpath="$1" scope="${2:-sections}" locator field value cache_key field_scope_key
    local field_mapping variable reference_index
    local locators=()

    if [[ "$scope" == sections ]]; then
        for locator in "${!SECTION_META_STATUS[@]}"; do
            locators+=("$locator")
            cache_key="$relpath$SECTION_METADATA_CACHE_SEPARATOR$locator"
            for field_mapping in "${SECTION_METADATA_CACHE_SECTION_FIELD_MAP[@]}"; do
                field="${field_mapping%%:*}"
                variable="${field_mapping#*:}[$locator]"
                value="${!variable}"
                SECTION_META_CACHE_VALUES["$cache_key$SECTION_METADATA_CACHE_SEPARATOR$field"]="$value"
            done
            for field in "${SECTION_METADATA_CACHE_SECTION_SCOPE_FIELDS[@]}"; do
                field_scope_key="$locator:$field"
                SECTION_META_CACHE_FIELD_SCOPES["$cache_key$SECTION_METADATA_CACHE_SEPARATOR$field"]="${SECTION_META_FIELD_SCOPE[$field_scope_key]-}"
            done
        done
    fi
    SECTION_META_CACHE_LOCATORS["$relpath"]="${locators[*]}"

    for field_mapping in "${SECTION_METADATA_CACHE_ARTICLE_FIELD_MAP[@]}"; do
        field="${field_mapping%%:*}"
        variable="${field_mapping#*:}"
        value="${!variable}"
        SECTION_META_CACHE_ARTICLE_VALUES["$relpath$SECTION_METADATA_CACHE_SEPARATOR$field"]="$value"
    done

    SECTION_META_CACHE_ARTICLE_REFERENCE_INDICES["$relpath"]="${!SECTION_META_ARTICLE_PROVENANCE_REFERENCES[*]}"
    for reference_index in "${!SECTION_META_ARTICLE_PROVENANCE_REFERENCES[@]}"; do
        SECTION_META_CACHE_ARTICLE_REFERENCES["$relpath$SECTION_METADATA_CACHE_SEPARATOR$reference_index"]="${SECTION_META_ARTICLE_PROVENANCE_REFERENCES[$reference_index]}"
    done
    for reference_index in "${!SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES[@]}"; do
        SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCES["$relpath$SECTION_METADATA_CACHE_SEPARATOR$reference_index"]="${SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES[$reference_index]}"
    done
    SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCE_INDICES["$relpath"]="${!SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES[*]}"
    SECTION_META_CACHE_READY["$relpath"]="$scope"
}

section_metadata_cache_restore() {
    local relpath="$1" selector="${2:-}" locator field value cache_key field_scope_key
    local field_mapping variable reference_index
    local -a locators=() reference_indices=()

    SECTION_METADATA_RELPATH="$relpath"
    SECTION_META_VERIFIED=()
    SECTION_META_TTL=()
    SECTION_META_EFFECTIVE=()
    SECTION_META_STATUS=()
    SECTION_META_SUPERSEDES=()
    SECTION_META_SCOPE=()
    SECTION_META_SOURCE_SCOPE=()
    SECTION_META_SOURCES=()
    SECTION_META_HEADING=()
    SECTION_META_VALID=()
    SECTION_META_INVALID=()
    SECTION_META_FIELD_SCOPE=()

    if [[ -n "$selector" ]]; then
        if [[ -n "${SECTION_META_CACHE_VALUES[$relpath$SECTION_METADATA_CACHE_SEPARATOR$selector${SECTION_METADATA_CACHE_SEPARATOR}status]+present}" ]]; then
            locators=("$selector")
        fi
    elif [[ -n "${SECTION_META_CACHE_LOCATORS[$relpath]}" ]]; then
        read -r -a locators <<< "${SECTION_META_CACHE_LOCATORS[$relpath]}"
    fi
    for locator in "${locators[@]}"; do
        cache_key="$relpath$SECTION_METADATA_CACHE_SEPARATOR$locator"
        for field_mapping in "${SECTION_METADATA_CACHE_SECTION_FIELD_MAP[@]}"; do
            field="${field_mapping%%:*}"
            value="${SECTION_META_CACHE_VALUES[$cache_key$SECTION_METADATA_CACHE_SEPARATOR$field]}"
            variable="${field_mapping#*:}[$locator]"
            printf -v "$variable" '%s' "$value"
        done
        for field in "${SECTION_METADATA_CACHE_SECTION_SCOPE_FIELDS[@]}"; do
            field_scope_key="$locator:$field"
            SECTION_META_FIELD_SCOPE["$field_scope_key"]="${SECTION_META_CACHE_FIELD_SCOPES[$cache_key$SECTION_METADATA_CACHE_SEPARATOR$field]-}"
        done
    done

    for field_mapping in "${SECTION_METADATA_CACHE_ARTICLE_FIELD_MAP[@]}"; do
        field="${field_mapping%%:*}"
        value="${SECTION_META_CACHE_ARTICLE_VALUES[$relpath$SECTION_METADATA_CACHE_SEPARATOR$field]}"
        variable="${field_mapping#*:}"
        printf -v "$variable" '%s' "$value"
    done

    SECTION_META_ARTICLE_PROVENANCE_REFERENCES=()
    if [[ -n "${SECTION_META_CACHE_ARTICLE_REFERENCE_INDICES[$relpath]}" ]]; then
        read -r -a reference_indices <<< "${SECTION_META_CACHE_ARTICLE_REFERENCE_INDICES[$relpath]}"
    fi
    for reference_index in "${reference_indices[@]}"; do
        SECTION_META_ARTICLE_PROVENANCE_REFERENCES+=(
            "${SECTION_META_CACHE_ARTICLE_REFERENCES[$relpath$SECTION_METADATA_CACHE_SEPARATOR$reference_index]}"
        )
    done

    SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES=()
    reference_indices=()
    if [[ -n "${SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCE_INDICES[$relpath]}" ]]; then
        read -r -a reference_indices <<< "${SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCE_INDICES[$relpath]}"
    fi
    for reference_index in "${reference_indices[@]}"; do
        SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES+=(
            "${SECTION_META_CACHE_ARTICLE_DISPLAY_REFERENCES[$relpath$SECTION_METADATA_CACHE_SEPARATOR$reference_index]}"
        )
    done
}

section_metadata_select() {
    local selector="$1" field key section_reference

    RESULT_CORPUS="$SECTION_META_ARTICLE_CORPUS"
    PROVENANCE_DISPOSITION="$SECTION_META_ARTICLE_PROVENANCE_DISPOSITION"
    PROVENANCE_DESTINATION="$SECTION_META_ARTICLE_PROVENANCE_DESTINATION"
    PROVENANCE_STATE="$SECTION_META_ARTICLE_PROVENANCE_STATE"
    FRESHNESS_DATE_FIELD="$SECTION_META_ARTICLE_FRESHNESS_DATE_FIELD"
    FRESHNESS_DATE_VALUE="$SECTION_META_ARTICLE_FRESHNESS_DATE_VALUE"
    FRESHNESS_TTL_VALUE="$SECTION_META_ARTICLE_FRESHNESS_TTL_VALUE"
    FRESHNESS_TTL_DAYS="$SECTION_META_ARTICLE_FRESHNESS_TTL_DAYS"
    FRESHNESS_STATUS="$SECTION_META_ARTICLE_FRESHNESS_STATUS"
    FRESHNESS_AGE_DAYS="$SECTION_META_ARTICLE_FRESHNESS_AGE_DAYS"
    CONFLICT_STATUS="$SECTION_META_ARTICLE_CONFLICT_STATUS"
    PROVENANCE_SCOPE="$SECTION_META_ARTICLE_PROVENANCE_SCOPE"
    PROVENANCE_LABEL="$SECTION_META_ARTICLE_PROVENANCE_LABEL"
    PROVENANCE_REFERENCES=("${SECTION_META_ARTICLE_PROVENANCE_REFERENCES[@]}")
    PROVENANCE_DISPLAY_REFERENCES=("${SECTION_META_ARTICLE_PROVENANCE_DISPLAY_REFERENCES[@]}")
    PROVENANCE_REFERENCE_COUNT="$SECTION_META_ARTICLE_PROVENANCE_REFERENCE_COUNT"
    PROVENANCE_REFERENCES_TRUNCATED="$SECTION_META_ARTICLE_PROVENANCE_REFERENCES_TRUNCATED"

    SECTION_METADATA_AVAILABLE=false
    SECTION_METADATA_LOCATOR="$selector"
    SECTION_METADATA_VALID=true
    SECTION_METADATA_INVALID=""
    SECTION_METADATA_FIELD_SCOPE=()
    if [[ -n "$selector" && -n "${SECTION_META_STATUS[$selector]+present}" ]]; then
        SECTION_METADATA_AVAILABLE=true
        SECTION_METADATA_VERIFIED="${SECTION_META_VERIFIED[$selector]}"
        SECTION_METADATA_TTL="${SECTION_META_TTL[$selector]}"
        SECTION_METADATA_EFFECTIVE="${SECTION_META_EFFECTIVE[$selector]}"
        SECTION_METADATA_STATUS="${SECTION_META_STATUS[$selector]}"
        SECTION_METADATA_SUPERSEDES="${SECTION_META_SUPERSEDES[$selector]}"
        SECTION_METADATA_SCOPE="${SECTION_META_SCOPE[$selector]}"
        SECTION_METADATA_SOURCE_SCOPE="${SECTION_META_SOURCE_SCOPE[$selector]}"
        SECTION_METADATA_SOURCES="${SECTION_META_SOURCES[$selector]}"
        SECTION_METADATA_VALID="${SECTION_META_VALID[$selector]}"
        SECTION_METADATA_INVALID="${SECTION_META_INVALID[$selector]}"
        for field in verified ttl effective status supersedes sources; do
            key="$selector:$field"
            SECTION_METADATA_FIELD_SCOPE["$field"]="${SECTION_META_FIELD_SCOPE[$key]}"
        done

        if [[ "$SECTION_METADATA_SOURCE_SCOPE" == section ]]; then
            PROVENANCE_SCOPE=section
            PROVENANCE_LABEL="section-level references"
            PROVENANCE_REFERENCES=()
            PROVENANCE_DISPLAY_REFERENCES=()
            PROVENANCE_REFERENCE_COUNT=0
            PROVENANCE_REFERENCES_TRUNCATED=false
            IFS=',' read -r -a section_reference_values <<< "$SECTION_METADATA_SOURCES"
            for section_reference in "${section_reference_values[@]}"; do
                section_reference="$(section_metadata_trim "$section_reference")"
                [[ -n "$section_reference" ]] || continue
                PROVENANCE_REFERENCES+=("$section_reference")
            done
            PROVENANCE_REFERENCE_COUNT=${#PROVENANCE_REFERENCES[@]}
            for section_reference in "${PROVENANCE_REFERENCES[@]}"; do
                if (( ${#PROVENANCE_DISPLAY_REFERENCES[@]} >= MAX_DISPLAYED_PROVENANCE_REFERENCES )); then
                    PROVENANCE_REFERENCES_TRUNCATED=true
                    break
                fi
                PROVENANCE_DISPLAY_REFERENCES+=("$section_reference")
            done
        fi
    fi

    if [[ "$SECTION_METADATA_AVAILABLE" == true ]]; then
        if [[ -n "$SECTION_METADATA_TTL" ]]; then
            FRESHNESS_TTL_DAYS="$(ttl_days "$SECTION_METADATA_TTL")"
            FRESHNESS_TTL_VALUE="$SECTION_METADATA_TTL"
        fi
        if [[ "$SECTION_METADATA_VALID" != true ]]; then
            FRESHNESS_STATUS=invalid
        elif [[ -n "$SECTION_METADATA_VERIFIED" ]]; then
            FRESHNESS_DATE_VALUE="$SECTION_METADATA_VERIFIED"
            FRESHNESS_DATE_FIELD=verified
            [[ "$SECTION_METADATA_RELPATH" == sources/* ]] && FRESHNESS_DATE_FIELD=synced
            local section_epoch today_epoch age_seconds
            section_epoch="$(date_to_epoch "${SECTION_METADATA_VERIFIED%%T*}")"
            today_epoch="${FRESHNESS_TODAY_EPOCH:-$(date -u +%s)}"
            age_seconds=$((today_epoch - section_epoch))
            FRESHNESS_AGE_DAYS=$((age_seconds / 86400))
            if (( age_seconds > FRESHNESS_TTL_DAYS * 86400 )); then
                FRESHNESS_STATUS=stale
            else
                FRESHNESS_STATUS=fresh
            fi
        fi
        [[ "$SECTION_METADATA_STATUS" == unresolved ]] && CONFLICT_STATUS=unresolved
    fi
    return 0
}

json_section_metadata() {
    if [[ "${SECTION_METADATA_AVAILABLE:-false}" != true ]]; then
        printf 'null'
        return 0
    fi
    printf '{"available":true,"locator":'
    json_quote "$SECTION_METADATA_LOCATOR"
    printf ',"scope":'; json_quote "$SECTION_METADATA_SCOPE"
    if [[ "$SECTION_METADATA_SOURCE_SCOPE" == section ]]; then
        printf ',"source_scope":"section"'
    fi
    printf ',"field_scopes":{ '
    local field field_value first_scope=true
    for field in verified ttl effective status supersedes sources; do
        case "$field" in
            verified) field_value="$SECTION_METADATA_VERIFIED" ;;
            ttl) field_value="$SECTION_METADATA_TTL" ;;
            effective) field_value="$SECTION_METADATA_EFFECTIVE" ;;
            status) field_value="$SECTION_METADATA_STATUS" ;;
            supersedes) field_value="$SECTION_METADATA_SUPERSEDES" ;;
            sources) field_value="$SECTION_METADATA_SOURCES" ;;
        esac
        [[ -n "$field_value" || "$field" == status ]] || continue
        [[ "$first_scope" == false ]] && printf ', '
        json_quote "$field"
        printf ':'
        json_quote "${SECTION_METADATA_FIELD_SCOPE[$field]}"
        first_scope=false
    done
    printf ' }'
    printf ',"verified":'; json_nullable_string "$SECTION_METADATA_VERIFIED"
    printf ',"ttl":'; json_nullable_string "$SECTION_METADATA_TTL"
    [[ -n "$SECTION_METADATA_EFFECTIVE" ]] && {
        printf ',"effective":'; json_quote "$SECTION_METADATA_EFFECTIVE"
    }
    printf ',"status":'; json_quote "$SECTION_METADATA_STATUS"
    [[ -n "$SECTION_METADATA_SUPERSEDES" ]] && {
        printf ',"supersedes":'; json_quote "$SECTION_METADATA_SUPERSEDES"
    }
    printf ',"sources":['
    local first=true source
    IFS=',' read -r -a section_sources <<< "${SECTION_METADATA_SOURCES:-}"
    for source in "${section_sources[@]}"; do
        source="$(section_metadata_trim "$source")"
        [[ -n "$source" ]] || continue
        [[ "$first" == false ]] && printf ','
        json_quote "$source"
        first=false
    done
    printf '],"valid":%s' "$SECTION_METADATA_VALID"
    if [[ -n "$SECTION_METADATA_INVALID" ]]; then
        printf ',"invalid":'; json_quote "$SECTION_METADATA_INVALID"
    fi
    printf '}'
}

section_metadata_text() {
    [[ "${SECTION_METADATA_AVAILABLE:-false}" == true ]] || return 0
    printf 'section-status=%s; section-scope=%s' \
        "$SECTION_METADATA_STATUS" "$SECTION_METADATA_SCOPE"
    [[ -n "$SECTION_METADATA_EFFECTIVE" ]] && \
        printf '; effective=%s' "$SECTION_METADATA_EFFECTIVE"
    [[ -n "$SECTION_METADATA_SUPERSEDES" ]] && \
        printf '; supersedes=%s' "$SECTION_METADATA_SUPERSEDES"
    [[ -n "$SECTION_METADATA_INVALID" ]] && \
        printf '; metadata-invalid=%s' "$SECTION_METADATA_INVALID"
    return 0
}

# Escape od's byte stream so UTF-8 and trailing newlines survive unchanged.
_json_escape_hex() {
    LC_ALL=C awk '
    BEGIN { digits = "0123456789abcdef" }
    {
        for (i = 1; i <= NF; i++) {
            code = (index(digits, substr($i, 1, 1)) - 1) * 16 + index(digits, substr($i, 2, 1)) - 1
            if (code == 8) printf "%s", "\\b"
            else if (code == 9) printf "%s", "\\t"
            else if (code == 10) printf "%s", "\\n"
            else if (code == 12) printf "%s", "\\f"
            else if (code == 13) printf "%s", "\\r"
            else if (code == 34) printf "%s", "\\\""
            else if (code == 92) printf "%s", "\\\\"
            else if (code < 32) printf "%s%04x", "\\u", code
            else printf "%c", code
        }
    }'
}

# Check every pipeline stage even when the caller has not enabled pipefail.
json_escape_value() (
    set -o pipefail
    printf '%s' "$1" | LC_ALL=C od -An -v -t x1 | _json_escape_hex
)

json_escape_file() (
    set -o pipefail
    LC_ALL=C od -An -v -t x1 "$1" | _json_escape_hex
)

json_quote() {
    printf '"' || return 1
    json_escape_value "$1" || return 1
    printf '"' || return 1
}

json_quote_file() {
    printf '"' || return 1
    json_escape_file "$1" || return 1
    printf '"' || return 1
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

json_conflict() {
    printf '{"status":'
    json_quote "$CONFLICT_STATUS"
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
    [[ "$CONFLICT_STATUS" != "none" ]] && \
        printf '; conflict=%s' "$CONFLICT_STATUS"
    return 0
}

conflict_metadata_text() {
    if [[ "$CONFLICT_STATUS" != "none" ]]; then
        printf 'Conflict: status=%s\n' "$CONFLICT_STATUS"
    fi
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

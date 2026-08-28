#!/usr/bin/env bats

load test_helper

setup() {
    setup_content_dir
    export INSTALL_HOME="$(mktemp -d)"
    export XDG_CONFIG_HOME="$INSTALL_HOME/config"
}

teardown() {
    teardown_content_dir
    rm -rf "$INSTALL_HOME"
}

@test "install migrates legacy Claude hooks to adapters" {
    local hooks_dir="$XDG_CONFIG_HOME/coat-tree/hooks.d"
    local scripts_root
    local events=(SessionStart UserPromptSubmit Stop SessionEnd PreToolUse)
    local scripts=(session-start session-prompt session-stop session-end pretool-allow)

    scripts_root="$(cd "$SCRIPTS" && pwd -P)"

    for index in "${!events[@]}"; do
        mkdir -p "$hooks_dir/${events[$index]}"
        ln -s "$SCRIPTS/${scripts[$index]}" \
            "$hooks_dir/${events[$index]}/010.knowledge"
    done

    run env HOME="$INSTALL_HOME" XDG_CONFIG_HOME="$XDG_CONFIG_HOME" \
        KB_CONTENT_DIR="$TEST_CONTENT_DIR" "$SCRIPTS/install"
    [[ "$status" -eq 0 ]]
    [[ "$output" == *"Migrated 5 legacy Claude hook(s)."* ]]

    for index in "${!events[@]}"; do
        run readlink "$hooks_dir/${events[$index]}/010.knowledge"
        [[ "$output" == "$scripts_root/adapters/claude/${scripts[$index]}" ]]
    done
}

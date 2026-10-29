"""The hook script and the hook action for each state of the hook path."""

import pytest

from kb import setup_rules
from kb.errors import KbError

KB = "/opt/tools/kb"
SCRIPT = setup_rules.hook_script(KB)
Action = setup_rules.HookAction


def test_the_script_is_the_three_line_contract() -> None:
    assert SCRIPT == (
        "#!/bin/sh\n"
        "# Installed by kb setup. Do not edit; run kb setup again to update.\n"
        "exec '/opt/tools/kb' hook pre-commit \"$@\"\n"
    )


def test_a_kb_path_with_spaces_and_non_ascii_is_quoted_as_written() -> None:
    path = "/home/agude/My Tools/kb-café"

    assert f"exec '{path}' hook pre-commit" in setup_rules.hook_script(path)


@pytest.mark.parametrize("path", ["/a'b/kb", "/a\nb/kb", "/a\rb/kb", "/a\0b/kb"])
def test_a_kb_path_the_script_cannot_quote_is_refused(path: str) -> None:
    with pytest.raises(KbError, match="must not contain"):
        setup_rules.hook_script(path)


def test_a_missing_hook_is_installed() -> None:
    assert setup_rules.hook_action(setup_rules.ExistingHook("absent"), SCRIPT) is Action.INSTALL


def test_a_managed_hook_with_the_same_bytes_is_unchanged() -> None:
    existing = setup_rules.ExistingHook("file", data=SCRIPT.encode("utf-8"))

    assert setup_rules.hook_action(existing, SCRIPT) is Action.UNCHANGED


def test_a_managed_hook_with_other_bytes_is_updated() -> None:
    old = f"#!/bin/sh\n{setup_rules.HOOK_MARKER}\nexec '/old/kb' hook pre-commit \"$@\"\n"
    existing = setup_rules.ExistingHook("file", data=old.encode("utf-8"))

    assert setup_rules.hook_action(existing, SCRIPT) is Action.UPDATE


@pytest.mark.parametrize("data", [b"", b"#!/bin/sh\nexec something\n", b"#!/bin/sh\n\xff\n"])
def test_a_file_that_kb_did_not_write_is_foreign(data: bytes) -> None:
    existing = setup_rules.ExistingHook("file", data=data)

    assert setup_rules.hook_action(existing, SCRIPT) is Action.REFUSE_FOREIGN


def test_a_directory_or_other_kind_at_the_hook_path_is_foreign() -> None:
    assert setup_rules.hook_action(setup_rules.ExistingHook("other"), SCRIPT) is (
        Action.REFUSE_FOREIGN
    )


def test_a_symbolic_link_at_the_hook_path_is_foreign_whatever_it_targets() -> None:
    link = setup_rules.ExistingHook("link", link_target="/elsewhere/pre-commit")

    assert setup_rules.hook_action(link, SCRIPT) is Action.REFUSE_FOREIGN


@pytest.mark.parametrize(
    ("output", "expected"),
    [("kb 0.1.0\n", True), ("kb 0.1.0", True), ("kb", False), ("kb: 0.1", False), ("x 1\n", False)],
)
def test_a_version_line_must_be_kb_followed_by_a_version(output: str, expected: bool) -> None:
    assert setup_rules.version_line_ok(output) is expected

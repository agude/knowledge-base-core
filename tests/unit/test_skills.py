"""The packaged skills name registered commands and options."""

import importlib
import re
from importlib import resources

import pytest

from kb import args, registry

NAMES = ("knowledge-base", "curate")
COMMAND = re.compile(r"\bkb\s+([a-z][a-z-]*)\b")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*\b")


def skill_text(name: str) -> str:
    """The source package's skill text."""
    return (
        resources.files("kb")
        .joinpath("data", "skills", name, "SKILL.md")
        .read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("name", NAMES)
def test_each_skill_names_only_registered_commands_and_options(name: str) -> None:
    text = skill_text(name)
    commands = set(COMMAND.findall(text))
    options = set(OPTION.findall(text))
    registered_commands = {command.name for command in registry.COMMANDS}
    registered_options = set(args.HELP_FLAGS)
    for command in registry.COMMANDS:
        module = importlib.import_module(command.run.__module__)
        for value in vars(module).values():
            if isinstance(value, args.Spec):
                registered_options.update(value.valued | value.switches)

    assert commands <= registered_commands, sorted(commands - registered_commands)
    assert options <= registered_options, sorted(options - registered_options)


@pytest.mark.parametrize("name", NAMES)
def test_each_skill_has_named_front_matter_and_stays_under_500_lines(name: str) -> None:
    lines = skill_text(name).splitlines()

    assert len(lines) < 500
    assert lines[0] == "---"
    end = lines.index("---", 1)
    fields = dict(line.split(":", 1) for line in lines[1:end] if ":" in line)
    assert fields.get("name", "").strip() == name
    assert fields.get("description", "").strip()

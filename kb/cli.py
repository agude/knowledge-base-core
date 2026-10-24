"""Option parsing with the rules every bash command follows.

- An option that takes a value takes the next word, whatever it starts
  with (audit A-030). With no next word: `Option X requires an argument`.
- `-h` and `--help` print the command's help, its module docstring, framed
  as the bash scripts frame their header comment: a blank line first.
- Any other word is `Unknown option: X`, unless the command accepts
  positional arguments, in which case words not starting with `-` are
  positional.
Errors print to stderr and exit 1.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass
class Parsed:
    values: dict[str, str] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    positional: list[str] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def print_help(doc: str | None) -> None:
    sys.stdout.write("\n" + (doc or "").strip("\n") + "\n")


def parse(
    argv: list[str],
    doc: str | None,
    *,
    values: Mapping[str, str] = {},
    flags: Mapping[str, str] = {},
    positional: bool = False,
) -> Parsed:
    """Parse argv. values and flags map each spelling to the name it sets."""
    parsed = Parsed()
    index = 0
    while index < len(argv):
        word = argv[index]
        if word in values:
            if index + 1 >= len(argv):
                fail(f"Option {word} requires an argument")
            parsed.values[values[word]] = argv[index + 1]
            index += 2
            continue
        if word in flags:
            parsed.flags.add(flags[word])
        elif word in ("-h", "--help"):
            print_help(doc)
            raise SystemExit(0)
        elif positional and not (word.startswith("-") and word != "-"):
            parsed.positional.append(word)
        else:
            fail(f"Unknown option: {word}")
        index += 1
    return parsed

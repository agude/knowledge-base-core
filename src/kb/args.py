"""Command-line words for the kb commands: options, positional words, and help.

A command declares its options in a Spec. parse() returns the positional
words and the option values, and raises KbError for an unknown option or a
missing value. Words after "--" are always positional, so a query can
contain a flag-like word.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field

from kb.errors import KbError

HELP_FLAGS = ("-h", "--help")


@dataclass(frozen=True)
class Spec:
    """A command's usage line, summary, and options.

    usage is the text after "Usage: kb ", for example "recall QUERY...".
    valued lists the options that take one value; switches lists the options
    that take none.
    """

    usage: str
    summary: str
    valued: frozenset[str] = field(default_factory=frozenset)
    switches: frozenset[str] = field(default_factory=frozenset)

    def help_text(self) -> str:
        """The text `kb COMMAND --help` prints."""
        return f"Usage: kb {self.usage}\n\n{self.summary}\n"

    def usage_error(self) -> KbError:
        """The error for a missing positional word."""
        return KbError(f"Usage: kb {self.usage}")


@dataclass
class Parsed:
    """The result of parsing one command's words."""

    words: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)
    switches: set[str] = field(default_factory=set)
    help: bool = False


def parse(spec: Spec, args: Sequence[str]) -> Parsed:
    """Split args into positional words and options as spec declares them."""
    parsed = Parsed()
    positional_only = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if positional_only or arg == "-":
            parsed.words.append(arg)
        elif arg == "--":
            positional_only = True
        elif arg in HELP_FLAGS:
            parsed.help = True
            return parsed
        elif arg.startswith("--"):
            name, equals, inline = arg.partition("=")
            if name in spec.valued:
                if equals:
                    parsed.values[name] = inline
                elif index < len(args):
                    parsed.values[name] = args[index]
                    index += 1
                else:
                    raise KbError(f"Option {name} requires an argument")
            elif name in spec.switches and not equals:
                parsed.switches.add(name)
            else:
                raise KbError(f"Unknown option: {name}")
        elif arg.startswith("-"):
            raise KbError(f"Unknown option: {arg}")
        else:
            parsed.words.append(arg)
    return parsed


def positive_int(value: str, option: str) -> int:
    """The value as an integer greater than zero, or KbError."""
    if value.isascii() and value.isdigit() and int(value) > 0:
        return int(value)
    raise KbError(f"Option {option} must be a positive integer")


def choice_int(value: str, option: str, choices: Collection[int]) -> int:
    """The value as one of choices, or KbError listing them."""
    if value.isascii() and value.isdigit() and int(value) in choices:
        return int(value)
    ordered = [str(choice) for choice in sorted(choices)]
    if len(ordered) == 2:
        listing = " or ".join(ordered)
    else:
        listing = ", ".join(ordered[:-1]) + ", or " + ordered[-1]
    raise KbError(f"Option {option} must be {listing}")

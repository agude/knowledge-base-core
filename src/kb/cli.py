"""Command-line interface for knowledge-base."""

import argparse
from collections.abc import Sequence

from kb import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for kb."""
    parser = argparse.ArgumentParser(
        prog="kb",
        description="A short description of kb.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run kb and return its exit status."""
    build_parser().parse_args(argv)
    return 0

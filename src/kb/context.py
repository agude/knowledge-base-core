"""The run context: the content repository and today's date, from the environment."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from kb import dates
from kb.config import content_root
from kb.platform import config_file


@dataclass(frozen=True)
class Context:
    """Where the content repository is, and the date that freshness is judged against."""

    root: Path
    today: date


def load(environ: Mapping[str, str], platform: str, home: Path) -> Context:
    """Resolve the content repository and the date from the environment and the config file."""
    config = config_file(environ, platform, home)
    return Context(root=content_root(environ, config), today=dates.today(environ))

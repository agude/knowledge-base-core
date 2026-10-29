"""Operating-system specifics: where the config file lives.

Each function takes the platform name and the environment as arguments, so
every branch can be tested on any machine.
"""

from collections.abc import Mapping
from pathlib import Path

LINUX = "linux"
WINDOWS = "win32"


def config_file(environ: Mapping[str, str], platform: str, home: Path) -> Path:
    """The config file: under XDG_CONFIG_HOME if set, else LOCALAPPDATA on Windows, else ~/.config."""
    xdg = environ.get("XDG_CONFIG_HOME", "")
    if xdg:
        return Path(xdg) / "kb" / "config.toml"
    if platform == WINDOWS:
        local = environ.get("LOCALAPPDATA", "")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "kb" / "config.toml"
    return home / ".config" / "kb" / "config.toml"


def scheduler_commands(platform: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    """The argument lists that ask whether the sync timer is enabled and active, or None.

    Only Linux has a timer that kb installs, through systemd's user instance.
    """
    if platform != LINUX:
        return None
    return (
        ("systemctl", "--user", "is-enabled", "kb-sync.timer"),
        ("systemctl", "--user", "is-active", "kb-sync.timer"),
    )

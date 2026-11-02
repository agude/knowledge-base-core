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


def scheduler_commands(platform: str) -> tuple[tuple[str, ...], ...] | None:
    """The argument lists that ask about the scheduled kb sync, or None where kb does not check.

    Linux asks systemd's user instance whether kb-sync.timer is enabled and active. Windows
    asks Task Scheduler for the kb-sync task's state; the state names are not localized, and
    a missing task prints nothing.
    """
    if platform == LINUX:
        return (
            ("systemctl", "--user", "is-enabled", "kb-sync.timer"),
            ("systemctl", "--user", "is-active", "kb-sync.timer"),
        )
    if platform == WINDOWS:
        query = "(Get-ScheduledTask -TaskName 'kb-sync' -ErrorAction Stop).State"
        return (("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", query),)
    return None

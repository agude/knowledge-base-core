"""Operating-system specifics: where the config file and Goose's sessions live.

Each function takes the platform name and the environment as arguments, so
every branch can be tested on any machine.
"""

from collections.abc import Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath

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


def goose_sessions(environ: Mapping[str, str], platform: str, home: Path) -> Path:
    """Goose's sessions directory, which holds its session database, found as Goose finds it.

    An absolute GOOSE_PATH_ROOT holds Goose's data on every platform. Otherwise the data is in
    APPDATA on Windows, and in an absolute XDG_DATA_HOME or ~/.local/share elsewhere. Goose
    ignores a relative GOOSE_PATH_ROOT or XDG_DATA_HOME.
    """
    root = environ.get("GOOSE_PATH_ROOT", "")
    if root and _absolute(root, platform):
        return Path(root) / "data" / "sessions"
    if platform == WINDOWS:
        roaming = environ.get("APPDATA", "")
        base = Path(roaming) if roaming else home / "AppData" / "Roaming"
        return base / "Block" / "goose" / "data" / "sessions"
    data = environ.get("XDG_DATA_HOME", "")
    base = Path(data) if data and _absolute(data, platform) else home / ".local" / "share"
    return base / "goose" / "sessions"


def _absolute(path: str, platform: str) -> bool:
    """Whether a path is absolute on the platform, which need not be this machine's."""
    pure = PureWindowsPath(path) if platform == WINDOWS else PurePosixPath(path)
    return pure.is_absolute()


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

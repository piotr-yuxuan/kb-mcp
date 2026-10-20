"""Settings: the site, where data lives, and what to download when no flag says."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from atlassian_offline_mcp.domain.content import PROJECT_KEY, SPACE_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_DATA_DIR = "~/atlassian-offline-mcp"
KNOWN_KEYS = frozenset({"site", "data_dir", "spaces", "projects"})
# Folders that may be synchronised to a cloud, under the home directory or by name.
SYNCED_UNDER_HOME = (
    Path("Library/Mobile Documents"),
    Path("Library/CloudStorage"),
    Path("Desktop"),
    Path("Documents"),
)
SYNCED_NAMES = ("Dropbox", "OneDrive", "Google Drive")


class SettingsError(ValueError):
    """A setting that cannot be used; the message names it."""


@dataclass(frozen=True)
class Settings:
    """What every command needs to know: the site, the data directory, the defaults."""

    site: str | None
    data_dir: Path
    spaces: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()

    @property
    def raw(self) -> Path:
        """The raw store: responses as received, and attached files."""
        return self.data_dir / "raw"

    @property
    def docs(self) -> Path:
        """The Markdown mirror that agents read."""
        return self.data_dir / "docs"

    @property
    def index(self) -> Path:
        """The search index, built from the mirror alone."""
        return self.data_dir / "index.sqlite"

    @property
    def session(self) -> Path:
        """The browser profile and the saved session, never read by agents."""
        return self.data_dir / "session"


def parse_settings(values: Mapping[str, object], home: Path) -> Settings:
    """Check settings read from a file or flags, and return them normalised.

    The site becomes ``https://<host>``; the data directory, whose ``~`` means ``home``,
    must be absolute; space and project keys must look like keys.
    """
    unknown = sorted(set(values) - KNOWN_KEYS)
    if unknown:
        message = f"unknown setting: {', '.join(unknown)}"
        raise SettingsError(message)
    site = values.get("site")
    try:
        parts = urlsplit(site) if isinstance(site, str) else None
    except ValueError:  # such as an unclosed [ in the host
        parts = None
    if site is not None and (
        parts is None
        or parts.scheme != "https"
        or not parts.hostname
        or parts.netloc.lower() != parts.hostname
        or parts.path not in {"", "/"}
    ):
        message = "site: an https address with a host name alone, such as https://x.atlassian.net"
        raise SettingsError(message)
    data_dir = values.get("data_dir", DEFAULT_DATA_DIR)
    if not isinstance(data_dir, str) or not data_dir.strip():
        message = "data_dir: a path"
        raise SettingsError(message)
    path = home / data_dir[2:] if data_dir == "~" or data_dir.startswith("~/") else Path(data_dir)
    if not path.is_absolute():
        message = "data_dir: an absolute path, or one under ~"
        raise SettingsError(message)
    spaces, projects = values.get("spaces", []), values.get("projects", [])
    if not isinstance(spaces, list) or not all(
        isinstance(key, str) and SPACE_KEY.fullmatch(key) for key in spaces
    ):
        message = "spaces: a list of space keys"
        raise SettingsError(message)
    if not isinstance(projects, list) or not all(
        isinstance(key, str) and PROJECT_KEY.fullmatch(key) for key in projects
    ):
        message = "projects: a list of project keys"
        raise SettingsError(message)
    host = f"https://{parts.hostname}" if parts is not None else None
    return Settings(host, path, tuple(spaces), tuple(projects))


def unsafe_location(path: Path, home: Path, git_root: Path | None) -> str | None:
    """Return why company data must not live at this path, or None when it may.

    ``path`` and ``home`` must be resolved, without links or ``..``; names compare
    without regard to case, as on the default file system of macOS. ``git_root`` is the
    working tree that holds the path, if any: data there could be committed. A
    synchronised folder would copy the data off the machine.
    """
    if git_root is not None:
        return f"inside the git working tree {git_root}"
    parts = [part.casefold() for part in path.parts]
    home_parts = [part.casefold() for part in home.parts]
    if parts[: len(home_parts)] == home_parts:
        relative = parts[len(home_parts) :]
        for folder in SYNCED_UNDER_HOME:
            if relative[: len(folder.parts)] == [part.casefold() for part in folder.parts]:
                return f"under ~/{folder}, which may be synchronised"
    for name in SYNCED_NAMES:
        if any(part.startswith(name.casefold()) for part in parts):
            return f"under a {name} folder"
    return None

"""What the program's former name, atlassian-offline-mcp, left, and the stop that says so.

Plan 027 renamed the program kb-mcp. A run that finds what the former name left stops
before acting and prints how to move it; nothing is moved for the user. Only the
settings the run uses are judged: the settings file that it reads, or the former one in
its place when the default is missing (rule 1), then the variables and the flags. Rule 2
moves the former data directory when the data directory so judged is the default, and
missing; rule 3 renames each variable of the former prefix that is set, and whose new
name is not; rule 4 names each path setting, and the settings file given, that holds a
folder or a file whose name begins with the former name, a place to move with the
setting, never a site or an e-mail, which a user cannot rename. Where a former place and
its new one both exist, the new one is used and nothing stops.

Once the user's machine has moved, the roadmap's row after plan 033 removes this module, its
call in ``load_settings``, ``advice``'s use in ``enter``, its tests, its line in
``tests/conftest.py`` and ``docs/how-to/move-to-kb-mcp.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING

from kb_mcp.config.domain.settings import (
    DEFAULT_DATA_DIR,
    NESTING,
    SETTING_PATHS,
    SettingsError,
    at_home,
    variable,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kb_mcp.config.domain.settings import Loaded

FORMER_PREFIX = "ATLASSIAN_OFFLINE_MCP_"
FORMER_SETTINGS_FILE = Path("~/.config/atlassian-offline-mcp/config.toml")
FORMER_DATA_DIR = Path("~/atlassian-offline-mcp")
# The former name as a path may write it, in any case and with any separator, at the
# start of a folder's or a file's name: a folder above whose name holds it elsewhere,
# such as a clone's under an agent's scratch, names no place of the program's.
FORMER_NAME = re.compile(r"(?:^|/)atlassian.offline.mcp", re.IGNORECASE)
# Each setting renamed since, by its former path, to its path now: none yet. Plans 030
# and 036, which rename settings, add theirs, so that the stop prints final names.
RENAMED: dict[tuple[str, ...], tuple[str, ...]] = {}
# What the program cannot do for the user, as it reads no other program's configuration.
BY_HAND = (
    "- uv tool uninstall atlassian-offline-mcp, then uv tool install --force <checkout>",
    "- Claude Code: claude mcp remove --scope user atlassian-offline-mcp, then",
    "  claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp, with the arguments",
    "  it was added with, such as serve --allow-remote-embeddings; in ~/.claude/settings.json",
    "  and each project's .claude/settings.local.json, mcp__atlassian-offline-mcp__*",
    "  renamed mcp__kb-mcp__*, and the data's docs/ path moved in additionalDirectories",
    "  and in the Edit deny rule",
    "- VS Code: in each mcp.json, the server's key and command; then its tools approved again",
    "- every other MCP client that starts the server, such as a project's .mcp.json,",
    "  LM Studio, llama.cpp or Codex: its entry's key and command",
    "- completion: the former script removed, and kb-mcp completion loaded as",
    "  docs/how-to/shell-completions.md says",
    "- eval-agents: each run prepared before, whose files call the former package, prepared",
    "  again",
    "- another search engine over the mirror: each collection on ~/atlassian-offline-mcp/docs/",
    "  added again on ~/kb-mcp/docs/",
)


class FormerNameError(SettingsError):
    """What the former name left; ``advice`` says how to move it."""

    def __init__(self, message: str, advice: str) -> None:
        """Keep the advice, written after the refusal."""
        super().__init__(message)
        self.advice = advice


@dataclass(frozen=True)
class Found:
    """What the loader found of the default places and the former ones, written from ``~``.

    ``settings_file`` is the default settings file, ``settings_given`` the one that the run
    was given, as written, and ``reads_default`` says whether they are one, by whatever
    path. ``existing`` holds those of four places that exist: the default settings file,
    ``FORMER_SETTINGS_FILE``, the default data directory and ``FORMER_DATA_DIR``.
    ``former_data_in_git`` says whether the former data directory lies in a git working
    tree, which was never the program's data, as the guard on where data lives refuses it.
    """

    settings_file: Path
    settings_given: Path
    reads_default: bool
    existing: frozenset[Path]
    former_data_in_git: bool

    @property
    def former_file_judged(self) -> bool:
        """Rule 1: the run reads the default settings file, missing, and the former exists."""
        return (
            self.reads_default
            and self.settings_file not in self.existing
            and FORMER_SETTINGS_FILE in self.existing
        )


def refuse_former_name(
    found: Found, loaded: Loaded, data_dir: Path, environ: Mapping[str, str], home: Path
) -> None:
    """Raise FormerNameError for what the former name left, saying how to move it.

    ``loaded`` holds the settings judged as given, the former file's when rule 1 holds,
    with ``~`` as ``home``, and their layers; ``data_dir`` is the data directory that
    the run uses, resolved, as ``home`` is. The advice holds, each section only when it
    has a line: a block of the moves of rules 1 and 2, which a shell can run as it is,
    headed ``# Move the files:`` and ended by a blank line; each variable of rule 3 and
    its new name, never its value; each path of rule 4, a setting's or the settings file
    given, and its layer, never its value; then, always, what is done by hand. A
    variable is read without regard to case, as pydantic-settings reads it, and is set
    when it is not empty.
    """
    default_data = Path(DEFAULT_DATA_DIR)
    moves = []
    if found.former_file_judged:
        moves.append(
            f"mkdir -p {found.settings_file.parent}"
            f" && mv {FORMER_SETTINGS_FILE} {found.settings_file}"
        )
    if (
        data_dir == at_home(default_data, home)
        and default_data not in found.existing
        and FORMER_DATA_DIR in found.existing
        and not found.former_data_in_git
    ):
        moves.append(f"mv {FORMER_DATA_DIR} {default_data}")
    given = {name.lower() for name, value in environ.items() if value}
    variables = []
    for name in sorted(environ):
        if not (environ[name] and name.lower().startswith(FORMER_PREFIX.lower())):
            continue
        path = tuple(name[len(FORMER_PREFIX) :].lower().split(NESTING))
        renamed = variable(RENAMED.get(path, path))
        if renamed.lower() not in given:
            variables.append(f"{name} to {renamed}")
    judged = [
        *(
            (setting, layer, reduce(getattr, setting.split("."), loaded.settings))
            for setting, layer in sorted(loaded.layers.items())
            if SETTING_PATHS[tuple(setting.split("."))] == "path"
        ),
        ("the settings file", "--config", found.settings_given),
    ]
    if loaded.settings.data_dir != at_home(default_data, home):
        # Given through a link, a data directory may lead into the former folder, which
        # the move would leave it leading nowhere; rule 2 judges the default's.
        judged.append(("data_dir", loaded.layer("data_dir"), data_dir))
    paths = list(
        dict.fromkeys(
            f"{name} ({layer})" for name, layer, value in judged if FORMER_NAME.search(str(value))
        )
    )
    sections = [
        ("# Move the files:", moves),
        (
            "Rename each variable where it is set (a shell's profile, an MCP client, sops):",
            variables,
        ),
        ("Change each setting whose path names the former name, moving what it names:", paths),
        ("Then, by hand, as docs/how-to/move-to-kb-mcp.md says:", BY_HAND),
    ]
    if moves or variables or paths:
        message = "atlassian-offline-mcp, the program's former name, left what is said below"
        advice = "".join(
            f"{line}\n" for heading, lines in sections if lines for line in (heading, *lines, "")
        )
        raise FormerNameError(message, advice)

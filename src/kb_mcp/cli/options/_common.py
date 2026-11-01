"""Options that commands share, declared without importing what runs them."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, override

from argcomplete.completers import DirectoriesCompleter, FilesCompleter

from kb_mcp.config.adapters.settings_file import SETTINGS_PATH
from kb_mcp.kernel.endpoint import EMBEDDINGS, refused_endpoint
from kb_mcp.kernel.names import MODEL_NAME
from kb_mcp.kernel.output import FORMATS, LEVELS, SUMMARIES
from kb_mcp.sources.atlassian.declared import API_TOKEN, CONFLUENCE, EMAIL, JIRA, SITE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.cli.domain.command import Refused
    from kb_mcp.kernel.output import Level
    from kb_mcp.sources.declaration import Declared, Option

# The level of each -v given, from none: warning, then info, then debug.
VERBOSITY: tuple[Level, ...] = ("warning", "info", "debug")
# The Atlassian account's settings of a sign-in by API token, which the commands that
# reach its site read beside the site: its email and the token.
SIGN_IN = (EMAIL, API_TOKEN)


class Verbose(argparse.Action):
    """``-v``: each time it is given, one level more verbose, down to debug."""

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """Take the next level of ``VERBOSITY``, or keep its last."""
        step = VERBOSITY.index(getattr(namespace, self.dest)) + 1
        setattr(namespace, self.dest, VERBOSITY[min(step, len(VERBOSITY) - 1)])


class Quiet(argparse.Action):
    """``-q``: write no result as text, and say errors alone, at the level error."""

    @override
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        """Set ``quiet``, and the level to error."""
        setattr(namespace, self.dest, True)
        namespace.level = "error"


def add_output_options(parser: argparse.ArgumentParser, *, result: bool = True) -> None:
    """Add -q, -v and --log-level, which exclude one another, then --format and --summary.

    Each of the three sets ``level``: warning by default, info with -v, debug with -vv,
    error with -q. -q alone also sets ``quiet``, which leaves a result as text unwritten,
    as Unix has it; a level leaves stdout alone. Without ``result``, for a command whose
    output is its own, such as a protocol, --format and --summary are not offered, and
    take their defaults.
    """
    parser.set_defaults(level=VERBOSITY[0], quiet=False, format=FORMATS[0], summary=SUMMARIES[0])
    levels = parser.add_mutually_exclusive_group()
    levels.add_argument(
        "-q",
        dest="quiet",
        action=Quiet,
        nargs=0,
        help="say errors alone, and write no result as text",
    )
    levels.add_argument(
        "-v", dest="level", action=Verbose, nargs=0, help="the level info, or debug with -vv"
    )
    levels.add_argument(
        "--log-level",
        dest="level",
        choices=LEVELS,
        help="say what is of this level or above; warning by default",
    )
    if result:
        parser.add_argument(
            "--format", choices=FORMATS, help="write the result as text, or as one JSON document"
        )
        parser.add_argument(
            "--summary", choices=SUMMARIES, help="write what matters of the result, or all of it"
        )


def add_yes_option(parser: argparse.ArgumentParser) -> None:
    """Add -y and --yes, for a command that writes: it runs without the question."""
    parser.add_argument(
        "-y", "--yes", action="store_true", help="run without asking first, as a script does"
    )


def add_settings_options(
    parser: argparse.ArgumentParser,
) -> tuple[tuple[argparse.Action, ...], dict[str, str]]:
    """Add --config, --data-dir and --site; return their actions, and each flag's setting."""
    config = parser.add_argument(
        "--config", type=Path, default=SETTINGS_PATH, help="the settings file"
    )
    config.completer = FilesCompleter(["toml"])
    data_dir = parser.add_argument("--data-dir", help="the data directory, overriding the settings")
    data_dir.completer = DirectoriesCompleter()
    site = parser.add_argument("--site", help="the site, as https://<name>.atlassian.net")
    return (config, data_dir, site), {"data_dir": "data_dir", "site": SITE}


def add_option(
    parser: argparse.ArgumentParser | argparse._ArgumentGroup, option: Option
) -> argparse.Action:
    """Add an option that a source declares, as ``given`` reads it; return its action.

    Its value is kept under its flag itself, so that no flag that a source declares takes
    a name that the program holds, such as ``sources``; help names its value as it would
    by the flag alone. One that replaces a setting repeats.
    """
    return parser.add_argument(
        option.flag,
        dest=option.flag,
        metavar=option.flag.lstrip("-").replace("-", "_").upper(),
        action="append" if option.setting else "store",
        type=option.type,
        help=option.help,
    )


def add_embedding_options(parser: argparse.ArgumentParser) -> argparse.Action:
    """Add --allow-remote-embeddings, never a setting, so that it is given on every run.

    Return its action.
    """
    return parser.add_argument(
        "--allow-remote-embeddings",
        action="store_true",
        help="let this run send the mirror's text to an embedding endpoint off this machine",
    )


def model_name(value: str) -> str:
    """Take a model's name given on the command line as the setting takes it."""
    if not MODEL_NAME.fullmatch(value):
        message = "the name of an embedding model, such as qwen3-embedding:0.6b"
        raise argparse.ArgumentTypeError(message)
    return value


def of_atlassian(sources: Sequence[Declared], refused: Refused | None = None) -> Refused | None:
    """Give what a command of the Atlassian package refuses, under this registry.

    ``doctor`` and ``login`` read that package's settings by name until plan 031 moves
    them, so a registry without both its sources is refused before they read one; any
    other, as ``refused`` says.
    """
    if {CONFLUENCE.name, JIRA.name} <= {declared.name for declared in sources}:
        return refused
    return lambda _arguments, _settings: (
        f"{CONFLUENCE.name} and {JIRA.name}: not both in the registry, which this command reads"
    )


def endpoint_elsewhere(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse an embedding endpoint off this machine without the run's word, or over http."""
    return refused_endpoint(
        str(settings["embedding_url"]), EMBEDDINGS, remote_allowed=arguments.allow_remote_embeddings
    )


def endpoint_by_meaning(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> str | None:
    """Refuse the endpoint as ``endpoint_elsewhere`` does, unless the lexical mode embeds none."""
    if settings["search_mode"] == "lexical":
        return None
    return endpoint_elsewhere(arguments, settings)

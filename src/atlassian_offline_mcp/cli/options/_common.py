"""Options that commands share, declared without importing what runs them."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, override

from argcomplete.completers import DirectoriesCompleter, FilesCompleter

from atlassian_offline_mcp.config.adapters.settings_file import SETTINGS_PATH
from atlassian_offline_mcp.kernel.content import MODEL_NAME
from atlassian_offline_mcp.kernel.endpoint import refused_endpoint
from atlassian_offline_mcp.kernel.output import FORMATS, LEVELS, SUMMARIES

if TYPE_CHECKING:
    from collections.abc import Mapping

    from atlassian_offline_mcp.kernel.output import Level

# The level of each -v given, from none: warning, then info, then debug.
VERBOSITY: tuple[Level, ...] = ("warning", "info", "debug")
# The settings of a sign-in by API token: a command that signs in reads them, if only
# to say that they go unused.
SIGN_IN = ("email", "api_token")


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


def add_output_options(parser: argparse.ArgumentParser, *, result: bool = True) -> None:
    """Add -q, -v and --log-level, which exclude one another, then --format and --summary.

    Each of the three sets ``level``: warning by default, info with -v, debug with -vv,
    error with -q. Without ``result``, for a command whose output is its own, such as a
    protocol, --format and --summary are not offered, and take their defaults.
    """
    parser.set_defaults(level=VERBOSITY[0], format=FORMATS[0], summary=SUMMARIES[0])
    levels = parser.add_mutually_exclusive_group()
    levels.add_argument(
        "-q",
        dest="level",
        action="store_const",
        const="error",
        help="say errors alone, and write no result as text",
    )
    levels.add_argument(
        "-v", dest="level", action=Verbose, nargs=0, help="say more: info with -v, debug with -vv"
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
    return (config, data_dir, site), {"data_dir": "data_dir", "site": "site"}


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


def email_without_token(
    _arguments: argparse.Namespace, settings: Mapping[str, object]
) -> dict[str, str]:
    """Without an API token, the browser's session signs in, and an email goes unused."""
    if settings["api_token"] is not None:
        return {}
    return {"email": "without an API token, the browser's session signs in"}


def token_without_email(
    _arguments: argparse.Namespace, settings: Mapping[str, object]
) -> str | None:
    """Refuse an API token without the email of its account, with which it signs in."""
    if settings["api_token"] is None or settings["email"] is not None:
        return None
    return "email: not set; an API token signs in with its account's email"


def signed_in_by(_arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say how the run signs in: by the API token when one is set, else by the saved session."""
    by = "an API token" if settings["api_token"] is not None else "the session saved by login"
    return (f"sign-in: {by}",)


def site_not_set(_arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse a run that reaches the site when none is set."""
    if settings["site"] is not None:
        return None
    return "site: not set; add it to the settings or pass --site"


def endpoint_elsewhere(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse an embedding endpoint off this machine without the run's word, or over http."""
    return refused_endpoint(
        str(settings["embedding_url"]), remote_allowed=arguments.allow_remote_embeddings
    )


def endpoint_by_meaning(
    arguments: argparse.Namespace, settings: Mapping[str, object]
) -> str | None:
    """Refuse the endpoint as ``endpoint_elsewhere`` does, unless the lexical mode embeds none."""
    if settings["search_mode"] == "lexical":
        return None
    return endpoint_elsewhere(arguments, settings)

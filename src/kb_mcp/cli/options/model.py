"""``model``'s declaration; ``cli.commands.model`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    endpoint_elsewhere,
    model_name,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def model_named(arguments: argparse.Namespace, _settings: Mapping[str, object]) -> dict[str, str]:
    """Check the model named on the command line, if any, in place of the setting."""
    return {"model": "replaced by the model named"} if arguments.name else {}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Declared],
) -> None:
    """Add ``model`` to the command."""
    parser = subparsers.add_parser(
        "model",
        help="check the embedding model and its endpoint",
        epilog=(
            "With --format json: name and dimensions, the model's; url, the endpoint;"
            " digest, the model's, empty when the endpoint reports none."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    remote = add_embedding_options(parser)
    action = parser.add_argument("action", choices=("check",))
    name = parser.add_argument(
        "name", nargs="?", type=model_name, help="the model to check; by default, the setting"
    )
    parser.set_defaults(
        command=Command(
            "model",
            "kb_mcp.cli.commands.model",
            reads=("model", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote, action, name),
            unapplied=model_named,
            refused=endpoint_elsewhere,
        )
    )

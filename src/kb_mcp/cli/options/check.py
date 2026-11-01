"""``check``'s declaration; ``cli.commands.check`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.sources.declaration import Declared

# The core's settings, by path, in the model's order, before the accounts' and the
# sources', then after them: check shows them all.
BEFORE_THE_REGISTRY = (
    "data_dir",
    "model",
    "search_mode",
    "chunking",
    "embedding_url",
    "embedding_api_key",
)
AFTER_THE_REGISTRY = (
    "logs.dir",
    "telemetry.endpoint",
    "rerank.enabled",
    "rerank.url",
    "rerank.model",
    "rerank.depth",
)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``check`` to the command, which reads every setting of the registry's model."""
    parser = subparsers.add_parser(
        "check",
        help="validate the settings and the data directory",
        epilog=(
            "With --format json: settings, secrets masked; layers, the layer of each setting"
            " that one gave; ignored, each value ignored, with its setting, layer and why."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "check",
            "kb_mcp.cli.commands.check",
            reads=(
                *BEFORE_THE_REGISTRY,
                *(path for account in accounts_of(sources).values() for path in account.paths),
                *(path for declared in sources for path in declared.paths),
                *AFTER_THE_REGISTRY,
            ),
            flags=flags,
            actions=actions,
        )
    )

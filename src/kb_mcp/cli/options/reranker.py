"""``reranker``'s declaration; ``cli.commands.reranker`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options
from kb_mcp.kernel.names import MODEL_NAME

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def reranker_name(value: str) -> str:
    """Take a reranking model's name given on the command line as the setting takes it."""
    if not MODEL_NAME.fullmatch(value):
        message = "the name of a reranking model, such as qwen3-reranker-0.6b"
        raise argparse.ArgumentTypeError(message)
    return value


def reranker_named(
    arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> dict[str, str]:
    """Check the model named on the command line, if any, in place of the setting."""
    return {"rerank.model": "replaced by the model named"} if arguments.name else {}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Declared],
) -> None:
    """Add ``reranker`` to the command."""
    parser = subparsers.add_parser(
        "reranker",
        help="check the reranking server and its model",
        epilog=(
            "With --format json: model, the one checked; url, the server; served, the"
            " models that it lists; answering and unrelated, the probe's scores; depth and"
            " seconds, a request of rerank.depth texts as long as a search sends, timed."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    action = parser.add_argument("action", choices=("check",))
    name = parser.add_argument(
        "name", nargs="?", type=reranker_name, help="the model to check; by default, the setting"
    )
    parser.set_defaults(
        command=Command(
            "reranker",
            "kb_mcp.cli.commands.reranker",
            reads=("rerank.url", "rerank.model", "rerank.depth"),
            flags=flags,
            actions=(*actions, action, name),
            unapplied=reranker_named,
        )
    )

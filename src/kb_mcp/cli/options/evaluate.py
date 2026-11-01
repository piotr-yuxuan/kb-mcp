"""``eval``'s declaration; ``cli.commands.evaluate`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from argcomplete.completers import FilesCompleter

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_elsewhere,
    model_name,
)
from kb_mcp.kernel.chunking import CHUNKINGS

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def models_named(arguments: argparse.Namespace, _settings: Mapping[str, object]) -> dict[str, str]:
    """Evaluate the models that --model names, if any, in place of the setting."""
    return {"model": "replaced by --model"} if arguments.model else {}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Declared],
) -> None:
    """Add ``eval`` to the command."""
    parser = subparsers.add_parser(
        "eval",
        help="measure search and ask on golden questions, by mode, model and chunking",
        epilog=(
            "With --format json: runs, each model's and chunking's measures of search and"
            " ask by mode and group, with its ranks, times, costs and tests; choices, each"
            " model's default chunking by the rule; results, the file that keeps them."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    remote = add_embedding_options(parser)
    golden = parser.add_argument("golden", type=Path, help="a YAML file of golden questions")
    golden.completer = FilesCompleter(["yaml", "yml"])
    models = parser.add_argument(
        "--model",
        action="append",
        type=model_name,
        help="a model to evaluate, as the endpoint names it; by default, the setting",
    )
    chunkings = parser.add_argument(
        "--chunking",
        action="append",
        choices=CHUNKINGS,
        help="a chunking to evaluate; by default, every one",
    )
    parser.set_defaults(
        command=Command(
            "eval",
            "kb_mcp.cli.commands.evaluate",
            reads=("data_dir", "model", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote, golden, models, chunkings),
            writes=True,
            unapplied=models_named,
            refused=endpoint_elsewhere,
            files=("golden",),
        )
    )

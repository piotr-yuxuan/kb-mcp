"""``eval``'s declaration; ``cli.commands.evaluate`` runs it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from argcomplete.completers import FilesCompleter

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_elsewhere,
    model_name,
)

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping


def models_named(arguments: argparse.Namespace, _settings: Mapping[str, object]) -> dict[str, str]:
    """Evaluate the models that --model names, if any, in place of the setting."""
    return {"model": "replaced by --model"} if arguments.model else {}


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``eval`` to the command."""
    parser = subparsers.add_parser(
        "eval",
        help="measure lexical, semantic and hybrid search on golden questions",
        epilog=(
            "With --format json: runs, each model's measures by mode, question and group,"
            " with its ranks, times and tests; results, the file that keeps them."
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
    parser.set_defaults(
        command=Command(
            "eval",
            "atlassian_offline_mcp.cli.commands.evaluate",
            reads=("data_dir", "model", "embedding_url", "embedding_api_key"),
            flags=flags,
            actions=(*actions, remote, golden, models),
            writes=True,
            unapplied=models_named,
            refused=endpoint_elsewhere,
            files=("golden",),
        )
    )

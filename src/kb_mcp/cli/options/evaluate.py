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
from kb_mcp.kernel.names import CHUNKINGS

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def models_named(arguments: argparse.Namespace, _settings: Mapping[str, object]) -> dict[str, str]:
    """Evaluate one model that --model names in place of the setting; of two, it is the control."""
    return {"model": "replaced by --model"} if len(set(arguments.model or ())) == 1 else {}


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Source],
) -> None:
    """Add ``eval`` to the command."""
    parser = subparsers.add_parser(
        "eval",
        help="measure search and ask on golden questions, by mode, model and chunking",
        epilog=(
            "With --format json: indexes, each model's and chunking's measures of search and"
            " ask by mode and group, with its ranks, times and costs, and the documents that it"
            " indexed, by source and type, and their digest; verdicts, the default"
            " rules' verdicts, the search mode's for each model and chunking, then the"
            " chunking's for each model, then the embedding model's for each chunking of two"
            " models or more, each arm a model in a mode; skipped, the golden questions left"
            " out, each with its ref and why; results, the file that keeps them."
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
            reads=(
                "data_dir",
                "model",
                "search_mode",
                "chunking",
                "embedding_url",
                "embedding_api_key",
            ),
            flags=flags,
            actions=(*actions, remote, golden, models, chunkings),
            writes=True,
            unapplied=models_named,
            refused=endpoint_elsewhere,
            files=("golden",),
        )
    )

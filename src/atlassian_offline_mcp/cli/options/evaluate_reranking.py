"""``eval-rerank``'s declaration; ``cli.commands.evaluate_reranking`` runs it."""

from __future__ import annotations

import argparse
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
)
from atlassian_offline_mcp.kernel.reranking import BAR_DEPTHS, DEPTHS

if TYPE_CHECKING:
    from collections.abc import Mapping


def depth(value: str) -> int:
    """Read --depth: documents reranked, within the depths that a reranking may have."""
    if not value.isdecimal() or int(value) not in DEPTHS:
        message = f"a whole number from {DEPTHS.start} to {DEPTHS[-1]}"
        raise argparse.ArgumentTypeError(message)
    return int(value)


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say what the run measures and what it asks of the reranking server, before it acts."""
    depths = sorted(set(arguments.depth or BAR_DEPTHS))
    measures = (
        f"reranking: depths {', '.join(map(str, depths))}, in the {settings['search_mode']} mode,"
        f" by {settings['rerank.model']} at {settings['rerank.url']}"
    )
    costs = (
        f"each question: a search not reranked, then {sum(depths)} texts scored in all;"
        f" the bar decides on depths {', '.join(map(str, BAR_DEPTHS))} alone"
    )
    return measures, costs


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``eval-rerank`` to the command."""
    parser = subparsers.add_parser(
        "eval-rerank",
        help="measure search reranked at each depth on golden questions, against the bar",
        epilog=(
            "With --format json: arms, each depth's measures of search and ask by group,"
            " with its ranks, times, tokens and Recall@N, depth 0 the order not reranked;"
            " decision, the bar's verdicts and default depth; results, the file that keeps"
            " them."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    remote = add_embedding_options(parser)
    golden = parser.add_argument("golden", type=Path, help="a YAML file of golden questions")
    golden.completer = FilesCompleter(["yaml", "yml"])
    depths = parser.add_argument(
        "--depth",
        action="append",
        type=depth,
        help=(
            "documents reranked, as one arm; by default"
            f" {', '.join(map(str, BAR_DEPTHS))}, the bar's"
        ),
    )
    parser.set_defaults(
        command=Command(
            "eval-rerank",
            "atlassian_offline_mcp.cli.commands.evaluate_reranking",
            reads=(
                "data_dir",
                "model",
                "chunking",
                "search_mode",
                "embedding_url",
                "embedding_api_key",
                "rerank.url",
                "rerank.model",
            ),
            flags=flags,
            actions=(*actions, remote, golden, depths),
            writes=True,
            described=described,
            refused=endpoint_elsewhere,
            files=("golden",),
        )
    )

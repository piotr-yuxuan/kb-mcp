"""``index``'s declaration; ``cli.commands.index`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def meaning_waits(
    _arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say first, whatever the mode, that what changed has no vectors until ``embed`` runs."""
    return ("then: documents added or changed have no vectors until kb-mcp embed",)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Declared],
) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser(
        "index",
        help="update the search index of the mirror's words to what changed",
        epilog=(
            "With --format json: report, the documents held by type, their sections, the"
            " files skipped, the documents copied, added, replaced and removed, those"
            " awaiting vectors, null when the index names no model, unchanged, whether"
            " nothing was written, and rebuilt, why the index was rebuilt whole, if it was;"
            " index, its path; model and pruned, null."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    rebuild = parser.add_argument(
        "--rebuild", action="store_true", help="build the index whole, keeping nothing of it"
    )
    parser.set_defaults(
        command=Command(
            "index",
            "kb_mcp.cli.commands.index",
            reads=("data_dir",),
            flags=flags,
            actions=(*actions, rebuild),
            writes=True,
            described=meaning_waits,
        )
    )

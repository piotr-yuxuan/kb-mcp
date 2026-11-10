"""``index``'s declaration; ``cli.commands.index`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def meaning_waits(
    _arguments: argparse.Namespace, _settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say first, whatever the mode, that what changed has no vectors until ``embed`` runs."""
    return ("then: documents added or changed have no vectors until kb-mcp embed",)


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Source],
) -> None:
    """Add ``index`` to the command."""
    parser = subparsers.add_parser(
        "index",
        help="update the search index of the mirror's words to what changed",
        epilog=(
            "With --format json: `ending` (done, failed); `counts`, null when nothing was"
            " built: `types`, the documents held by type, `sections`, `persons`, the join's"
            " `count`, the names `ambiguous` and the aliases `unused`, the documents"
            " `copied`, `added`, `replaced` and `removed`,"
            " `awaiting`, those awaiting vectors, null when the index names no model,"
            " `unchanged`, whether nothing was written, `rebuilt`, why the index was rebuilt"
            " whole, if it was, and `index`, its path; `problems`, each file skipped, or why"
            " nothing was built, and `warnings`, each name that could be several persons and"
            " each alias that changed nothing, each with its `where` and `reason`."
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

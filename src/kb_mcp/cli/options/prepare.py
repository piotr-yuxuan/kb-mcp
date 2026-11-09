"""``prepare``'s declaration, from the registry's; ``cli.commands.sources`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sources import PREPARE, prepare_described
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option
from kb_mcp.cli.options._sources import choice_refused, left_unapplied, source_groups
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.sources.declaration import Source


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``prepare`` to the command, for every source of the registry.

    The settings read are each account's first, which links resolve by, the data
    directory and the settings of each source read in place: a source that keeps a store
    is prepared from what it holds, whatever its settings cover. A source named comes with
    the others, after the options or before them: its ``dest`` is ``source``, as
    ``sources`` holds the registry.
    """
    parser = subparsers.add_parser(
        "prepare",
        help="turn what each source holds into the Markdown mirror",
        epilog=(
            "With --format json: exit_status, the run's; sources, a row per source taken, in"
            " the registry's order, each with its source, its outcome (done, failed,"
            " interrupted, not run) and its result, null when it gave none: its outcome, and"
            " under mirrored what the source's documents became, null when it did not run:"
            " documents, how many it prepared; for Confluence and Jira, converted, the"
            " conversions pandoc ran, and reused, those the cache gave, a document's file and"
            " a space's tree being one each; changes, the files written, unchanged and"
            " removed; unsupported, what the mirror does not show, by name; problems, each by"
            " its place and why; elsewhere, those that it found reading the other source's,"
            " by that source, which fail nothing of its own. For the work log: documents;"
            " changes; html, the HTML transcripts left out; warnings; problems, each with what"
            " it held back; in a dry run, documents, to_convert, to_remove, html, warnings and"
            " problems."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    source = parser.add_argument(
        "source",
        nargs="*",
        choices=[declared.name for declared in sources],
        help="the sources to prepare, given together; by default those that keep a store, and"
        " each one read in place that is configured",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="count what a run would convert and remove, where a source can tell; write nothing",
    )
    source_groups(parser, sources)
    parser.set_defaults(
        command=Command(
            PREPARE,
            "kb_mcp.cli.commands.sources",
            reads=(
                *(account.paths[0] for account in accounts_of(sources).values()),
                "data_dir",
                *(path for each in sources if each.fetcher is None for path in each.paths),
            ),
            flags=flags,
            actions=(*actions, source),
            writes=True,
            dry_run=True,
            unapplied=left_unapplied,
            described=prepare_described,
            refused=choice_refused,
            programs=("pandoc",),
        )
    )

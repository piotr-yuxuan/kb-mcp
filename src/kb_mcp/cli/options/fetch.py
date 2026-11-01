"""``fetch``'s declaration, from the registry's; ``cli.commands.sources`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sources import described
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option
from kb_mcp.cli.options._sources import add_source_options, refused, unapplied
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.sources.declaration import Declared


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``fetch`` to the command, for the sources of the registry that have a fetcher.

    The settings read are each account's that they name, once, the data directory, each
    of those sources'. A source named comes with the others, after the options or before
    them: its ``dest`` is ``source``, as ``sources`` holds the registry.
    """
    fetched = [declared for declared in sources if declared.fetcher is not None]
    parser = subparsers.add_parser(
        "fetch",
        help="bring what changed in each source into its store",
        epilog=(
            "With --format json: exit_status, the run's; sources, a row per source taken,"
            " in the registry's order, each with its source, its outcome (done, failed,"
            " sign in, interrupted, not run) and its result, null when it gave none: its"
            " outcome, and under downloaded, null when the fetch could not start: report,"
            " the counts of what the fetch did, or with --dry-run would do; failed_targets,"
            " the targets that failed; status, its exit status; windows, each target's: its"
            " start, end and reason, and its coverage, extended, capped at a failure, held,"
            " or null when not written; dry_run, whether the fetch only planned."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    source = parser.add_argument(
        "source",
        nargs="*",
        choices=[declared.name for declared in fetched],
        help="the sources to fetch, given together; by default each one configured",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="say what a run would fetch, and fetch nothing"
    )
    options, replacing = add_source_options(parser, fetched)
    parser.set_defaults(
        command=Command(
            "fetch",
            "kb_mcp.cli.commands.sources",
            reads=(
                *(path for account in accounts_of(fetched).values() for path in account.paths),
                "data_dir",
                *(path for declared in fetched for path in declared.paths),
            ),
            flags={**flags, **replacing},
            actions=(*actions, *options, source),
            writes=True,
            dry_run=True,
            unapplied=unapplied,
            described=described,
            refused=refused,
        )
    )

"""``fetch``'s declaration, from the registry's; ``cli.commands.sources`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sources import FETCH, chosen_to_fetch, fetch_described, given
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option
from kb_mcp.cli.options._sources import add_source_options, choice_refused, left_unapplied
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no fetch can run with, before anything is asked: the first found.

    A source named but not configured, or none left; then what each source taken refuses,
    by its declaration's ``refused``, such as an option that does not read, or a site not
    set: no source's options are read unless it is taken.
    """
    taken, _ = chosen_to_fetch(arguments, settings)
    faults = [
        choice_refused(arguments, settings),
        *(
            declared.refused(given(arguments, declared.options), settings)
            for declared in taken
            if declared.refused is not None
        ),
    ]
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply, and why.

    What it does not apply of the sources left out; then what each source taken does not
    apply, by its declaration's ``unapplied``, such as an email without the API token that
    it signs in with.
    """
    taken, _ = chosen_to_fetch(arguments, settings)
    unused = left_unapplied(arguments, settings)
    for declared in taken:
        options = given(arguments, declared.options)
        unused |= declared.unapplied(options, settings) if declared.unapplied else {}
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
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
            "With --format json: `exit_status`, the run's; `sources`, a row per source"
            " taken, in the registry's order, each with its `source`, its `ending` (done,"
            " failed, sign in again, interrupted, not run), its `counts`, null when it gave"
            " none, and its `problems` and `warnings`, each with its `where` and `reason`,"
            " a target, a document or a file and why it failed. The counts: each count by"
            " its name, of what the fetch did, or with --dry-run would do; `windows`, each"
            " target's: its `target`, `start`, `end` and `reason`, and its `coverage`,"
            " extended, capped at a failure, held, or null when not written; `dry_run`,"
            " whether the fetch only planned."
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
            FETCH,
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
            described=fetch_described,
            refused=refused,
        )
    )

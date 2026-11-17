"""``fetch``'s declaration, from the registry's; ``cli.commands.sources`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import FETCH, Command
from kb_mcp.cli.domain.sources import chosen_to_fetch, fetch_described, given, refusals
from kb_mcp.cli.options._common import add_output_options, add_settings_options, add_yes_option
from kb_mcp.cli.options._sources import add_source_options, choice_refused, left_unapplied

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no fetch can run with, before anything is asked: the first found.

    An option of a setting of several sources given when the sources named leave more
    than one of them, as ``Command.narrowed`` says, naming them; a source named but not
    configured, or none left; then what the settings of each source named refuse, by its
    connector's light check (``refusals``), such as a site not set: one taken by default
    fails its unit instead, as the echo says; then what each source taken refuses of its
    options, such as one that does not read. No source's options are read unless it is
    taken.
    """
    taken, _ = chosen_to_fetch(arguments, settings)
    faults = [
        *(
            f"{flag}: overrides a setting of one source; name one of {', '.join(left)}"
            for flag, left in arguments.command.narrowed(arguments).items()
            if len(left) > 1 and getattr(arguments, flag) is not None
        ),
        choice_refused(arguments, settings),
        *(why for name, why in refusals(taken, settings).items() if name in arguments.source),
        *(
            declared.connector.options_refused(given(arguments, declared.connector.flags))
            for declared in taken
            if declared.connector.options_refused is not None
        ),
    ]
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply, and why.

    What it does not apply of the sources left out; then what each source taken does not
    apply, by its connector's ``unapplied``, such as an email without the API token that
    it signs in with.
    """
    taken, _ = chosen_to_fetch(arguments, settings)
    unused = left_unapplied(arguments, settings)
    for declared in taken:
        connector = declared.connector
        options = given(arguments, connector.flags)
        unused |= connector.unapplied(declared, options, settings) if connector.unapplied else {}
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``fetch`` to the command, for the sources that have a fetcher.

    The settings read are the data directory and each of those sources'. A source named
    comes with the others, after the options or before them: its ``dest`` is ``source``,
    as ``sources`` holds the sources.
    """
    fetched = [declared for declared in sources if declared.connector.fetcher is not None]
    parser = subparsers.add_parser(
        "fetch",
        help="bring what changed in each source into its store",
        epilog=(
            "With --format json: `run`, the run's id, which refresh --resume takes, but"
            " for a dry run, which records nothing, as its text says after the id;"
            " `exit_status`, the run's; `sources`, a row per source"
            " taken, in the registry's order, each with its `source`, its `ending` (done,"
            " failed, sign in again, interrupted, not run), its `counts`, null when it gave"
            " none, and its `problems` and `warnings`, each with its `where` and `reason`,"
            " a scope, a document or a file and why it failed. Confluence's and Jira's"
            " counts: each count by its name, of what the fetch did, or with --dry-run"
            " would do; `windows`, each scope's: its `scope`, by its source, type and key,"
            " its `start`, `end` and `reason`, and its `coverage`, extended, capped at a"
            " failure, held, or null when not written; `dry_run`, whether the fetch only"
            " planned. The work log's: `documents`, those read; `new` and `changed`, of"
            " another revision; `gone`, those that a read without a problem no longer found;"
            " `html`, the HTML transcripts left out; `held_back`, by each problem's place,"
            " what keeps its last copy."
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
    options, scoped = add_source_options(parser, fetched)
    parser.set_defaults(
        command=Command(
            FETCH,
            "kb_mcp.cli.commands.sources",
            reads=("data_dir", *(path for declared in fetched for path in declared.paths)),
            flags=flags,
            scoped=scoped,
            actions=(*actions, *options, source),
            writes=True,
            dry_run=True,
            unapplied=unapplied,
            described=fetch_described,
            refused=refused,
            stages=(FETCH,),
        )
    )

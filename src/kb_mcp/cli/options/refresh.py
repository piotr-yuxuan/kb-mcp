"""``refresh``'s declaration, from the registry's; ``cli.commands.refresh`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import FETCH, STAGES, Command
from kb_mcp.cli.domain.sources import (
    chosen,
    fetch_described,
    fetch_flags,
    given,
    prepare_described,
    refusals,
)
from kb_mcp.cli.options import fetch
from kb_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_elsewhere,
)
from kb_mcp.cli.options._sources import add_source_options
from kb_mcp.kernel.names import RUN_ID

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Source


def run_id(text: str) -> str:
    """Take a run's id as given on the command line: 16 lower-case hex digits."""
    if not RUN_ID.fullmatch(text):
        message = "a run's id, 16 lower-case hex digits, as a recorded run's result names it"
        raise argparse.ArgumentTypeError(message)
    return text


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no refresh can run with, before anything is asked: the first found.

    A resume runs the configuration that its run recorded: a source named, or an option
    of a source, which would change it, is refused, naming it. Else what a fetch
    refuses, as ``fetch``'s declaration says, then an embedding endpoint off this machine
    without the run's word.
    """
    if arguments.resume is None:
        return fetch.refused(arguments, settings) or endpoint_elsewhere(arguments, settings)
    flags = fetch_flags(arguments.sources)
    named = [
        *arguments.source,
        *(flag for flag, value in sorted(given(arguments, flags).items()) if value is not None),
    ]
    if not named:
        return None
    return f"{named[0]}: would change the configuration that --resume runs, as its run recorded it"


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say what each stage takes: fetch's and prepare's sources, then index's and embed's work.

    A source whose fetch will not run, by its light check (``refusals``), asked once for
    both stages' lines, is not prepared either, and its prepare's line says that alone.
    """
    taken, _ = chosen(arguments, settings, FETCH)
    unfetched = refusals(taken, settings)
    return (
        *(f"fetch: {line}" for line in fetch_described(arguments, settings, unfetched)),
        *(f"prepare: {line}" for line in prepare_described(arguments, settings, unfetched)),
        "index: the words of the mirror's files that changed, whichever source wrote them",
        "embed: the vectors of the chunks that the index lacks, then the vector cache pruned",
    )


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Source],
) -> None:
    """Add ``refresh`` to the command, for the sources that have a fetcher.

    The settings read are fetch's, prepare's and embed's. A source named comes with the
    others, after the options or before them: its ``dest`` is ``source``, as ``sources``
    holds the sources.
    """
    fetched = [each for each in sources if each.connector.fetcher is not None]
    parser = subparsers.add_parser(
        "refresh",
        help="bring each source, the mirror, the index and its vectors up to date: one run",
        epilog=(
            "One run of fetch, prepare, index and embed, recorded under <data>/runs/<run id>/:"
            " fetch and prepare a unit per source, a source's prepare only once its fetch"
            " is done; index and embed over the whole. --resume runs again the units of a"
            " run, any command's, that did not end done, by the configuration that it"
            " recorded. With --format json: `run`, the run's id; `exit_status`, the run's;"
            " `units`, each unit's last entry, in the order in which they run: its `stage`,"
            " its `source`, null for index and embed, its `ending` (done, failed, sign in"
            " again, interrupted, not run), its `counts`, as its stage's command writes them,"
            " its `problems` and `warnings`, and `invocation`, when the invocation that gave"
            " it started."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    source = parser.add_argument(
        "source",
        nargs="*",
        choices=[each.name for each in fetched],
        help="the sources to refresh, given together; by default each one configured",
    )
    remote = add_embedding_options(parser)
    resume = parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        type=run_id,
        help="run again the units of this run that did not end done, by its configuration",
    )
    options, scoped = add_source_options(parser, fetched)
    parser.set_defaults(
        command=Command(
            "refresh",
            "kb_mcp.cli.commands.refresh",
            reads=(
                "data_dir",
                *(path for each in sources for path in each.paths),
                "model",
                "chunking",
                "embedding_url",
                "embedding_api_key",
            ),
            flags=flags,
            scoped=scoped,
            actions=(*actions, *options, remote, resume, source),
            writes=True,
            unapplied=fetch.unapplied,
            described=described,
            refused=refused,
            programs=("pandoc",),
            stages=STAGES,
        )
    )

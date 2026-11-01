"""``sync``'s declaration, from the registry's; ``cli.commands.sync`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sync import chosen, described, given
from kb_mcp.cli.options._common import (
    add_embedding_options,
    add_output_options,
    add_settings_options,
    add_yes_option,
    endpoint_by_meaning,
)
from kb_mcp.cli.options.index import INDEX_SETTINGS, by_words_alone
from kb_mcp.sources.registry import accounts_of

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no sync can run with, before anything is asked: the first found.

    A source included but not configured, or none left; an embedding endpoint that
    ``index`` would refuse, unless a dry run, which builds no index; then what each
    source taken refuses, by its declaration's ``refused``, such as an option that does
    not read: no source's options are read unless it is taken.
    """
    taken, left = chosen(arguments, settings)
    faults = [
        f"--include {declared.name}: not configured; set {declared.paths[0]}"
        for declared in arguments.sources
        if declared.name in (arguments.include or ())
        and left.get(declared.name) == "not configured"
    ]
    faults.append(None if taken else "nothing to sync: no source is configured and chosen")
    faults.append(None if arguments.dry_run else endpoint_by_meaning(arguments, settings))
    faults += [
        declared.refused(given(arguments, declared.options), settings)
        for declared in taken
        if declared.refused is not None
    ]
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply, and why.

    The settings of the sources left out, and those of an account that no source taken
    names; the index's in a dry run, which builds none, and else those that the lexical
    mode does not use; then what each source taken does not apply, by its declaration's
    ``unapplied``, such as an email without the API token that it signs in with.
    """
    taken, left = chosen(arguments, settings)
    signing = {declared.account.name for declared in taken if declared.account is not None}
    unused = {
        path: f"{declared.name} {left[declared.name]}"
        for declared in arguments.sources
        if declared.name in left
        for path in declared.paths
    }
    unused |= {
        path: f"no source of the {declared.account.name} account in this sync"
        for declared in arguments.sources
        if declared.account is not None and declared.account.name not in signing
        for path in declared.account.paths
    }
    if arguments.dry_run:
        unused |= dict.fromkeys(INDEX_SETTINGS, "a dry run builds no index")
    else:
        unused |= by_words_alone(arguments, settings)
    for declared in taken:
        options = given(arguments, declared.options)
        unused |= declared.unapplied(options, settings) if declared.unapplied else {}
    return unused


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``sync`` to the command, its sources and their options the registry's.

    ``--include`` and ``--exclude`` take the sources' names; each option that a source
    declares is added once, and none has a default, so that one given is told from one
    not given. The settings read are each account's, once, the data directory, each
    source's, then the index's. Raises ValueError, naming the source, for an option that
    takes a flag of ``sync``'s own, as the registry's other rules do.
    """
    parser = subparsers.add_parser(
        "sync",
        help=("bring the configured sources up to date: fetch each, prepare each, then the index"),
        epilog=(
            "With --format json: exit_status, the run's; steps, a row per step and source,"
            " the fetch of each source that has a fetcher, then the prepare of each, then"
            " the index, each with its step (fetch, prepare, index), its source, null for"
            " the index, its outcome (done, failed, sign in, interrupted, not run) and its"
            " result, null when it gave none: a fetch's or a prepare's outcome, and what"
            " the source's own command gives, under downloaded or mirrored; the index's,"
            " as index gives it."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    names = [declared.name for declared in sources]
    choosing = parser.add_mutually_exclusive_group()
    include = choosing.add_argument(
        "--include",
        action="append",
        choices=names,
        help="sync this source alone, if configured; repeat for more",
    )
    exclude = choosing.add_argument(
        "--exclude",
        action="append",
        choices=names,
        help="sync every configured source but this one; repeat for more",
    )
    options = {flag: option for declared in sources for flag, option in declared.options.items()}
    try:
        declared_options = tuple(
            parser.add_argument(option.flag, type=option.type, help=option.help)
            for option in options.values()
        )
        remote = add_embedding_options(parser)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="say what the run would fetch, and change where a source can tell; write nothing",
        )
    except argparse.ArgumentError as error:
        flag = error.argument_name
        named = next(declared.name for declared in sources if flag in declared.options)
        message = f"source {named!r}: option {flag}: a flag of sync's own"
        raise ValueError(message) from error
    parser.set_defaults(
        command=Command(
            "sync",
            "kb_mcp.cli.commands.sync",
            reads=(
                *(path for account in accounts_of(sources).values() for path in account.paths),
                "data_dir",
                *(path for declared in sources for path in declared.paths),
                *INDEX_SETTINGS,
            ),
            flags=flags,
            actions=(*actions, include, exclude, *declared_options, remote),
            writes=True,
            dry_run=True,
            unapplied=unapplied,
            described=described,
            refused=refused,
            programs=("pandoc",),
        )
    )

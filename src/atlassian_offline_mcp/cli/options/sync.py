"""``sync``'s declaration; ``cli.commands.sync`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.domain.sync import SITE_SETTINGS, SOURCES, chosen, described
from atlassian_offline_mcp.cli.options._common import (
    SIGN_IN,
    add_output_options,
    add_settings_options,
    add_yes_option,
    email_without_token,
    site_not_set,
    token_without_email,
)
from atlassian_offline_mcp.cli.options.download import add_period_options, period_refused
from atlassian_offline_mcp.kernel.content import SOURCE_NAMES

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no sync can run with, before anything is asked: the first found.

    A source included but not configured, or none left; with Confluence or Jira, no
    site, an API token without its email, or an option of the period that does not read.
    The period's options are not read when no source uses them.
    """
    taken, left = chosen(arguments, settings)
    unready = [
        f"--include {source.name}: not configured; set {source.settings[0]}"
        for source in SOURCES
        if source.name in (arguments.include or ()) and left.get(source.name) == "not configured"
    ]
    faults = [*unready, None if taken else "nothing to sync: no source is configured and chosen"]
    if any(source.step == "atlassian" for source in taken):
        faults += [
            site_not_set(arguments, settings),
            token_without_email(arguments, settings),
            period_refused(arguments),
        ]
    return next((fault for fault in faults if fault is not None), None)


def unapplied(arguments: argparse.Namespace, settings: Mapping[str, object]) -> dict[str, str]:
    """Name what the run does not apply, and why.

    The settings of the sources left out, the site's when no Atlassian source is taken,
    and else an email without an API token.
    """
    taken, left = chosen(arguments, settings)
    unused = {
        setting: f"{source.name} {left[source.name]}"
        for source in SOURCES
        if source.name in left
        for setting in source.settings
    }
    if any(source.step == "atlassian" for source in taken):
        return unused | email_without_token(arguments, settings)
    return unused | dict.fromkeys(SITE_SETTINGS, "no Atlassian source in this sync")


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``sync`` to the command."""
    parser = subparsers.add_parser(
        "sync",
        help="bring the configured sources up to date: download, mirror, then the work log",
        epilog=(
            "With --format json: exit_status, the run's; steps, a row per step (download,"
            " mirror, worklog), each with its step, its outcome (done, failed, sign in,"
            " interrupted, not run) and its result, as its own command gives it."
        ),
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    choosing = parser.add_mutually_exclusive_group()
    include = choosing.add_argument(
        "--include",
        action="append",
        choices=SOURCE_NAMES,
        help="sync this source alone, if configured; repeat for more",
    )
    exclude = choosing.add_argument(
        "--exclude",
        action="append",
        choices=SOURCE_NAMES,
        help="sync every configured source but this one; repeat for more",
    )
    period = add_period_options(parser, max_file_mb=None)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="say what a run would fetch and what the work log would change; write nothing",
    )
    parser.set_defaults(
        command=Command(
            "sync",
            "atlassian_offline_mcp.cli.commands.sync",
            reads=(
                "site",
                *SIGN_IN,
                "data_dir",
                "sources.confluence.spaces",
                "sources.jira.projects",
                "sources.worklog.path",
                "sources.worklog.archives",
            ),
            flags=flags,
            actions=(*actions, include, exclude, *period),
            writes=True,
            dry_run=True,
            unapplied=unapplied,
            described=described,
            refused=refused,
            programs=("pandoc",),
        )
    )

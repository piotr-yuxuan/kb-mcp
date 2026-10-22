"""``download``'s declaration; ``cli.commands.download`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from atlassian_offline_mcp.cli.domain.command import Command
from atlassian_offline_mcp.cli.options._common import (
    SIGN_IN,
    add_output_options,
    add_settings_options,
    add_yes_option,
    email_without_token,
    site_not_set,
)
from atlassian_offline_mcp.kernel.content import PROJECT_KEY, SPACE_KEY
from atlassian_offline_mcp.sources.atlassian.domain.period import EPOCH, PeriodError, length, moment

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

DEFAULT_MAX_FILE_MB = 50


def key_of(pattern_name: str) -> Callable[[str], str]:
    """Return an argparse type that accepts a space key or a project key."""
    pattern = SPACE_KEY if pattern_name == "space" else PROJECT_KEY

    def check(text: str) -> str:
        if not pattern.fullmatch(text):
            message = f"not a {pattern_name} key: {text!r}"
            raise argparse.ArgumentTypeError(message)
        return text

    return check


def refused(arguments: argparse.Namespace, settings: Mapping[str, object]) -> str | None:
    """Refuse what no download can run with, before anything is asked: the first found.

    No site; no space nor project; a largest file under 1 MB; an option of the period
    that does not read. Whether one reads does not depend on when the run starts, so
    the epoch stands for it.
    """
    named = settings["sources.confluence.spaces"] or settings["sources.jira.projects"]
    faults = [
        site_not_set(arguments, settings),
        None if named else "nothing to download: name a --space or a --project",
        None if arguments.max_file_mb >= 1 else "--max-file-mb: at least 1",
    ]
    try:
        for option, text in (("--since", arguments.since), ("--until", arguments.until)):
            if text is not None:
                moment(text, EPOCH, option)
        if arguments.back is not None:
            length(arguments.back, "--back")
    except PeriodError as error:
        faults.append(str(error))
    return next((fault for fault in faults if fault is not None), None)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add ``download`` to the command."""
    parser = subparsers.add_parser(
        "download", help="download what changed in a period, with its files"
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    add_yes_option(parser)
    space = parser.add_argument(
        "--space", action="append", type=key_of("space"), help="a space key; repeat for more"
    )
    project = parser.add_argument(
        "--project", action="append", type=key_of("project"), help="a project key; repeat"
    )
    since = parser.add_argument(
        "--since", help="7d, 6mo, or an ISO date; by default, the start of what is covered"
    )
    back = parser.add_argument("--back", help="reach this much further back (6mo, 1y), or all")
    until = parser.add_argument("--until", help="an ISO date or time, excluded; by default, now")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what a run would fetch, and fetch nothing"
    )
    largest = parser.add_argument(
        "--max-file-mb", type=int, default=DEFAULT_MAX_FILE_MB, help="the largest file kept"
    )
    parser.set_defaults(
        command=Command(
            "download",
            "atlassian_offline_mcp.cli.commands.download",
            reads=(
                "site",
                *SIGN_IN,
                "data_dir",
                "sources.confluence.spaces",
                "sources.jira.projects",
            ),
            flags={
                **flags,
                "space": "sources.confluence.spaces",
                "project": "sources.jira.projects",
            },
            actions=(*actions, space, project, since, back, until, largest),
            writes=True,
            dry_run=True,
            unapplied=email_without_token,
            refused=refused,
        )
    )

"""``download``'s declaration; ``cli.commands.download`` runs it."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.domain.sync import given
from kb_mcp.cli.options._common import (
    SIGN_IN,
    SITE,
    add_option,
    add_output_options,
    add_settings_options,
    add_yes_option,
    of_atlassian,
    signed_in_by,
)
from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY
from kb_mcp.sources.atlassian.declared import (
    MAX_FILE_MB,
    PERIOD,
    SINCE,
    UNTIL,
    email_without_token,
    period_refused,
    site_not_set,
    token_without_email,
)
from kb_mcp.sources.atlassian.fetch.domain.period import DEFAULT_MAX_FILE_MB, period_rule

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from kb_mcp.sources.declaration import Declared


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

    No site; an API token without its email; no space nor project; the period's options,
    as ``period_refused`` says.
    """
    named = settings["sources.confluence.spaces"] or settings["sources.jira.projects"]
    faults = [
        site_not_set(arguments, settings),
        token_without_email(arguments, settings),
        None if named else "nothing to download: name a --space or a --project",
        period_refused(given(arguments, (option.flag for option in PERIOD))),
    ]
    return next((fault for fault in faults if fault is not None), None)


def described(arguments: argparse.Namespace, settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say how the run signs in, and where each target's window starts, by the rule."""
    since = getattr(arguments, SINCE.flag) is not None
    return (*signed_in_by(arguments, settings), period_rule(since=since))


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    sources: Sequence[Declared],
) -> None:
    """Add ``download`` to the command."""
    parser = subparsers.add_parser(
        "download",
        help="download what changed in a period, with its files",
        epilog=(
            "With --format json: exit_status, the run's; steps, a row per source with"
            " targets, confluence then jira, each with its step, download, its source, its"
            " outcome (done, failed, sign in) and its result, null when the fetch could not"
            " start: report, the counts of what the fetch did, or with --dry-run would do;"
            " failed_targets, the spaces or projects that failed; status, its exit status;"
            " windows, each target's: its start, end and reason, and its coverage,"
            " extended, capped at a failure, held, or null when not written; dry_run,"
            " whether the fetch only planned."
        ),
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
    period = (
        add_option(parser, SINCE),
        add_option(parser, UNTIL),
        add_option(parser, MAX_FILE_MB, DEFAULT_MAX_FILE_MB),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="say what a run would fetch, and fetch nothing"
    )
    parser.set_defaults(
        command=Command(
            "download",
            "kb_mcp.cli.commands.download",
            reads=(
                SITE,
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
            actions=(*actions, space, project, *period),
            writes=True,
            dry_run=True,
            unapplied=email_without_token,
            described=described,
            refused=of_atlassian(sources, refused),
        )
    )

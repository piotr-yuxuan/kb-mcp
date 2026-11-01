"""Confluence's and Jira's declarations: what each reads of the site, its table and roles.

Each resource type is a kind that the raw store keeps, fetched over a period that its
options give. Both sign in with one Atlassian account, its site's, name one fetcher and
one preparer, which read the kinds of the source that they run for from its
declaration, and share their light checks: the sign-in's, and the period's.
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from kb_mcp.kernel.names import PROJECT_KEY, SPACE_KEY
from kb_mcp.sources.atlassian.fetch.domain.period import (
    DEFAULT_MAX_FILE_MB,
    EPOCH,
    MAX_FILE_MB_FLAG,
    SINCE_FLAG,
    UNTIL_FLAG,
    PeriodError,
    moment,
    period_rule,
)
from kb_mcp.sources.declaration import Account, Declared, Option, ResourceType

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Mapping


def site_not_set(_given: object, settings: Mapping[str, object]) -> str | None:
    """Refuse a run that reaches the site when none is set."""
    if settings[SITE] is not None:
        return None
    return f"{SITE}: not set; add it to the settings or pass --site"


def token_without_email(_given: object, settings: Mapping[str, object]) -> str | None:
    """Refuse an API token without the email of its account, with which it signs in."""
    if settings[API_TOKEN] is None or settings[EMAIL] is not None:
        return None
    return f"{EMAIL}: not set; an API token signs in with its account's email"


def email_without_token(_given: object, settings: Mapping[str, object]) -> dict[str, str]:
    """Without an API token, the browser's session signs in, and an email goes unused."""
    if settings[API_TOKEN] is not None:
        return {}
    return {EMAIL: "without an API token, the browser's session signs in"}


ATLASSIAN = Account(
    name="atlassian",
    table="kb_mcp.sources.atlassian.settings:AtlassianAccount",
    settings=("site", "email", "api_token"),
    login="kb_mcp.sources.atlassian.fetch.app.login:signed_in",
    checks="kb_mcp.sources.atlassian.fetch.app.doctor:checks",
    refused=token_without_email,
    unapplied=email_without_token,
)
# The account's settings, by path: the site, then those of a sign-in by API token, its
# email and the token.
SITE, EMAIL, API_TOKEN = ATLASSIAN.paths
# The options of a fetch's period: from when, until when, and the largest file kept.
SINCE, UNTIL, MAX_FILE_MB = PERIOD = (
    Option(
        flag=SINCE_FLAG,
        help="12h, 7d, 6mo, an ISO date or time, or all; by default, each target's last fetch",
    ),
    Option(flag=UNTIL_FLAG, help="12h, 7d, or an ISO date or time, excluded; by default, now"),
    Option(
        flag=MAX_FILE_MB_FLAG,
        help=f"the largest file kept, in MB; {DEFAULT_MAX_FILE_MB} by default",
        type=int,
    ),
)


def key_of(name: str, rule: re.Pattern[str]) -> Callable[[str], str]:
    """Return an argparse type that takes a key by its rule, a space's or a project's."""

    def check(text: str) -> str:
        if not rule.fullmatch(text):
            message = f"not a {name} key: {text!r}"
            raise argparse.ArgumentTypeError(message)
        return text

    return check


# The options that replace a source's list for one run.
SPACE = Option(
    flag="--space",
    help="a space key, in place of the setting's; repeat for more",
    type=key_of("space", SPACE_KEY),
    setting="sources.confluence.spaces",
)
PROJECT = Option(
    flag="--project",
    help="a project key, in place of the setting's; repeat for more",
    type=key_of("project", PROJECT_KEY),
    setting="sources.jira.projects",
)
FETCHER = "kb_mcp.sources.atlassian.fetch.app.fetcher"
PREPARER = "kb_mcp.sources.atlassian.prepare.app.preparer"


def period_refused(options: Mapping[str, object]) -> str | None:
    """Refuse a largest file under 1 MB, or an option of the period that does not read.

    ``options`` holds the period's by flag, None when not given. Whether one reads does
    not depend on when the run starts, so the epoch stands for it.
    """
    largest = options[MAX_FILE_MB.flag]
    if isinstance(largest, int) and largest < 1:
        return f"{MAX_FILE_MB.flag}: at least 1"
    try:
        for option in (SINCE, UNTIL):
            text = options[option.flag]
            if isinstance(text, str):
                moment(text, EPOCH, option.flag)
    except PeriodError as error:
        return str(error)
    return None


def refused(options: Mapping[str, object], settings: Mapping[str, object]) -> str | None:
    """Refuse what no fetch of the site can run with: the first found.

    No site; an API token without its email; the period's options, as
    ``period_refused`` says.
    """
    faults = (
        site_not_set(options, settings),
        token_without_email(options, settings),
        period_refused(options),
    )
    return next((fault for fault in faults if fault is not None), None)


def described(options: Mapping[str, object], settings: Mapping[str, object]) -> tuple[str, ...]:
    """Say how the run signs in, and where each target's window starts, by the rule.

    By the API token when one is set, else by the saved session; --since given or not.
    """
    by = "an API token" if settings[API_TOKEN] is not None else "the session saved by login"
    return (f"sign-in: {by}", period_rule(since=options[SINCE.flag] is not None))


CONFLUENCE = Declared(
    name="confluence",
    summary="Confluence, on the Atlassian site: the pages and blog posts of its spaces,"
    " with their files",
    types=(
        ResourceType(
            name="pages", summary="a space's pages", read="listed", options=(SPACE, *PERIOD)
        ),
        ResourceType(
            name="blogposts",
            summary="a space's blog posts",
            read="listed",
            options=(SPACE, *PERIOD),
        ),
    ),
    settings=("spaces",),
    table="kb_mcp.sources.atlassian.settings:ConfluenceSource",
    preparers=(PREPARER,),
    fetcher=FETCHER,
    account=ATLASSIAN,
    refused=refused,
    unapplied=email_without_token,
    described=described,
)
JIRA = Declared(
    name="jira",
    summary="Jira, on the Atlassian site: the issues of its projects,"
    " with their comments and files",
    types=(
        ResourceType(
            name="issues",
            summary="a project's issues",
            read="searched",
            options=(PROJECT, *PERIOD),
        ),
    ),
    settings=("projects",),
    table="kb_mcp.sources.atlassian.settings:JiraSource",
    preparers=(PREPARER,),
    fetcher=FETCHER,
    account=ATLASSIAN,
    refused=refused,
    unapplied=email_without_token,
    described=described,
)

"""Confluence's and Jira's connectors: what each reads of the site, its table and stages.

The raw store keeps each document type, fetched over a period that the options give.
Each source holds its site and its way to sign in. Both connectors name one fetcher and
one preparer, which read the scope types and document types of the connector of the
source that they run for, one login and one doctor's checks, and share their light
checks: the sign-in's, and the period's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.sources.atlassian.fetch.domain import names
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
from kb_mcp.sources.declaration import Connector, Option

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kb_mcp.sources.declaration import Source

# A source's settings of its sign-in, by name: its site, then those of a sign-in by API
# token, its account's email and the token.
SITE, EMAIL, API_TOKEN = SIGN_IN = ("site", "email", "api_token")


def site_not_set(source: Source, settings: Mapping[str, object]) -> str | None:
    """Refuse a run of a source that reaches its site when none is set."""
    if settings[source.path(SITE)] is not None:
        return None
    return f"{source.path(SITE)}: not set; add it to the settings"


def token_without_email(source: Source, settings: Mapping[str, object]) -> str | None:
    """Refuse an API token without the email of its account, with which it signs in."""
    if settings[source.path(API_TOKEN)] is None or settings[source.path(EMAIL)] is not None:
        return None
    return f"{source.path(EMAIL)}: not set; an API token signs in with its account's email"


def email_without_token(
    source: Source, _options: object, settings: Mapping[str, object]
) -> dict[str, str]:
    """Without an API token, the browser's session signs in, and an email goes unused."""
    if settings[source.path(API_TOKEN)] is not None:
        return {}
    return {source.path(EMAIL): "without an API token, the browser's session signs in"}


# The options of a fetch's period: from when, until when, and the largest file kept.
SINCE, UNTIL, MAX_FILE_MB = PERIOD = (
    Option(
        flag=SINCE_FLAG,
        help="12h, 7d, 6mo, an ISO date or time, or all; by default, each scope's last fetch",
    ),
    Option(flag=UNTIL_FLAG, help="12h, 7d, or an ISO date or time, excluded; by default, now"),
    Option(
        flag=MAX_FILE_MB_FLAG,
        help=f"the largest file kept, in MiB; {DEFAULT_MAX_FILE_MB} by default",
        parse=int,
    ),
)


FETCHER = "kb_mcp.sources.atlassian.fetch.app.fetcher"
PREPARER = "kb_mcp.sources.atlassian.prepare.app.preparer"
LOGIN = "kb_mcp.sources.atlassian.fetch.app.login:login"
CHECKS = "kb_mcp.sources.atlassian.fetch.app.doctor:checks"


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


def refused(
    source: Source, options: Mapping[str, object], settings: Mapping[str, object]
) -> str | None:
    """Refuse what no fetch of a source's site can run with: the first found.

    No site; an API token without its email; the period's options, as
    ``period_refused`` says.
    """
    faults = (
        site_not_set(source, settings),
        token_without_email(source, settings),
        period_refused(options),
    )
    return next((fault for fault in faults if fault is not None), None)


def described(
    source: Source, options: Mapping[str, object], settings: Mapping[str, object]
) -> tuple[str, ...]:
    """Say how a source signs in, and where each scope's window starts, by the rule.

    By the API token when one is set, else by the saved session; --since given or not.
    """
    token = settings[source.path(API_TOKEN)] is not None
    by = "an API token" if token else "the session saved by login"
    return (
        f"source {source.name}: signs in by {by}",
        period_rule(since=options[SINCE.flag] is not None),
    )


CONFLUENCE = Connector(
    name=names.CONFLUENCE,
    help="Confluence, on the Atlassian site: the pages and blog posts of its spaces,"
    " with their files",
    scope_types=(names.SPACE,),
    settings=("spaces", *SIGN_IN),
    table_path="kb_mcp.sources.atlassian.settings:ConfluenceTable",
    preparers=(PREPARER,),
    fetcher=FETCHER,
    location=SITE,
    login=LOGIN,
    checks=CHECKS,
    options=PERIOD,
    refused=refused,
    unapplied=email_without_token,
    described=described,
)
JIRA = Connector(
    name=names.JIRA,
    help="Jira, on the Atlassian site: the issues of its projects, with their comments and files",
    scope_types=(names.PROJECT,),
    settings=("projects", *SIGN_IN),
    table_path="kb_mcp.sources.atlassian.settings:JiraTable",
    preparers=(PREPARER,),
    fetcher=FETCHER,
    location=SITE,
    login=LOGIN,
    checks=CHECKS,
    options=PERIOD,
    refused=refused,
    unapplied=email_without_token,
    described=described,
)
# The package's connectors, which the registry declares.
CONNECTORS = (CONFLUENCE, JIRA)

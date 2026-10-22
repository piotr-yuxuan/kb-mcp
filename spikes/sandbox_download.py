"""Download from the sandbox with its API token, into a scratch raw store.

This is for development only: it runs plan 004's download over the sandbox site with
the API token instead of a browser session, so that a real raw store exists for the
mirror and search to be built against. The token goes to the sandbox's host alone,
never to a media host after a redirect. Run it through sops, which gives the token to
this process alone, with a data directory outside any synchronised folder or git tree::

    sops exec-env <primary checkout>/atlassian-test-credientials.sops.json
        'uv run python spikes/sandbox_download.py --data <folder> --since 7d
         --space MFS --space QM --project PRB'

(one line, in a shell).

It prints the report's counts and what the store then holds, by count.
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from atlassian_offline_mcp.adapters import http
from atlassian_offline_mcp.adapters.http import Site
from atlassian_offline_mcp.adapters.raw_store import RawStore, Stored
from atlassian_offline_mcp.app.download import Download
from atlassian_offline_mcp.domain.period import period
from atlassian_offline_mcp.kernel.content import BlogPost, Issue, Page

MEBIBYTE = 1024 * 1024


def main() -> None:
    """Download what the options name, then print what was done and what is stored."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, required=True, help="a scratch data directory")
    parser.add_argument("--since", default="7d")
    parser.add_argument("--space", action="append", default=[])
    parser.add_argument("--project", action="append", default=[])
    arguments = parser.parse_args()
    site = os.environ["ATLASSIAN_SITE"].rstrip("/")
    host = httpx.URL(site).host
    pair = f"{os.environ['ATLASSIAN_EMAIL']}:{os.environ['ATLASSIAN_API_TOKEN']}"
    authorisation = f"Basic {base64.b64encode(pair.encode()).decode()}"

    def sandbox_only(request: httpx.Request) -> None:
        if request.url.host == host:
            request.headers["Authorization"] = authorisation

    store = RawStore(arguments.data / "raw")
    hooks = {"request": [http.refuse_plain_http, sandbox_only]}
    client = httpx.Client(base_url=site, timeout=http.TIMEOUT_S, event_hooks=hooks)
    now = datetime.now(UTC)
    with client, store.writing():
        span = period(arguments.since, None, now)
        run = Download(Site(client), store, span, 50 * MEBIBYTE, lambda: datetime.now(UTC))
        started = time.monotonic()
        run.run(arguments.space, arguments.project)
    sys.stdout.write(f"took {time.monotonic() - started:.1f} s\n")
    for what, number in sorted(run.report.counts.items()):
        sys.stdout.write(f"  {what}: {number}\n")
    for kind in (Page, BlogPost, Issue):
        items = list(store.latest(kind))
        stored = sum(isinstance(item, Stored) for item in items)
        sys.stdout.write(f"{kind.kind}: {stored} stored, {len(items) - stored} unreadable\n")


if __name__ == "__main__":
    main()

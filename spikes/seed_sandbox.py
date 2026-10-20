# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28,<1", "pillow>=13,<14"]
# ///
"""Create the probe's Confluence pages in the sandbox site (spikes/README.md, section 1).

It reads ``ATLASSIAN_SITE``, ``ATLASSIAN_EMAIL`` and ``ATLASSIAN_API_TOKEN`` from the
environment, so run it through sops, which gives the token to this process alone::

    sops exec-env <credentials file> 'uv run spikes/seed_sandbox.py --space MFS'

A page that already exists, by title, is left as it is. The Jira issues table is not
created here: insert it with /jira in the editor. ``--issue KEY`` gives that issue an
image attachment and a description that shows it.
"""

from __future__ import annotations

import argparse
import os
import sys
from io import BytesIO
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from collections.abc import Sequence

HTTP_TIMEOUT_S = 30
LONG_SECTIONS = 12
LONG_SECTION_WORDS = 250
# Words for the long page: plain English, so that word coverage is easy to read.
VOCABULARY = (
    "deployment", "service", "team", "owner", "runbook", "incident", "review", "release",
    "pipeline", "database", "schema", "migration", "rollback", "dashboard", "alert",
    "metric", "latency", "queue", "worker", "cluster", "region", "backup", "restore",
    "access", "policy", "budget", "roadmap", "quarter", "milestone", "decision",
    "proposal", "customer", "contract", "support", "ticket", "escalation", "handover",
    "onboarding", "guide",
)  # fmt: skip
# About 3,000 words in sections with headings, each section a rotation of the words.
LONG_PAGE = "".join(
    f"<h2>Section {number}</h2>"
    f"<p>{' '.join((VOCABULARY * 7)[number : number + LONG_SECTION_WORDS])}.</p>"
    for number in range(1, LONG_SECTIONS + 1)
)


def png(caption: str, width: int, height: int) -> bytes:
    """Draw a captioned PNG of the given size, wider than the browser shows it."""
    image = Image.new("RGB", (width, height), "white")
    ImageDraw.Draw(image).text((20, 20), caption, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def macro(name: str, body: str = "", **parameters: str) -> str:
    """Write a storage-format macro with its parameters and rich-text body."""
    rendered = "".join(
        f'<ac:parameter ac:name="{key}">{value}</ac:parameter>' for key, value in parameters.items()
    )
    inner = f"<ac:rich-text-body>{body}</ac:rich-text-body>" if body else ""
    return f'<ac:structured-macro ac:name="{name}">{rendered}{inner}</ac:structured-macro>'


def page_link(title: str) -> str:
    """Link to a page of the same space by its title, as include macros expect."""
    return f'<ac:link><ri:page ri:content-title="{title}"/></ac:link>'


def image(filename: str) -> str:
    """Show an attachment of the page, narrower than the file itself."""
    return f'<ac:image ac:width="400"><ri:attachment ri:filename="{filename}"/></ac:image>'


def ensure_page(
    client: httpx.Client, space_id: str, parent_id: str, title: str, body: str
) -> tuple[str, bool]:
    """Return the id of the page with this title, creating it if needed, and whether it is new."""
    found = client.get("/wiki/api/v2/pages", params={"space-id": space_id, "title": title})
    found.raise_for_status()
    results = found.json().get("results", [])
    if results:
        return str(results[0]["id"]), False
    created = client.post(
        "/wiki/api/v2/pages",
        json={
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "parentId": parent_id,
            "body": {"representation": "storage", "value": body},
        },
    )
    created.raise_for_status()
    return str(created.json()["id"]), True


def attach(client: httpx.Client, page_id: str, filename: str, data: bytes) -> None:
    """Create or replace an attachment of a page."""
    response = client.put(
        f"/wiki/rest/api/content/{page_id}/child/attachment",
        files={"file": (filename, data, "image/png")},
        headers={"X-Atlassian-Token": "no-check"},
    )
    response.raise_for_status()


def seed_issue(client: httpx.Client, key: str) -> None:
    """Attach an image to an issue, unless it has one, and show it in the description."""
    issue = client.get(f"/rest/api/3/issue/{key}", params={"fields": "attachment"})
    issue.raise_for_status()
    names = {attachment["filename"] for attachment in issue.json()["fields"]["attachment"]}
    if "probe-issue.png" not in names:
        uploaded = client.post(
            f"/rest/api/3/issue/{key}/attachments",
            files={"file": ("probe-issue.png", png("issue", 1400, 700), "image/png")},
            headers={"X-Atlassian-Token": "no-check"},
        )
        uploaded.raise_for_status()
    # Version 2 of the API takes wiki markup, in which !name! shows an attachment.
    described = client.put(
        f"/rest/api/2/issue/{key}",
        json={"fields": {"description": "An image for the probe.\n\n!probe-issue.png!"}},
    )
    described.raise_for_status()


def main(argv: Sequence[str] | None = None) -> int:
    """Create the pages under the space's home page, then print their titles and ids."""
    parser = argparse.ArgumentParser(description="Create the probe's pages in the sandbox.")
    parser.add_argument("--space", required=True, help="the key of the space to create them in")
    parser.add_argument("--issue", help="a Jira issue key to give an image in its description")
    arguments = parser.parse_args(argv)
    site = urlsplit(os.environ["ATLASSIAN_SITE"])
    if site.scheme != "https" or not site.netloc.endswith(".atlassian.net"):
        parser.error("ATLASSIAN_SITE must be an https://<name>.atlassian.net address")
    auth = (os.environ["ATLASSIAN_EMAIL"], os.environ["ATLASSIAN_API_TOKEN"])
    with httpx.Client(
        base_url=f"https://{site.netloc}", auth=auth, timeout=HTTP_TIMEOUT_S
    ) as client:
        spaces = client.get("/wiki/api/v2/spaces", params={"keys": arguments.space})
        spaces.raise_for_status()
        space = spaces.json()["results"][0]
        space_id, home_id = str(space["id"]), str(space["homepageId"])
        table = "".join(
            f"<tr><td>Row {row} A</td><td>Row {row} B</td><td>Row {row} C</td></tr>"
            for row in range(1, 4)
        )
        pages = {
            "Probe innermost": (
                home_id,
                macro("excerpt", "<p>The innermost sentence comes from the deepest page.</p>")
                + image("probe-innermost.png"),
            ),
            "Probe middle": (
                home_id,
                macro("include", **{"": page_link("Probe innermost")})
                + "<p>The middle sentence sits between two includes.</p>",
            ),
        }
        ids: dict[str, str] = {}
        for title, (parent, body) in pages.items():
            ids[title], _ = ensure_page(client, space_id, parent, title, body)
        complex_body = (
            macro("include", **{"": page_link("Probe middle")})
            + macro("excerpt-include", **{"": page_link("Probe innermost")})
            + macro("detailssummary", cql='label = "probe-props" and space = currentSpace()')
            + macro("children")
            + macro("info", "<p>An information panel for the probe.</p>")
            + '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python'
            + '</ac:parameter><ac:plain-text-body><![CDATA[print("probe")]]>'
            + "</ac:plain-text-body></ac:structured-macro>"
            + macro("expand", "<p>Text hidden inside the expand.</p>", title="More detail")
            + f"<table><tbody>{table}</tbody></table>"
            + image("probe-complex.png")
        )
        ids["Probe complex"], _ = ensure_page(
            client, space_id, home_id, "Probe complex", complex_body
        )
        for number in (1, 2):
            title = f"Probe properties {number}"
            properties = (
                f"<table><tbody><tr><th>Owner</th><td>Team {number}</td></tr>"
                f"<tr><th>State</th><td>Draft {number}</td></tr></tbody></table>"
            )
            ids[title], created = ensure_page(
                client, space_id, home_id, title, macro("details", properties)
            )
            if created:
                labelled = client.post(
                    f"/wiki/rest/api/content/{ids[title]}/label",
                    json=[{"prefix": "global", "name": "probe-props"}],
                )
                labelled.raise_for_status()
        # Children display lists this page alone, apart from the report's pages.
        ids["Probe child"], _ = ensure_page(
            client, space_id, ids["Probe complex"], "Probe child", "<p>A child page.</p>"
        )
        ids["Probe long"], _ = ensure_page(client, space_id, home_id, "Probe long", LONG_PAGE)
        attach(client, ids["Probe innermost"], "probe-innermost.png", png("innermost", 1200, 800))
        attach(client, ids["Probe complex"], "probe-complex.png", png("complex", 1600, 900))
        if arguments.issue:
            seed_issue(client, arguments.issue)
    for title, page_id in ids.items():
        sys.stdout.write(f"{page_id}  {title}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests of the corpus itself: its shape, its links, its tickets (plan 002, criteria 2, 3)."""

from __future__ import annotations

import re
from collections import Counter
from datetime import timedelta

import pytest

from sandbox.seed_corpus import (
    CLOSED,
    Page,
    Ticket,
    read_corpus,
    read_ideas,
    read_tickets,
    timeline,
    to_jira,
    to_storage,
)

SECTIONS = 15
PAGES = 250
LONG = range(60, 71)
LONG_WORDS = range(1500, 3001)
SHORT_WORDS = range(300, 1501)
FRENCH = 6
TICKETS = 1200
TICKETS_PER_EPIC = 39
IDEAS = 5
# Names of real organisations and products that a fictional wiki might slip in. Jira and
# Confluence, which host the corpus, may be named, as in any wiki on them.
DENIED = (
    "Slack",
    "PagerDuty",
    "Opsgenie",
    "Datadog",
    "Splunk",
    "Sentry",
    "AWS",
    "Amazon",
    "Azure",
    "Microsoft",
    "Outlook",
    "Google",
    "Gmail",
    "GitHub",
    "GitLab",
    "Bitbucket",
    "Atlassian",
    "Stripe",
    "Adyen",
    "PayPal",
    "Visa",
    "Mastercard",
    "Amex",
    "Okta",
    "Zendesk",
    "Intercom",
    "Salesforce",
    "HubSpot",
    "Notion",
    "Figma",
    "Miro",
    "Snowflake",
    "Databricks",
    "Workday",
    "BambooHR",
    "Expensify",
    "DocuSign",
    "Uber",
    "Deliveroo",
    "Heroku",
    "Vercel",
    "Cloudflare",
    "Twilio",
    "Revolut",
    "Monzo",
    "Barclays",
    "HSBC",
    "Lloyds",
    "NatWest",
    "Swile",
    "Qonto",
    "Doctolib",
    "Apple",
)
WEB_ADDRESS = re.compile(r"https?://([^/\s)>\]`'\"]+)")
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
TICKET_KEY = re.compile(r"\bENG-(\d+)\b")


@pytest.fixture(scope="module")
def pages() -> dict[str, Page]:
    """Read the corpus once."""
    return read_corpus()


@pytest.fixture(scope="module")
def tickets() -> list[Ticket]:
    """Read the tickets once."""
    return read_tickets()


def words(page: Page) -> int:
    """Count a page's words as wc does, front matter aside."""
    return len(page.markdown.split())


def test_every_section_has_a_section_page_and_the_corpus_has_its_size(
    pages: dict[str, Page],
) -> None:
    """Fifteen sections, each with its index, under one home page: 250 pages in all."""
    sections = {key.partition("/")[0] for key in pages if "/" in key}
    assert len(sections) == SECTIONS
    assert {f"{section}/index" for section in sections} | {"index"} <= set(pages)
    assert len(pages) == PAGES


def test_pages_are_long_or_short_within_bounds(pages: dict[str, Page]) -> None:
    """Long pages hold 1,500 to 3,000 words, the others 300 to 1,500."""
    content = {key: words(page) for key, page in pages.items() if not key.endswith("index")}
    outside = {key: count for key, count in content.items() if count not in range(300, 3001)}
    assert outside == {}
    assert sum(count in LONG_WORDS for count in content.values()) in LONG


def test_french_pages_and_titles(pages: dict[str, Page]) -> None:
    """At least six pages are French, and no two pages share a title."""
    assert sum(page.lang == "fr" for page in pages.values()) >= FRENCH
    titles = Counter(page.title for page in pages.values())
    assert [title for title, count in titles.items() if count > 1] == []


def test_every_page_converts_to_well_formed_storage_with_its_links(
    pages: dict[str, Page],
) -> None:
    """Conversion refuses raw HTML, unknown links and malformed XHTML: none occurs."""
    titles = {key: page.title for key, page in pages.items()}
    unlinked = [key for key, page in pages.items() if not to_storage(page, titles)[1]]
    assert unlinked == []


def test_addresses_are_reserved_and_no_real_name_appears(pages: dict[str, Page]) -> None:
    """Web and email addresses use reserved domains; no denied name appears."""
    texts = {key: page.markdown for key, page in pages.items()}
    texts |= {idea.key: idea.markdown for idea in read_ideas().values()}
    problems = []
    for key, text in texts.items():
        # A placeholder such as <service> stands for any name.
        named = re.sub(r"<[^>\s]+>", "x", text)
        hosts = WEB_ADDRESS.findall(named) + EMAIL.findall(named)
        problems += [
            f"{key}: {host}"
            for host in hosts
            if not host.endswith((".example", ".example.com")) and host != "example.com"
        ]
        problems += [f"{key}: {name}" for name in DENIED if re.search(rf"\b{name}\b", text)]
    assert problems == []


def test_every_ticket_key_a_page_cites_exists(
    pages: dict[str, Page], tickets: list[Ticket]
) -> None:
    """Pages cite tickets by key; each key names a ticket of the data."""
    keys = {ticket.key for ticket in tickets}
    cited = {
        f"ENG-{number}" for page in pages.values() for number in TICKET_KEY.findall(page.markdown)
    }
    assert cited - keys == set()


def test_tickets_are_numbered_epics_first_with_unique_summaries(tickets: list[Ticket]) -> None:
    """1,200 tickets, ENG-1 to ENG-1200; each epic holds 39 tickets; summaries are unique."""
    assert len(tickets) == TICKETS
    epics = [ticket for ticket in tickets if ticket.parent is None]
    children = Counter(ticket.parent for ticket in tickets if ticket.parent)
    assert [ticket.key for ticket in epics] == [f"ENG-{number}" for number in range(1, 31)]
    assert set(children.values()) == {TICKETS_PER_EPIC}
    numbers = sorted(int(ticket.key.removeprefix("ENG-")) for ticket in tickets)
    assert numbers == list(range(1, TICKETS + 1))
    assert len({ticket.summary for ticket in tickets}) == TICKETS


def test_most_tickets_are_closed_and_their_dates_span_the_calendar(tickets: list[Ticket]) -> None:
    """At least 80% of tickets are closed, and they were created over at least 15 months."""
    closed = [ticket for ticket in tickets if ticket.status in CLOSED]
    assert len(closed) >= 0.8 * TICKETS
    created = [timeline(ticket).created for ticket in tickets]
    assert max(created) - min(created) >= timedelta(days=15 * 30)


def test_ticket_descriptions_convert_with_their_links(tickets: list[Ticket]) -> None:
    """Every description converts, every corpus link in it names a page."""
    urls = {key: f"https://site.example.com/{key}" for key in read_corpus()}
    for ticket in tickets:
        assert to_jira(ticket.markdown, ticket.source, urls)


def test_ideas_link_corpus_pages() -> None:
    """Each idea converts, linking only corpus pages."""
    urls = {key: f"https://site.example.com/{key}" for key in read_corpus()}
    ideas = read_ideas()
    assert len(ideas) == IDEAS
    for idea in ideas.values():
        assert "site.example.com" in to_jira(idea.markdown, idea.source, urls)

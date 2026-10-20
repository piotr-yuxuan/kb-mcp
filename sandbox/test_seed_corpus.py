"""Tests of the seeding script's pure parts: reading, conversion and decisions."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import yaml
from defusedxml import ElementTree

from sandbox.seed_corpus import (
    NAMESPACES,
    SPRINTS,
    TODAY,
    LinkTargets,
    LivePage,
    Page,
    decide,
    match,
    read_corpus,
    read_golden,
    read_ideas,
    read_tickets,
    sprint_start,
    timeline,
    to_jira,
    to_storage,
)

if TYPE_CHECKING:
    from pathlib import Path
    from xml.etree.ElementTree import Element

    from sandbox.seed_corpus import Ticket

TITLES = {"index": "Handbook", "people/index": "People", "people/onboarding": "Onboarding & you"}
AC = "{http://atlassian.com/content}"
RI = "{http://atlassian.com/resource}"


def storage(markdown: str, key: str = "payments/runbook") -> tuple[str, frozenset[str]]:
    """Convert a Markdown body as the page with that key, beside the pages of TITLES."""
    return to_storage(Page(key, "Runbook", "en", markdown), TITLES)


def parse(body: str) -> Element:
    """Parse a storage body as XML, which Confluence requires it to be."""
    return ElementTree.fromstring(f"<root {NAMESPACES}>{body}</root>")


def live(**changes: object) -> LivePage:
    """Describe a site page as the last seeding left it, with some fields changed."""
    fields = {
        "id": "10",
        "title": "Runbook",
        "parent_id": "2",
        "version": 3,
        "source": {"key": "payments/runbook", "sha256": "abc", "version": 3},
        "property_id": "7",
        "property_version": 1,
    }
    return LivePage(**{**fields, **changes})


def test_reading_keys_pages_by_path_and_finds_parents(tmp_path: Path) -> None:
    """A page's key is its path; a section page hangs from the home page, others from it."""
    (tmp_path / "people").mkdir()
    (tmp_path / "index.md").write_text('---\ntitle: "Handbook"\n---\nHome.\n')
    (tmp_path / "people" / "index.md").write_text('---\ntitle: "People"\n---\nPeople.\n')
    (tmp_path / "people" / "conges.md").write_text('---\ntitle: "Congés"\nlang: fr\n---\nTexte.\n')
    pages = read_corpus(tmp_path)
    assert sorted(pages) == ["index", "people/conges", "people/index"]
    assert pages["people/conges"].lang == "fr"
    assert pages["people/conges"].markdown == "Texte.\n"
    assert [pages[key].parent for key in sorted(pages)] == [None, "people/index", "index"]


@pytest.mark.parametrize(
    "text",
    [
        "No front matter.\n",
        "---\nlang: fr\n---\nNo title.\n",
        '---\ntitle: "Page"\nlang: de\n---\nUnknown language.\n',
        '---\ntitle: "Page"\nowner: me\n---\nUnknown field.\n',
    ],
)
def test_reading_refuses_bad_front_matter(tmp_path: Path, text: str) -> None:
    """Front matter holds a title, and lang: fr on French pages, nothing else."""
    (tmp_path / "page.md").write_text(text)
    with pytest.raises(ValueError, match="page"):
        read_corpus(tmp_path)


def test_code_blocks_become_code_macros_with_their_language() -> None:
    """A fenced block is a code macro; text has no language; ]]> survives the CDATA."""
    body, _ = storage('```python\nprint("]]>")\n```\n\n```text\nplain\n```\n')
    macros = parse(body).findall(f"{AC}structured-macro")
    assert [macro.get(f"{AC}name") for macro in macros] == ["code", "code"]
    first, second = (macro.findall(f"{AC}parameter") for macro in macros)
    assert [parameter.text for parameter in first] == ["python"]
    assert second == []
    assert macros[0].findtext(f"{AC}plain-text-body") == 'print("]]>")'


def test_code_blocks_in_other_languages_are_refused() -> None:
    """Only the bible's languages are allowed, so the code macro always knows them."""
    with pytest.raises(ValueError, match="cobol"):
        storage("```cobol\nDISPLAY 'HELLO'.\n```\n")


@pytest.mark.parametrize(
    ("alert", "panel"),
    [("NOTE", "info"), ("TIP", "tip"), ("IMPORTANT", "note"), ("WARNING", "warning")],
)
def test_alerts_become_panels_without_their_label(alert: str, panel: str) -> None:
    """A GitHub alert is the matching panel macro, holding the alert's text only."""
    body, _ = storage(f"> [!{alert}]\n> Superseded by **the new policy**.\n")
    macro = parse(body).find(f"{AC}structured-macro")
    assert macro is not None
    assert macro.get(f"{AC}name") == panel
    text = "".join(macro.itertext())
    assert "Superseded by the new policy." in text
    assert alert.title() not in text


def test_links_to_corpus_pages_become_page_links_by_title() -> None:
    """A link to a corpus file names the page by space and title, and keeps its text."""
    body, linked = storage("Read [the *guide*](../people/onboarding.md) first.\n")
    link = parse(body).find(f".//{AC}link")
    assert link is not None
    page = link.find(f"{RI}page")
    assert page is not None
    assert page.get(f"{RI}space-key") == "QM"
    assert page.get(f"{RI}content-title") == "Onboarding & you"
    assert "".join(link.itertext()) == "the guide"
    assert linked == {"people/onboarding"}


def test_web_links_stay_links() -> None:
    """A web address is an ordinary link, and links no corpus page."""
    body, linked = storage("See [Lantern](https://lantern.quillmoor.example/d/1).\n")
    anchor = parse(body).find(".//a")
    assert anchor is not None
    assert anchor.get("href") == "https://lantern.quillmoor.example/d/1"
    assert linked == frozenset()


@pytest.mark.parametrize(
    "markdown",
    [
        "[missing](../people/nobody.md)\n",
        "[anchored](../people/onboarding.md#day-one)\n",
        "[relative](other.html)\n",
        "Raw <span>HTML</span>.\n",
    ],
)
def test_links_outside_the_corpus_and_raw_html_are_refused(markdown: str) -> None:
    """A link must name a corpus page without an anchor; raw HTML could break the XHTML."""
    with pytest.raises(ValueError, match="payments/runbook"):
        storage(markdown)


def test_task_lists_stay_text() -> None:
    """A task list item stays text: Confluence would drop a form input."""
    body, _ = storage("- [ ] Collect the laptop\n")
    assert "input" not in body
    assert "[ ] Collect the laptop" in "".join(parse(body).itertext())


def test_a_new_page_is_created() -> None:
    """A corpus page the site lacks is created."""
    assert decide("Runbook", "2", "abc", None) == "create"


def test_a_page_as_last_written_is_left() -> None:
    """A page whose title, parent, body and version are as last written is left alone."""
    assert decide("Runbook", "2", "abc", live()) == "leave"


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Old runbook"},
        {"parent_id": "5"},
        {"source": {"key": "payments/runbook", "sha256": "old", "version": 3}},
        # Edited by hand since the last seeding.
        {"version": 4},
        # The page write succeeded, the property write after it did not.
        {"version": 4, "source": {"key": "payments/runbook", "sha256": "old", "version": 3}},
        # A page of the same title that no seeding wrote.
        {"source": None, "property_id": None, "property_version": None},
    ],
)
def test_a_page_that_differs_is_updated(changes: dict[str, object]) -> None:
    """Any difference from what the corpus would write updates the page."""
    assert decide("Runbook", "2", "abc", live(**changes)) == "update"


def test_pages_match_by_key_then_title_and_home_by_id() -> None:
    """A renamed page is found by its key, an unseeded one by title, the home by id."""
    pages = {
        key: Page(key, title, "en", "")
        for key, title in [("index", "Handbook"), ("a/one", "One"), ("a/two", "Two")]
    }
    renamed = live(id="11", title="Former one", source={"key": "a/one"})
    same_title = live(id="12", title="Two", source=None)
    home = live(id="1", title="Quillmoor handbook Home", source=None)
    matched = match(pages, [renamed, same_title, home], home_id="1")
    assert {key: page.id for key, page in matched.items()} == {
        "index": "1",
        "a/one": "11",
        "a/two": "12",
    }


def test_rendered_links_and_errors_are_found() -> None:
    """The check reads page links by their target id, and spots an error element."""
    parser = LinkTargets()
    parser.feed(
        '<p><a href="/wiki/x" data-linked-resource-id="42" data-linked-resource-type="page">x</a>'
        '<a href="https://example.com">web</a></p>'
        '<div class="error"><span class="error">Unknown macro</span></div>'
    )
    assert parser.ids == {"42"}
    assert parser.error


def test_ideas_are_keyed_by_name_and_hold_a_summary_only(tmp_path: Path) -> None:
    """An idea's front matter is its summary; its source is its path under the sandbox."""
    ideas = tmp_path / "jira" / "ideas"
    ideas.mkdir(parents=True)
    (ideas / "dark-mode.md").write_text('---\nsummary: "Dark mode"\n---\nBody.\n')
    read = read_ideas(ideas)
    assert list(read) == ["jira/dark-mode"]
    assert read["jira/dark-mode"].summary == "Dark mode"
    assert read["jira/dark-mode"].source == "jira/ideas/dark-mode.md"
    (ideas / "bad.md").write_text('---\ntitle: "Bad"\n---\nBody.\n')
    with pytest.raises(ValueError, match="summary"):
        read_ideas(ideas)


def test_jira_markup_links_corpus_pages_to_the_site_without_anchors() -> None:
    """A corpus link points at the page's address; headings carry no anchor macro."""
    markup = to_jira(
        "## Problem\n\nSee [the runbook](../../corpus/payments/runbook.md).\n",
        "jira/ideas/rollback.md",
        {"payments/runbook": "https://site.example.com/wiki/spaces/QM/pages/42"},
    )
    assert "[the runbook|https://site.example.com/wiki/spaces/QM/pages/42]" in markup
    assert "h2. Problem" in markup
    assert "anchor" not in markup


@pytest.mark.parametrize(
    "markdown",
    ["[gone](../../corpus/payments/gone.md)\n", "[outside](../ideas/other.md)\n", "<b>x</b>\n"],
)
def test_jira_markup_refuses_unknown_pages_and_raw_html(markdown: str) -> None:
    """Every corpus link must name a page on the site, and raw HTML is refused."""
    with pytest.raises(ValueError, match=r"jira/ideas/rollback\.md"):
        to_jira(markdown, "jira/ideas/rollback.md", {"payments/runbook": "https://x.example.com"})


def epic_file(tmp_path: Path, sprints: list[int], statuses: list[str]) -> list[Ticket]:
    """Write one epic file with a ticket per status, and read it back."""
    folder = tmp_path / "jira" / "eng"
    folder.mkdir(parents=True, exist_ok=True)
    base = {"type": "Story", "priority": "Medium", "labels": ["payments"], "description": "D"}
    tickets = [
        {**base, "key": f"ENG-{31 + number}", "summary": f"Ticket {number}", "status": status}
        | {"comments": ["First.", "Second."]}
        for number, status in enumerate(statuses)
    ]
    epic = {"key": "ENG-1", "summary": "Epic", "sprints": sprints, "labels": ["payments"]}
    data = {"epic": epic | {"description": "Epic."}, "tickets": tickets}
    (folder / "01-epic.yaml").write_text(yaml.safe_dump(data))
    return read_tickets(folder)


def test_an_epic_file_reads_as_the_epic_then_its_tickets(tmp_path: Path) -> None:
    """The epic comes first, without a parent; its tickets name it as their parent."""
    tickets = epic_file(tmp_path, [1, 8], ["Done", "Won't Do"])
    assert [(ticket.key, ticket.type, ticket.parent) for ticket in tickets] == [
        ("ENG-1", "Epic", None),
        ("ENG-31", "Story", "ENG-1"),
        ("ENG-32", "Story", "ENG-1"),
    ]
    assert tickets[0].status == "Done"
    assert tickets[1].source == "jira/eng/01-epic.yaml"


def test_an_epic_reaching_the_active_sprint_is_in_progress(tmp_path: Path) -> None:
    """An epic whose sprints run into the active one is not done."""
    assert epic_file(tmp_path, [33, SPRINTS], ["Done"])[0].status == "In Progress"


@pytest.mark.parametrize(
    ("sprints", "statuses"),
    [([1, 8], ["Closed"]), ([0, 8], ["Done"]), ([8, 1], ["Done"]), ([1, 41], ["Done"])],
)
def test_epic_files_with_bad_values_are_refused(
    tmp_path: Path, sprints: list[int], statuses: list[str]
) -> None:
    """A status outside the workflow, or sprints outside the calendar, are refused."""
    with pytest.raises(ValueError, match="01-epic"):
        epic_file(tmp_path, sprints, statuses)


def test_derived_dates_hold_their_invariants(tmp_path: Path) -> None:
    """Closed tickets resolve inside a sprint of their epic; nothing is dated after today."""
    statuses = ["Done", "Won't Do", "In Progress", "To Do"] * 10
    first = 30
    epic, *tickets = epic_file(tmp_path, [first, SPRINTS], statuses)
    epic_line = timeline(epic)
    assert epic_line.resolved is None
    for ticket in tickets:
        line = timeline(ticket)
        assert epic_line.created < line.created < TODAY
        assert all(line.created <= comment < TODAY for comment in line.comments)
        if ticket.status == "In Progress":
            assert (line.sprint, line.resolved) == (SPRINTS, None)
        elif ticket.status == "To Do":
            assert (line.sprint, line.resolved) == (None, None)
        else:
            assert line.sprint is not None
            assert first <= line.sprint <= SPRINTS
            start = sprint_start(line.sprint)
            assert line.resolved is not None
            assert start <= line.resolved < min(start + timedelta(days=14), TODAY)
            assert all(comment <= line.resolved for comment in line.comments)


def test_a_done_epic_resolves_after_its_tickets(tmp_path: Path) -> None:
    """A done epic is resolved after the last of its tickets, in its last sprint."""
    epic, *tickets = epic_file(tmp_path, [1, 8], ["Done"] * 39)
    resolved = [timeline(ticket).resolved for ticket in tickets]
    assert all(date is not None for date in resolved)
    epic_resolved = timeline(epic).resolved
    assert epic_resolved is not None
    assert max(date for date in resolved if date) < epic_resolved < sprint_start(9)
    assert [timeline(ticket).sprint for ticket in tickets] == sorted(
        timeline(ticket).sprint or 0 for ticket in tickets
    )
    assert {timeline(ticket).sprint for ticket in tickets} == set(range(1, 9))


def test_derived_dates_are_the_same_on_every_run(tmp_path: Path) -> None:
    """The derivation depends only on the data, never on the clock or on a process."""
    statuses = ["Done", "To Do", "In Progress"]
    once = [timeline(ticket) for ticket in epic_file(tmp_path / "a", [5, 14], statuses)]
    again = [timeline(ticket) for ticket in epic_file(tmp_path / "b", [5, 14], statuses)]
    assert once == again


GOOD_QUESTION = {
    "id": "q001",
    "question": "How do I get the old payouts release back?",
    "overlap": "paraphrase",
    "lang": "en",
    "expected": ["payments/payout-gateway-rollback"],
    "partial": [],
    "evidence": {"payments/payout-gateway-rollback": "drain the payout queue"},
    "outdated": [],
    "traps": ["synonym"],
    "distractors": ["ml/model-rollback"],
}


def test_a_golden_question_reads_with_every_document_it_names(tmp_path: Path) -> None:
    """A question keeps its fields, and names its expected and look-alike documents."""
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump([GOOD_QUESTION]))
    (question,) = read_golden(path)
    assert question.expected == ("payments/payout-gateway-rollback",)
    assert question.documents == {"payments/payout-gateway-rollback", "ml/model-rollback"}


@pytest.mark.parametrize(
    "changes",
    [
        {"overlap": "fuzzy"},
        {"lang": "de"},
        {"expected": []},
        {"expected": ["a/one", "a/two", "a/three"]},
        {"evidence": {"a/other": "phrase"}},
        {"traps": ["typo"]},
        {"answer": "an extra field"},
    ],
)
def test_golden_questions_that_break_the_schema_are_refused(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    """Kinds, languages and traps come from closed lists; one or two documents, each evidenced."""
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump([GOOD_QUESTION | changes]))
    with pytest.raises(ValueError, match="q001"):
        read_golden(path)

"""Tests of the probe's pure parts: the scans, coverage, comparison and report."""

from __future__ import annotations

import argparse
import json
import stat
from collections import Counter
from io import BytesIO
from typing import TYPE_CHECKING

import httpx
import pytest
from PIL import Image
from playwright.sync_api import Error as PlaywrightError

from spikes.session_probe import (
    JSON,
    SCROLL_JS,
    VECTOR,
    Check,
    ImageRef,
    PageEvidence,
    Query,
    Rendered,
    Reply,
    StorageScanner,
    ViewScanner,
    attempt,
    compare_page,
    coverage,
    disable_password_saving,
    first_image,
    image_size,
    macro_labels,
    main,
    media_type,
    probe_carrier,
    probe_issue,
    read_check,
    refuse_plain_http,
    render_page,
    render_report,
    run_query,
    run_with_saved_cookies,
    save_cookies,
    session_client,
    shown,
    words,
)

if TYPE_CHECKING:
    from pathlib import Path

OWNER_ONLY = 0o600
# Two unsettled polls (no area, an empty shell), the first sight of the text, then the
# three unchanged polls that settle it.
SCROLL_AFTER_POLLS = 6

STORAGE = """<p>Intro</p>
<ac:structured-macro ac:name="expand" ac:macro-id="1"><ac:rich-text-body>
  <ac:structured-macro ac:name="jira" ac:macro-id="2">
    <ac:parameter ac:name="jqlQuery">project = ABC ORDER BY key</ac:parameter>
    <ac:parameter ac:name="columns">key,summary</ac:parameter>
  </ac:structured-macro>
</ac:rich-text-body></ac:structured-macro>
<ac:structured-macro ac:name="jira" ac:macro-id="3">
  <ac:parameter ac:name="key">ABC-7</ac:parameter>
</ac:structured-macro>
<ac:structured-macro ac:name="detailssummary" ac:macro-id="4">
  <ac:parameter ac:name="cql">label = "x"</ac:parameter>
</ac:structured-macro>
<ac:structured-macro ac:name="code" ac:macro-id="5">
  <ac:plain-text-body><![CDATA[print("x")]]></ac:plain-text-body>
</ac:structured-macro>"""

VIEW = """<p>Intro text</p>
<div class="conf-macro output-block" data-macro-name="info"><p>Note this</p></div>
<div class="conf-macro output-block" data-macro-name="jira"></div>
<table><tr><td>cell</td></tr></table>
<img class="confluence-embedded-image" data-linked-resource-type="attachment"
     data-linked-resource-id="65538" data-linked-resource-container-id="98305" src="/a.png">
<img class="emoticon emoticon-smile" src="/smile.png">
<img class="confluence-embedded-image confluence-external-resource" src="https://example.invalid/a.png">
<img src="/b.png">
<script>var hidden = "not text";</script>"""


def png(width: int, height: int) -> bytes:
    """Encode a blank PNG image of the given size."""
    buffer = BytesIO()
    Image.new("RGB", (width, height)).save(buffer, format="PNG")
    return buffer.getvalue()


def evidence(
    storage: str,
    view: str,
    rendered: Rendered | None,
    *,
    rest_images: tuple[tuple[int, int] | None, ...] = (),
    results: tuple[tuple[Query, tuple[str, ...] | None], ...] = (),
) -> PageEvidence:
    """Build the evidence about one page, as the probe gathers it."""
    return PageEvidence(
        StorageScanner.parse(storage),
        ViewScanner.parse(view),
        rendered,
        rest_images,
        results,
        rest_ms=120,
        render_ms=4_000,
    )


def test_storage_scanner_counts_nested_macros_and_reads_their_queries() -> None:
    """Every macro counts, nested ones too; only query parameters are kept, in order."""
    scanned = StorageScanner.parse(STORAGE)
    assert scanned.macros == Counter({"jira": 2, "expand": 1, "detailssummary": 1, "code": 1})
    assert scanned.queries == [
        Query("jql", "project = ABC ORDER BY key", "jira"),
        Query("key", "ABC-7", "jira"),
        Query("cql", 'label = "x"', "detailssummary"),
    ]


def test_compare_page_finds_a_macro_rendered_inline_without_a_wrapper() -> None:
    """An excerpt renders its body inline: view holding its words is its output."""
    storage = (
        '<ac:structured-macro ac:name="excerpt"><ac:rich-text-body>'
        "<p>The innermost sentence.</p></ac:rich-text-body></ac:structured-macro>"
    )
    present = compare_page("page-1", evidence(storage, "<p>The innermost sentence.</p>", None))
    absent = compare_page("page-1", evidence(storage, "<p>Another sentence.</p>", None))
    assert (
        Check("page-1: macro excerpt", passed=True, detail="1 of 1 with output in view") in present
    )
    assert (
        Check("page-1: macro excerpt", passed=False, detail="0 of 1 with output in view") in absent
    )


def test_storage_scanner_reads_the_jql_of_a_smart_link_table() -> None:
    """The /jira command inserts a Smart Link table, whose JSON parameters hold its JQL."""
    storage = (
        '<a href="https://example.invalid/issues/" data-card-appearance="block" data-datasource='
        '"{&quot;id&quot;:&quot;d8&quot;,&quot;parameters&quot;:{&quot;jql&quot;:'
        '&quot;project = PRB ORDER BY key&quot;},&quot;views&quot;:[]}">x</a>'
        '<a data-datasource="not json">y</a>'
    )
    scanned = StorageScanner.parse(storage)
    assert scanned.macros == Counter({"jira-datasource": 1, "smart-link-list": 1})
    assert scanned.queries == [Query("jql", "project = PRB ORDER BY key", "jira-datasource")]


def test_view_scanner_reads_a_smart_link_table_as_its_output_apart_from_the_text() -> None:
    """REST renders a Smart Link table as a plain table: its rows are the table's output."""
    view = (
        "<p>Before the table.</p>"
        '<table class="jiraWorkItemMacroListViewTable"><tr><td>'
        '<img src="/avatar" alt="Idea" width="16" height="16"></td>'
        '<td><a href="/browse/PRB-1">PRB-1</a></td><td>An idea</td></tr></table>'
    )
    scanned = ViewScanner.parse(view)
    assert scanned.macros_with_output == Counter({"jira-datasource": 1})
    assert "PRB-1" in " ".join(scanned.macro_text["jira-datasource"])
    assert scanned.static_text == "Before the table."
    assert scanned.images == []


def test_words_compare_static_text_and_queries_read_the_dynamic_tables() -> None:
    """A table drawn by the browser is compared by its query, not word by word."""
    storage = (
        '<a data-datasource="{&quot;parameters&quot;:{&quot;jql&quot;:'
        '&quot;project = PRB&quot;}}">x</a>'
    )
    view = (
        "<p>Static text of the page.</p>"
        '<table class="jiraWorkItemMacroListViewTable"><tr><td>PRB-1</td></tr></table>'
    )
    rendered = Rendered(
        "Static text of the page.",
        tables=1,
        images=(),
        dynamic_text="PRB-1 Unassigned Synced just now 1 item",
    )
    page = evidence(
        storage,
        view,
        rendered,
        results=((Query("jql", "project = PRB", "jira-datasource"), ("PRB-1",)),),
    )
    checks = {check.name: check for check in compare_page("page-1", page)}
    assert checks["page-1: words"].detail == "100.0% of 5 in view, 0 missing"
    assert checks["page-1: jql 1"].passed
    assert checks["page-1: jql 1"].detail.endswith("1 shown in the browser, 1 in view")
    assert checks["page-1: macro jira-datasource"].passed


def test_view_scanner_reads_text_tables_images_and_macro_output() -> None:
    """Script text is not visible; emoticons are not images; an empty macro has no output."""
    scanned = ViewScanner.parse(VIEW)
    assert scanned.tables == 1
    assert scanned.images == [
        ImageRef("attachment", "98305", "65538"),
        ImageRef("external"),
        ImageRef("unmapped"),
    ]
    assert scanned.local_images == [ImageRef("attachment", "98305", "65538"), ImageRef("unmapped")]
    assert scanned.macros_with_output == Counter({"info": 1})
    assert "Note this" in scanned.text
    assert "cell" in scanned.text
    assert "not text" not in scanned.text


def test_view_scanner_credits_output_to_every_enclosing_macro() -> None:
    """Text inside a macro nested in another counts as output of both."""
    view = '<div data-macro-name="expand"><div data-macro-name="info"><p>x</p></div></div>'
    assert ViewScanner.parse(view).macros_with_output == Counter({"expand": 1, "info": 1})


def test_view_scanner_closes_elements_left_open() -> None:
    """A body cut short still credits the output of its open macros."""
    view = '<div data-macro-name="expand"><p>text'
    assert ViewScanner.parse(view).macros_with_output == Counter({"expand": 1})


def test_words_fold_case_and_skip_single_characters() -> None:
    """Words compare without case, and one-character tokens are noise."""
    assert words("Hello, HELLO world a") == Counter({"hello": 2, "world": 1})


def test_coverage_counts_repeated_words() -> None:
    """A word rendered twice but held once over REST covers one of its two occurrences."""
    assert coverage(words("alpha beta beta"), words("alpha beta")) == 2 / 3


def test_coverage_of_an_empty_render_is_complete() -> None:
    """Nothing rendered means nothing missing."""
    assert coverage(Counter(), words("alpha")) == 1.0


def test_macro_labels_keep_built_in_names_and_number_the_others() -> None:
    """Third-party macro names never reach the report; their numbering is stable."""
    labels = macro_labels(["info", "zeta-app", "acme-widget", "jira"])
    assert labels == {
        "info": "info",
        "jira": "jira",
        "acme-widget": "custom-1",
        "zeta-app": "custom-2",
    }


def test_compare_page_passes_when_rest_holds_what_the_browser_shows() -> None:
    """Same words, tables, full-size images and query results: every check passes."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "project = ABC</ac:parameter></ac:structured-macro>"
    )
    view = (
        '<p>Runbook</p><div data-macro-name="jira"><a>ABC-1</a> <a>ABC-2</a></div>'
        '<table><tr><td>cell</td></tr></table><img data-linked-resource-type="attachment"'
        ' data-linked-resource-id="1" data-linked-resource-container-id="2">'
    )
    rendered = Rendered(
        "Runbook cell", tables=1, images=((800, 600),), dynamic_text="ABC-1 Summary ABC-2"
    )
    checks = compare_page(
        "page-1",
        evidence(
            storage,
            view,
            rendered,
            rest_images=((1600, 1200),),
            results=((Query("jql", "project = ABC", "jira"), ("ABC-1", "ABC-2")),),
        ),
    )
    assert [check.name for check in checks if not check.passed] == []


def test_compare_page_flags_what_rest_misses() -> None:
    """Missing words, tables and rows, a smaller image and an empty macro each fail."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "project = ABC</ac:parameter></ac:structured-macro>"
    )
    view = (
        '<p>Runbook</p><div data-macro-name="jira"></div><table><tr><td>cell</td></tr>'
        '</table><img data-linked-resource-type="attachment" data-linked-resource-id="1"'
        ' data-linked-resource-container-id="2">'
    )
    rendered = Rendered(
        "Runbook cell loaded later by script ABC-1 ABC-2 ABC-3", tables=2, images=((800, 600),)
    )
    checks = compare_page(
        "page-1",
        evidence(
            storage,
            view,
            rendered,
            rest_images=((100, 100),),
            results=((Query("jql", "project = ABC", "jira"), ("ABC-1", "ABC-2", "ABC-3")),),
        ),
    )
    failed = {check.name for check in checks if not check.passed}
    assert failed == {"page-1: macro jira", "page-1: words", "page-1: tables", "page-1: images"}


def test_compare_page_flags_query_results_the_browser_does_not_show() -> None:
    """A JQL result over REST that the browser does not show means the table differs."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "project = ABC</ac:parameter></ac:structured-macro>"
    )
    view = '<div data-macro-name="jira"><a>ABC-1</a></div>'
    checks = compare_page(
        "page-1",
        evidence(
            storage,
            view,
            Rendered("ABC-1", tables=0, images=()),
            results=((Query("jql", "project = ABC", "jira"), ("ABC-1", "ABC-9")),),
        ),
    )
    jql = next(check for check in checks if check.name == "page-1: jql 1")
    assert jql == Check(
        "page-1: jql 1",
        passed=False,
        detail="2 over REST; of the first 2, 1 shown in the browser, 1 in view",
    )


def test_words_fail_below_98_percent_whatever_the_page_length() -> None:
    """No fixed allowance: one missing word fails a short page, 15 of 1,000 pass."""
    short = "<p>" + " ".join(f"word{index}" for index in range(20)) + "</p>"
    one_more = Rendered(f"{short[3:-4]} extra", tables=0, images=())
    long = "<p>" + " ".join(f"word{index}" for index in range(985)) + "</p>"
    fifteen = Rendered(long[3:-4] + "".join(f" new{index}" for index in range(15)), 0, ())
    twenty_five = Rendered(long[3:-4] + "".join(f" new{index}" for index in range(25)), 0, ())
    words_check = "page-1: words"
    checks = {
        name: {check.name: check for check in compare_page("page-1", page)}[words_check]
        for name, page in {
            "short": evidence("", short, one_more),
            "fifteen": evidence("", long, fifteen),
            "twenty-five": evidence("", long, twenty_five),
        }.items()
    }
    assert not checks["short"].passed
    assert checks["fifteen"].passed
    assert checks["fifteen"].detail == "98.5% of 1000 in view, 15 missing"
    assert not checks["twenty-five"].passed


def test_a_report_drawn_empty_fails_even_when_its_titles_appear_elsewhere() -> None:
    """Titles listed by another macro, such as children display, are not the report's."""
    storage = (
        '<ac:structured-macro ac:name="detailssummary"><ac:parameter ac:name="cql">'
        'label = "x"</ac:parameter></ac:structured-macro>'
    )
    view = (
        '<div data-macro-name="children"><a>Properties 1</a> <a>Properties 2</a></div>'
        '<div data-macro-name="detailssummary"><p>Generating the report</p></div>'
    )
    results = ((Query("cql", 'label = "x"', "detailssummary"), ("Properties 1", "Properties 2")),)
    empty = Rendered("Properties 1 Properties 2", tables=0, images=())
    drawn = Rendered("Properties 1 Properties 2", 1, (), dynamic_text="Properties 1 Properties 2")
    reports = [
        next(
            check
            for check in compare_page("page-1", evidence(storage, view, rendered, results=results))
            if check.name == "page-1: cql 1"
        )
        for rendered in (empty, drawn)
    ]
    assert reports[0] == Check(
        "page-1: cql 1",
        passed=False,
        detail="2 over REST; of the first 2, 0 shown in the browser, 0 in view",
    )
    assert reports[1].passed


def test_compare_page_leaves_external_images_out_of_the_image_check() -> None:
    """External images are linked, never downloaded, so they cannot fail the check."""
    view = (
        '<img data-linked-resource-type="attachment" data-linked-resource-id="1"'
        ' data-linked-resource-container-id="2">'
        '<img class="confluence-external-resource" src="https://example.invalid/a.png">'
    )
    rendered = Rendered("", tables=0, images=((800, 600),), external_images=1)
    checks = compare_page("page-1", evidence("", view, rendered, rest_images=((800, 600),)))
    images = next(check for check in checks if check.name == "page-1: images")
    assert images == Check(
        "page-1: images",
        passed=True,
        detail="1 in view, 1 rendered, 1 of 1 compared at full size or larger, 0 not downloaded;"
        " widest 800 px over REST, 800 px in the browser; external: 1 in view, 1 rendered",
    )


def test_a_query_with_no_results_over_rest_fails() -> None:
    """With nothing over REST, there is nothing to compare with the browser."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "assignee = currentUser()</ac:parameter></ac:structured-macro>"
    )
    page = evidence(
        storage,
        "<p>x</p>",
        Rendered("ABC-1 ABC-2", tables=0, images=()),
        results=((Query("jql", "assignee = currentUser()", "jira"), ()),),
    )
    checks = compare_page("page-1", page)
    assert Check("page-1: jql 1", passed=False, detail="0 over REST") in checks


def test_a_single_issue_query_reads_the_issue_over_rest() -> None:
    """A single-issue macro's key is read over REST, and a missing issue fails."""
    issue = Reply(200, "application/json", b'{"key": "ABC-7"}', 1)
    gone = Reply(404, "application/json", b"{}", 1)
    asked: list[str] = []

    def found(path: str) -> Reply:
        asked.append(path)
        return issue

    assert run_query(found, Query("key", "ABC-7", "jira"), "") == ("ABC-7",)
    assert asked == ["/rest/api/3/issue/ABC-7?fields=summary"]
    assert run_query(lambda _: gone, Query("key", "ABC-7", "jira"), "") is None


def test_compare_page_reports_a_page_that_never_rendered() -> None:
    """Without a rendered page, the comparison fails but still checks the macros."""
    storage = '<ac:structured-macro ac:name="info"></ac:structured-macro>'
    checks = compare_page("page-2", evidence(storage, "<p>x</p>", None))
    assert checks[0] == Check("page-2: rendered", passed=False, detail="content area never settled")
    assert "page-2: macro info" in {check.name for check in checks}


def test_report_holds_none_of_the_page_identifiers_or_content() -> None:
    """Titles, ids, URLs, queries, issue keys and third-party names stay out of the report."""
    seeds = [
        "acme-secret-widget",
        "SECRETPROJ",
        "confidential-roadmap",
        "Confidential roadmap 2027",
        "998877",
        "secret-corp.atlassian.net",
    ]
    storage = (
        '<ac:structured-macro ac:name="acme-secret-widget"></ac:structured-macro>'
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "project = SECRETPROJ AND labels = confidential-roadmap</ac:parameter>"
        '</ac:structured-macro><ac:structured-macro ac:name="detailssummary">'
        '<ac:parameter ac:name="cql">label = "confidential-roadmap"</ac:parameter>'
        "</ac:structured-macro>"
    )
    text = "Confidential roadmap 2027 SECRETPROJ-42 https://secret-corp.atlassian.net/wiki/x"
    view = (
        f"<p>{text}</p><img data-linked-resource-type='attachment' "
        "data-linked-resource-id='998877' data-linked-resource-container-id='998877'>"
    )
    page = evidence(
        storage,
        view,
        Rendered(text, tables=0, images=((640, 480),)),
        rest_images=((640, 480),),
        results=(
            (Query("jql", "project = SECRETPROJ", "jira"), ("SECRETPROJ-42",)),
            (
                Query("cql", 'label = "confidential-roadmap"', "detailssummary"),
                ("Confidential roadmap 2027",),
            ),
        ),
    )
    report = render_report(compare_page("page-1", page))
    assert [seed for seed in seeds if seed.casefold() in report.casefold()] == []
    assert "custom-1" in report


def test_image_size_reads_pixels_only_from_images() -> None:
    """A downloaded image gives its size; anything else gives none."""
    assert image_size(Reply(200, "image/png", png(40, 20), 1)) == (40, 20)
    assert image_size(Reply(200, "text/html", png(40, 20), 1)) is None
    assert image_size(Reply(200, "image/png", b"not an image", 1)) is None
    assert image_size(Reply(401, "image/png", png(40, 20), 1)) is None


def test_an_svg_counts_as_downloaded_at_any_size() -> None:
    """An SVG has no pixels to compare; downloaded, it scales to what the browser shows."""
    svg = Reply(200, "image/svg+xml", b"<svg/>", 1)
    assert image_size(svg) == VECTOR
    view = (
        '<img data-linked-resource-type="attachment" data-linked-resource-id="1"'
        ' data-linked-resource-container-id="2">'
    )
    rendered = Rendered("", tables=0, images=((760, 400),))
    checks = compare_page("page-1", evidence("", view, rendered, rest_images=(VECTOR,)))
    images = next(check for check in checks if check.name == "page-1: images")
    assert images.passed


def test_report_lists_each_check_then_a_summary() -> None:
    """Each check is one line, then the counts of passes and failures."""
    checks = [Check("a", passed=True, detail="1"), Check("b", passed=False, detail="2")]
    report = render_report(checks)
    assert report == "PASS  a  1\nFAIL  b  2\n1 passed, 1 failed\n"


def test_failed_reads_report_no_url_id_or_exception_message() -> None:
    """A failed read names its exception class only; no read reports a path or an id."""
    seeds = ["secret-corp.atlassian.net", "998877", "SECRETPROJ", "/wiki/"]
    listing = json.dumps({"results": [{"id": "att998877", "mediaType": "image/png"}]}).encode()

    def get(path: str) -> Reply:
        if path.endswith("/attachments?limit=25"):
            return Reply(200, JSON, listing, 1)
        if "/rest/api/3/" in path:
            message = f"https://secret-corp.atlassian.net{path} failed"
            raise PlaywrightError(message)
        message = f"cannot reach https://secret-corp.atlassian.net{path}"
        raise httpx.ConnectError(message)

    checks = [
        *probe_carrier("httpx", get, "998877", "project = SECRETPROJ"),
        *probe_issue(get, "SECRETPROJ-42"),
    ]
    report = render_report(checks)
    assert [seed for seed in seeds if seed.casefold() in report.casefold()] == []
    assert attempt(get, "/wiki/x").media_type == "error ConnectError"
    assert run_query(get, Query("jql", "project = SECRETPROJ", "jira"), "") is None


def test_the_image_download_reads_the_original_through_the_v1_path() -> None:
    """The listing's image is downloaded through the v1 endpoint, which serves the original."""
    listing = json.dumps({"results": [{"id": "att5", "mediaType": "image/png"}]}).encode()
    asked: list[str] = []

    def get(path: str) -> Reply:
        asked.append(path)
        body = listing if path.endswith("/attachments?limit=25") else b"{}"
        return Reply(200, JSON, body, 1)

    probe_carrier("httpx", get, "12", "project = ABC")
    assert asked[-1] == "/wiki/rest/api/content/12/child/attachment/att5/download"


def test_a_read_passes_only_with_status_200_and_the_expected_media_type() -> None:
    """A sign-in page served with 200 is not a JSON answer."""
    assert not read_check("x", Reply(200, "text/html", b"<html>", 1), JSON).passed
    assert not read_check("x", Reply(404, JSON, b"{}", 1), JSON).passed
    assert read_check("x", Reply(200, JSON, b"{}", 1), JSON).passed


def test_unknown_media_types_never_reach_the_report() -> None:
    """A server chooses its Content-Type freely; only known media types are named."""
    assert media_type("application/json; charset=UTF-8") == "application/json"
    assert media_type("image/x-secretcorp-roadmap") == "image/other"
    assert media_type("text/x-internal") == "text/other"
    assert media_type("secretcorp/falcon") == "other"


def test_view_scanner_maps_only_well_formed_attachment_ids() -> None:
    """An id that is not a number never goes into a request path."""
    view = (
        '<img data-linked-resource-type="attachment" data-linked-resource-id="../../x"'
        ' data-linked-resource-container-id="2">'
    )
    assert ViewScanner.parse(view).images == [ImageRef("unmapped")]


def test_saved_cookies_are_readable_by_the_user_alone(tmp_path: Path) -> None:
    """The session's cookies are a secret: mode 0600, even over an existing file."""
    path = tmp_path / "cookies.json"
    path.write_text("[]", encoding="utf-8")
    path.chmod(0o644)
    cookie = {"name": "a", "value": "b", "domain": "example.invalid"}
    save_cookies(path, [cookie])
    assert stat.S_IMODE(path.stat().st_mode) == OWNER_ONLY
    assert json.loads(path.read_text(encoding="utf-8")) == [cookie]


def test_password_saving_is_disabled_and_other_preferences_kept(tmp_path: Path) -> None:
    """Chrome must not offer to save the sign-in password; the rest of its settings stay."""
    preferences = tmp_path / "Default" / "Preferences"
    preferences.parent.mkdir()
    preferences.write_text(json.dumps({"profile": {"name": "Probe"}, "other": 1}), "utf-8")
    disable_password_saving(tmp_path)
    settings = json.loads(preferences.read_text(encoding="utf-8"))
    assert settings["credentials_enable_service"] is False
    assert settings["profile"] == {"name": "Probe", "password_manager_enabled": False}
    assert settings["autofill"] == {"profile_enabled": False}
    assert settings["other"] == 1


def test_plain_http_requests_are_refused() -> None:
    """Cookies never travel in clear, even after a redirect to plain HTTP."""
    with pytest.raises(httpx.UnsupportedProtocol):
        refuse_plain_http(httpx.Request("GET", "http://example.invalid/x"))
    refuse_plain_http(httpx.Request("GET", "https://example.invalid/x"))


def test_titles_match_as_whole_words() -> None:
    """A title is shown only as itself: "Plan 1" is not in "Plan 10", "Home" not in "Homepage"."""
    assert shown("cql", ["Plan 1"], "Plan 10 Plan 11") == 0
    assert shown("cql", ["Home"], "Welcome to the Homepage") == 0
    assert shown("cql", ["Plan 1"], "See Plan 1.") == 1


def test_a_classic_jira_macro_is_compared_word_for_word() -> None:
    """With no browser selector for it, a classic macro's text counts as the page's own."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">ABC-7</ac:parameter>'
        "</ac:structured-macro>"
    )
    view = (
        "<p>Release notes for the quarter.</p><span data-macro-name='jira'><a>ABC-7</a>"
        " <span>Fix the login timeout</span> <span>In Progress</span></span>"
    )
    text = "Release notes for the quarter. ABC-7 Fix the login timeout In Progress"
    checks = {
        check.name: check
        for check in compare_page("page-1", evidence(storage, view, Rendered(text, 0, ())))
    }
    assert checks["page-1: words"].passed
    assert checks["page-1: macro jira"].passed


def test_an_include_nested_from_another_page_is_not_counted_twice() -> None:
    """The page's one include has output; the include inside it belongs to the included page."""
    storage = '<ac:structured-macro ac:name="include"></ac:structured-macro>'
    view = '<div data-macro-name="include"><div data-macro-name="include"><p>Deep</p></div></div>'
    checks = compare_page("page-1", evidence(storage, view, None))
    assert (
        Check("page-1: macro include", passed=True, detail="1 of 1 with output in view") in checks
    )


def test_images_inside_dynamic_tables_belong_to_the_tables() -> None:
    """Avatars and issue-type icons in a Smart Link table are not the page's images."""
    view = (
        '<table class="jiraWorkItemMacroListViewTable"><tr><td><img src="/avatar.png"'
        ' width="48" height="48"></td></tr></table>'
    )
    assert ViewScanner.parse(view).images == []


def test_a_small_attachment_still_counts_and_odd_sizes_do_not_crash() -> None:
    """An attachment is downloaded at full size whatever its declared size."""
    view = (
        '<img data-linked-resource-type="attachment" data-linked-resource-id="5"'
        ' data-linked-resource-container-id="2" width="30" height="30">'
        '<img src="/x.png" width="²" height="1">'
    )
    assert ViewScanner.parse(view).images == [
        ImageRef("attachment", "2", "5"),
        ImageRef("unmapped"),
    ]


def test_a_dynamic_table_without_a_query_of_its_own_fails() -> None:
    """A table from an included page has no query here, so nothing else compares it."""
    storage = (
        '<ac:structured-macro ac:name="detailssummary"><ac:parameter ac:name="cql">'
        'label = "x"</ac:parameter></ac:structured-macro>'
    )
    rendered = Rendered("Text", tables=2, images=(), dynamic_text="A B", regions=2)
    checks = compare_page("page-1", evidence(storage, "<p>Text</p>", rendered))
    expected = Check(
        "page-1: dynamic tables", passed=False, detail="2 in the browser, 1 with a query read"
    )
    assert expected in checks


def snapshot(
    text: str, dynamic: str = "", images: tuple[tuple[int, int], ...] = ()
) -> dict[str, object]:
    """Return a result of CONTENT_JS, as the browser gives it."""
    return {
        "text": text,
        "dynamic": dynamic,
        "regions": 1 if dynamic else 0,
        "tables": 0,
        "images": [list(size) for size in images],
        "external": 0,
    }


class ScriptedPage:
    """A browser page that returns scripted snapshots, the last one for ever."""

    def __init__(self, snapshots: list[dict[str, object] | None]) -> None:
        """Keep the snapshots to return, in order."""
        self.snapshots = snapshots
        self.calls: list[str] = []

    def goto(self, url: str, timeout: float) -> None:
        """Open nothing."""

    def wait_for_timeout(self, timeout: float) -> None:
        """Wait for nothing."""

    def evaluate(self, script: str, argument: object) -> object:
        """Record a scroll, or return the next content snapshot."""
        del argument
        if script == SCROLL_JS:
            self.calls.append("scroll")
            return 0
        self.calls.append("content")
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


def test_render_page_scrolls_once_settled_then_waits_for_the_images() -> None:
    """An empty shell is not settled; the scroll follows a first settle, then images load."""
    settled = snapshot("Page text")
    loaded = snapshot("Page text", images=((640, 400),))
    page = ScriptedPage([None, snapshot("  "), *[settled] * 4, *[loaded] * 4])
    rendered, render_ms = render_page(page, "https://example.invalid", "1")  # type: ignore[arg-type]
    assert rendered is not None
    assert rendered.images == ((640, 400),)
    assert page.calls.index("scroll") == SCROLL_AFTER_POLLS
    assert page.calls.count("scroll") == 1
    assert render_ms >= 0


def test_render_page_waits_for_a_dynamic_table_to_fill() -> None:
    """Rows arriving in a dynamic table after the text has settled reset the wait."""
    page = ScriptedPage(
        [
            *[snapshot("Text")] * 4,
            snapshot("Text", "Key Summary"),
            *[snapshot("Text", "Key Summary A-1 A-2")] * 4,
        ]
    )
    rendered, _ = render_page(page, "https://example.invalid", "1")  # type: ignore[arg-type]
    assert rendered is not None
    assert rendered.dynamic_text == "Key Summary A-1 A-2"


def test_the_session_client_refuses_plain_http_before_any_connection() -> None:
    """The refusal is wired into the client, so a redirect to plain HTTP never leaves."""
    with (
        session_client("https://example.invalid", []) as client,
        pytest.raises(httpx.UnsupportedProtocol),
    ):
        client.get("http://example.invalid/x")


def test_main_refuses_arguments_that_could_not_stay_out_of_the_report() -> None:
    """A user name, plain HTTP or an odd page id stops the probe before any request."""
    for arguments in (
        ["--site", "http://example.atlassian.net", "--page", "1"],
        ["--site", "https://user@example.atlassian.net", "--page", "1"],
        ["--site", "https://example.atlassian.net", "--page", "²"],
        ["--site", "https://example.atlassian.net", "--page", "1", "--issue", "ABC-²"],
    ):
        with pytest.raises(SystemExit):
            main(arguments)


def test_a_missing_saved_session_fails_without_a_request(tmp_path: Path) -> None:
    """With no cookie file from an earlier sign-in, the next-day check reports it at once."""
    arguments = argparse.Namespace(profile=tmp_path, site="https://example.invalid", page=["1"])
    checks = run_with_saved_cookies(arguments, "project = ABC")
    assert checks == [Check("saved session", passed=False, detail="error FileNotFoundError")]


def test_ids_that_are_not_numbers_never_reach_a_path() -> None:
    """A listing's odd attachment id, or a page's odd container id, is not used."""
    assert first_image([{"id": "../x", "mediaType": "image/png"}], "mediaType") is None
    good = {"id": "att5", "mediaType": "image/png"}
    assert first_image([good], "mediaType") == good
    view = (
        '<img data-linked-resource-type="attachment" data-linked-resource-id="5"'
        ' data-linked-resource-container-id="2/../x">'
    )
    assert ViewScanner.parse(view).images == [ImageRef("unmapped")]


def test_a_failed_query_reports_no_query_text() -> None:
    """The failure branch, too, holds no part of the query."""
    storage = (
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="jqlQuery">'
        "project = SECRETPROJ</ac:parameter></ac:structured-macro>"
    )
    page = evidence(
        storage,
        "<p>x</p>",
        Rendered("x", 0, ()),
        results=((Query("jql", "project = SECRETPROJ", "jira"), None),),
    )
    assert "secretproj" not in render_report(compare_page("page-1", page)).casefold()

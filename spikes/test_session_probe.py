"""Tests of the probe's pure parts: the scans, coverage, comparison and report."""

from __future__ import annotations

from collections import Counter
from io import BytesIO

from PIL import Image

from spikes.session_probe import (
    Check,
    ImageRef,
    PageEvidence,
    Query,
    Rendered,
    Reply,
    StorageScanner,
    ViewScanner,
    compare_page,
    coverage,
    image_size,
    macro_labels,
    render_report,
    words,
)

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
        Query("jql", "project = ABC ORDER BY key"),
        Query("key", "ABC-7"),
        Query("cql", 'label = "x"'),
    ]


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
    rendered = Rendered("Runbook ABC-1 ABC-2 cell", tables=1, images=((800, 600),))
    checks = compare_page(
        "page-1",
        evidence(
            storage,
            view,
            rendered,
            rest_images=((1600, 1200),),
            results=((Query("jql", "project = ABC"), ("ABC-1", "ABC-2")),),
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
            results=((Query("jql", "project = ABC"), ("ABC-1", "ABC-2", "ABC-3")),),
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
            results=((Query("jql", "project = ABC"), ("ABC-1", "ABC-9")),),
        ),
    )
    jql = next(check for check in checks if check.name == "page-1: jql 1")
    assert jql == Check(
        "page-1: jql 1",
        passed=False,
        detail="2 over REST; of the first 2, 1 shown in the browser, 1 in view",
    )


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
        " external: 1 in view, 1 rendered",
    )


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
            (Query("jql", "project = SECRETPROJ"), ("SECRETPROJ-42",)),
            (Query("cql", 'label = "confidential-roadmap"'), ("Confidential roadmap 2027",)),
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


def test_report_lists_each_check_then_a_summary() -> None:
    """Each check is one line, then the counts of passes and failures."""
    checks = [Check("a", passed=True, detail="1"), Check("b", passed=False, detail="2")]
    report = render_report(checks)
    assert report == "PASS  a  1\nFAIL  b  2\n1 passed, 1 failed\n"

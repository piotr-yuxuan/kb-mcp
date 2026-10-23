"""What each command records is what ``docs/reference/telemetry/`` says, on the scripted site.

Plan 016, criterion 10: for each page found in the folder, runs of its command over the
scripted site and the scripted endpoint, between them, record every event, span and
instrument that the page lists, and none that it and the README do not; each record
exported has the event as body and the ids of the span around it. Criterion 11: a run's
trace keeps its size however many documents it fetches, each a trace of its own.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.kernel.content import Page
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from tests.reference import README, Emitted, documented, operations, undocumented
from tests.samples import v2_space
from tests.test_download import SITE, FakeSite
from tests.test_mirror import FETCHED, SPACE_ID, listing_page, page_responses
from tests.test_mirror_command import fake_pandoc

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from tests.conftest import InMemory

TESTS = Path(__file__).parent
# Where a test compares the runs of a command with its page.
CHECKED = re.compile(r'undocumented\(\s*"([a-z-]+)"')
# The site's client, as a run makes it, before any test replaces it.
CLIENT = http.client


def test_each_page_of_the_reference_is_checked_by_a_test() -> None:
    """Some test compares each command's runs with its page; later plans' in their files.

    The pages are found in their folder, and the tests in theirs: neither is a list.
    """
    sources = [path.read_text("utf-8") for path in TESTS.glob("test_*.py")]
    checked = {name for source in sources for name in CHECKED.findall(source)}
    assert set(operations()) <= checked


def test_no_page_repeats_what_the_readme_says_every_command_records() -> None:
    """A name is listed once: on the README, or on the pages of the commands that record it."""
    every = documented(README)
    for name in operations():
        own = documented(name)
        assert set(own.events).isdisjoint(every.events), name
        assert set(own.spans).isdisjoint(every.spans), name
        assert set(own.instruments).isdisjoint(every.instruments), name


def signed_in(monkeypatch: MonkeyPatch, fake: FakeSite, data: Path) -> Settings:
    """Save a session in the data directory ``data``; have the site's client reach ``fake``.

    The client is the site's own, observed, over the scripted site; no run waits between
    requests. Give the settings of a run that names the site and the data directory.
    """
    chosen = Settings(site=SITE, data_dir=data.resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(
        http, "client", lambda site, cookies, hooks=(): CLIENT(site, cookies, hooks, transport)
    )
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return chosen


def download(data: Path, *options: str) -> list[str]:
    """Give the arguments of a download of the site into ``data``, without settings file."""
    settings = ("--config", str(data.parent / "none.toml"), "--data-dir", str(data))
    return ["download", "--yes", *settings, "--site", SITE, *options]


def test_download_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Fetched, failed, unread, skipped, retried; refused, busy, interrupted, signed out.

    A first run fetches a space and a project, with a page whose adapter refuses it, a
    video skipped and a file gone; a second, a space whose pages the site cannot serve,
    retried until they fail; a third, a space not found. Then a period refused, a store
    busy, Ctrl-C, and a session no longer saved.
    """
    emitted = Emitted()
    since = ("--since", "2026-10-02")
    data = tmp_path / "data"
    fake = FakeSite(changed_labels=True, failing_files=1)
    chosen = signed_in(monkeypatch, fake, data)
    with emitted.gathering(telemetry, "download"):
        whole = download(data, "--space", "MFS", "--project", "PRB", *since)
        assert main(whole) == ExitStatus.FAILED
    signed_in(monkeypatch, FakeSite(pages_fail=True), tmp_path / "retried")
    with emitted.gathering(telemetry, "download"):
        assert main(download(tmp_path / "retried", "--space", "MFS", *since)) == ExitStatus.FAILED
    signed_in(monkeypatch, FakeSite(spaces=[]), data)
    with emitted.gathering(telemetry, "download"):
        assert main(download(data, "--space", "NOPE", *since)) == ExitStatus.FAILED
    with emitted.gathering(telemetry, "download"):
        backwards = ("--since", "2026-10-22", "--until", "2026-10-01")
        assert main(download(data, "--space", "MFS", *backwards)) == ExitStatus.REFUSED
    with emitted.gathering(telemetry, "download"), RawStore(chosen.raw).writing():
        assert main(download(data, "--space", "MFS", *since)) == ExitStatus.FAILED

    def interrupted(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", interrupted)
    with emitted.gathering(telemetry, "download"):
        assert main(download(data, "--space", "MFS", *since)) == ExitStatus.INTERRUPTED
    (chosen.session / COOKIES).unlink()
    with emitted.gathering(telemetry, "download"):
        assert main(download(data, "--space", "MFS", *since)) == ExitStatus.SIGN_IN_AGAIN
    assert undocumented("download", emitted) == []


def test_a_run_s_trace_keeps_its_size_each_document_a_trace_linked_to_it(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """3 then 30 documents, pages and a blog post: the run's traces count as many spans.

    Each document fetched is the root of a trace of its own, linked to its run's. Each
    run downloads into a data directory of its own.
    """
    sizes = []
    for pages in (2, 29):
        data = tmp_path / str(pages)
        signed_in(monkeypatch, FakeSite(many_pages=pages), data)
        emitted = Emitted()
        with emitted.gathering(telemetry, "download"):
            assert main(download(data, "--space", "MFS", "--since", "2026-10-02")) == 0
        (root,) = (span for span in emitted.spans if span.name == "download")
        fetched = [span for span in emitted.spans if span.name == "download.document"]
        assert len(fetched) == pages + 1
        for document in fetched:
            assert (document.parent, document.trace_id != root.trace_id) == (0, True)
            assert [trace_id for trace_id, _ in document.links] == [root.trace_id]
        sizes.append(sum(1 for span in emitted.spans if span.trace_id == root.trace_id))
    three, thirty = sizes
    assert three == thirty


def test_mirror_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Built, failed, unplaced; then pandoc gone once the run began.

    A space lists a page, built, and one that pandoc fails on; a third page's space is
    not listed. The pandoc on PATH passes its input through, unless it holds BREAK.
    """
    data = tmp_path / "data"
    store = RawStore(data / "raw")
    listed = [listing_page("100", "Home", None, None), listing_page("101", "Broken", None, None)]
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), listed, [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(Page, page_responses("101", "Broken", 1, "<p>BREAK</p>", []), FETCHED, {})
        elsewhere = page_responses("102", "Elsewhere", 1, "<p>Away.</p>", [], spaceId="999")
        store.put(Page, elsewhere, FETCHED, {})
    script = 'input=$(cat); case "$input" in *BREAK*) exit 3;; esac; printf "%s" "$input"'
    folder = fake_pandoc(tmp_path / "bin", script)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    arguments = [
        "mirror",
        "--yes",
        "--config",
        str(tmp_path / "none.toml"),
        "--data-dir",
        str(data),
    ]
    emitted = Emitted()
    with emitted.gathering(telemetry, "mirror"):
        assert main(arguments) == ExitStatus.FAILED

    def gone() -> Pandoc:
        message = "pandoc: not found on PATH"
        raise PandocMissingError(message)

    monkeypatch.setattr(Pandoc, "find", gone)
    with emitted.gathering(telemetry, "mirror"):
        assert main(arguments) == ExitStatus.FAILED
    assert undocumented("mirror", emitted) == []

"""What each command records is what ``docs/reference/telemetry/`` says, on the scripted site.

Plan 016, criterion 10: for each page found in the folder, runs of its command over the
scripted site and the scripted endpoint, between them, record every event, span and
instrument that the page lists, and none that it and the README do not; each record
exported has the event as body and the ids of the span around it. Criterion 11: a run's
trace keeps its size however many documents it fetches, each a trace of its own.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.config.domain.settings import Settings
from atlassian_offline_mcp.kernel.content import Page
from atlassian_offline_mcp.kernel.exit_status import ExitStatus
from atlassian_offline_mcp.mirror.adapters.pandoc import Pandoc, PandocMissingError
from atlassian_offline_mcp.search.app.indexing import Embedding, build_index
from atlassian_offline_mcp.sources.atlassian.adapters import http
from atlassian_offline_mcp.sources.atlassian.adapters.raw_store import RawStore
from atlassian_offline_mcp.sources.atlassian.adapters.session_file import COOKIES, write_cookies
from tests.collector import Collector, collecting
from tests.endpoint import URL, Scripted, nothing_listening, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.reference import README, Emitted, documented, operations, undocumented
from tests.samples import v2_space
from tests.test_download import SITE, FakeSite
from tests.test_mirror import FETCHED, SPACE_ID, listing_page, page_responses
from tests.test_mirror_command import fake_pandoc
from tests.test_serve import talk
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

    from tests.conftest import InMemory

TESTS = Path(__file__).parent
ROOT = TESTS.parent
# How long telemetry has at a run's end, in seconds, and a server for an answer.
LIMIT_S = 1.0
WAIT_S = 30
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


def by_meaning(data: Path, url: str, mode: str = "hybrid") -> list[str]:
    """Write settings naming the tiny model at ``url``, in ``mode``; give the options to them."""
    settings = data.parent / "config.toml"
    settings.write_text(
        f'model = "tiny"\nembedding_url = {json.dumps(url)}\nsearch_mode = "{mode}"\n',
        encoding="utf-8",
    )
    return ["--config", str(settings), "--data-dir", str(data)]


def test_index_records_as_documented(telemetry: InMemory, tmp_path: Path) -> None:
    """Indexed by meaning, a file skipped and a piece refused; no endpoint; no mirror.

    The mirror holds a few pages, one with a front matter refused, and one whose second
    section the endpoint refuses to embed.
    """
    data = tmp_path / "data"
    fillers(data / "docs", 5)
    body = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
    write(data / "docs", page("196845", "Rollback"), body)
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    refused = "Rollback\nRelease\nThe deploy of the seller service."
    emitted = Emitted()
    with serving(Scripted(refused={refused})) as url, emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    with nothing_listening() as url, emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    with emitted.gathering(telemetry, "index"):
        empty = tmp_path / "empty"
        assert main(["index", "--yes", *by_meaning(empty, URL, "lexical")]) == ExitStatus.FAILED
    assert undocumented("index", emitted) == []


def server(home: Path, settings: str, ports: list[int]) -> StdioServerParameters:
    """Give the command of a server run from ``home``, whose settings file holds ``settings``.

    It runs in a fresh interpreter, as agents start it, kept to the ports given of this
    machine; telemetry has ``LIMIT_S`` seconds at its end.
    """
    folder = home / ".config" / "atlassian-offline-mcp"
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text(settings, encoding="utf-8")
    given = {"ports": ports, "limit": LIMIT_S, "report": str(home / "report.json")}
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tests.guarded", json.dumps({**given, "arguments": ["serve"]})],
        env={"HOME": str(home)},
        cwd=ROOT,
    )


def test_serve_records_as_documented(tmp_path: Path) -> None:
    """By meaning, each tool and a call refused; then, the endpoint stopped, by words alone.

    The first server is spoken to as an agent does, from ``initialize``; the second by
    the SDK's client, from ``server/discover``. Each runs in a fresh interpreter, its
    telemetry sent to a scripted collector: what it logged is read from its file, what
    it traced and measured at the collector.
    """
    data = tmp_path / "data"
    fillers(data / "docs")
    write(data / "docs", page("4002", "Holiday canteen", space="ENG"), "Leave for a meal.\n")
    write(data / "docs", issue("PROJ-7", "Kafka upgrade"))
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(tiny(), data / "v.db"))
    calls: list[tuple[str, dict[str, object]]] = [
        ("search", {"query": "vacation lunch"}),
        ("read", {"ref": "PROJ-7"}),
        ("browse", {"space": "ENG"}),
        ("status", {}),
        ("search", {"query": "kafka", "filters": {"space": "NOPE"}}),
    ]

    async def search(command: StdioServerParameters) -> None:
        async with Client(command) as client:
            with anyio.fail_after(WAIT_S):
                await client.call_tool("search", {"query": "vacation lunch"})

    emitted = Emitted()
    for name, stopped in (("answering", False), ("stopped", True)):
        home, collector = tmp_path / name, Collector()
        with (
            nothing_listening() if stopped else serving(Scripted()) as url,
            collecting(collector) as endpoint,
        ):
            settings = (
                f'data_dir = {json.dumps(str(data))}\nmodel = "tiny"\nsearch_mode = "hybrid"\n'
                f"embedding_url = {json.dumps(url)}\n"
                f"[telemetry]\nendpoint = {json.dumps(endpoint)}\n"
            )
            ports = [int(each.rpartition(":")[2].partition("/")[0]) for each in (url, endpoint)]
            command = server(home, settings, ports)
            if stopped:
                anyio.run(search, command)
            else:
                _, _, results = talk(command, calls)
                assert [result["isError"] for result in results] == [False] * 4 + [True]
        (log_file,) = user_log_folder(home).iterdir()
        emitted.collected(log_file, collector)
    assert undocumented("serve", emitted) == []

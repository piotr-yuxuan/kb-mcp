"""What each command records is what ``docs/reference/telemetry/`` says, on the scripted site.

Plan 016, criterion 10: for each page found in the folder, runs of its command over the
scripted site and the scripted endpoint, between them, record every event, span and
instrument that the page lists, and none that it and the README do not; each record
exported has the event as body, its fields as attributes and the ids of the span around
it. Criterion 11: a run's trace keeps its size however many documents it fetches, each a
trace of its own.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import httpx
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters.pandoc import Pandoc, PandocFailedError, PandocMissingError
from kb_mcp.search.adapters import vector_cache
from kb_mcp.search.app.indexing import Embedding, build_index
from kb_mcp.sources.atlassian.fetch.adapters import http
from kb_mcp.sources.atlassian.fetch.adapters.browser import SignInFailedError
from kb_mcp.sources.atlassian.fetch.adapters.raw_store import RawStore
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from kb_mcp.sources.atlassian.fetch.app import login as login_module
from kb_mcp.sources.atlassian.fetch.domain.content import Page
from kb_mcp.sources.worklog.prepare.app import preparer as worklog_preparer
from tests.collector import Collector, collecting
from tests.composed import MODEL
from tests.endpoint import URL, Reranks, Scripted, nothing_listening, serving, tiny
from tests.mirrors import MOMENT, PERSONS, fillers, issue, page, worklog_document, write
from tests.reference import README, Emitted, documented, operations, undocumented
from tests.samples import v2_space
from tests.test_evaluate import GOLDEN
from tests.test_fetching import SITE, FakeSite
from tests.test_prepare_atlassian import FETCHED, SPACE_ID, listing_page, page_responses
from tests.test_prepare_command import fake_pandoc
from tests.test_prepare_worklog import FIXTURE as WORKLOG_FIXTURE
from tests.test_serve import talk
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from collections.abc import Callable

    from _pytest.monkeypatch import MonkeyPatch

    from kb_mcp.config.domain.settings import Settings
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


def signed_in(
    monkeypatch: MonkeyPatch, handle: Callable[[httpx.Request], httpx.Response], data: Path
) -> Settings:
    """Save a session in the data directory ``data``; have ``handle`` answer the site's client.

    The client is the site's own, observed, over the scripted site; no run waits between
    requests. Give the settings of a run that names the site and the data directory.
    """
    chosen = MODEL(accounts={"atlassian": {"site": SITE}}, data_dir=data.resolve())
    write_cookies(chosen.session / COOKIES, [{"name": "s", "value": "v", "domain": "x"}])
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(
        http, "client", lambda site, cookies, hooks=(): CLIENT(site, cookies, hooks, transport)
    )
    monkeypatch.setattr(time, "sleep", lambda _: None)
    return chosen


def fetch_arguments(data: Path, *options: str) -> list[str]:
    """Give the arguments of a fetch of the site into ``data``, without settings file."""
    settings = ("--config", str(data.parent / "none.toml"), "--data-dir", str(data))
    return ["fetch", "--yes", *settings, "--site", SITE, *options]


def test_fetch_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Fetched, failed, unread, skipped, retried; refused, busy, interrupted, signed out.

    A first run fetches a space and a project, with a page whose adapter refuses it, a
    video skipped and a file gone, over the period given; the next catches up on both
    from their last fetch, without --since. Then a space whose pages the site cannot
    serve, retried until they fail; a space not found; a period refused, a store busy,
    Ctrl-C, and a session no longer saved.
    """
    emitted = Emitted()
    since = ("--since", "2026-10-02")
    data = tmp_path / "data"
    fake = FakeSite(changed_labels=True, failing_files=1)
    chosen = signed_in(monkeypatch, fake.handle, data)
    with emitted.gathering(telemetry, "fetch"):
        whole = fetch_arguments(data, "--space", "MFS", "--project", "PRB", *since)
        assert main(whole) == ExitStatus.FAILED
        assert (
            main(fetch_arguments(data, "--space", "MFS", "--project", "PRB")) == ExitStatus.FAILED
        )
    signed_in(monkeypatch, FakeSite(pages_fail=True).handle, tmp_path / "retried")
    with emitted.gathering(telemetry, "fetch"):
        assert (
            main(fetch_arguments(tmp_path / "retried", "--space", "MFS", *since))
            == ExitStatus.FAILED
        )
    signed_in(monkeypatch, FakeSite(spaces=[]).handle, data)
    with emitted.gathering(telemetry, "fetch"):
        assert main(fetch_arguments(data, "--space", "NOPE", *since)) == ExitStatus.FAILED
    with emitted.gathering(telemetry, "fetch"):
        backwards = ("--since", "2026-10-22", "--until", "2026-10-01")
        assert main(fetch_arguments(data, "--space", "MFS", *backwards)) == ExitStatus.REFUSED
    with emitted.gathering(telemetry, "fetch"), RawStore(chosen.raw, "confluence").writing():
        assert main(fetch_arguments(data, "--space", "MFS", *since)) == ExitStatus.FAILED

    def interrupted(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(time, "sleep", interrupted)
    with emitted.gathering(telemetry, "fetch"):
        assert main(fetch_arguments(data, "--space", "MFS", *since)) == ExitStatus.INTERRUPTED
    (chosen.session / COOKIES).unlink()
    with emitted.gathering(telemetry, "fetch"):
        assert main(fetch_arguments(data, "--space", "MFS", *since)) == ExitStatus.SIGN_IN_AGAIN
    assert undocumented("fetch", emitted) == []


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
        signed_in(monkeypatch, FakeSite(many_pages=pages).handle, data)
        emitted = Emitted()
        with emitted.gathering(telemetry, "fetch"):
            assert main(fetch_arguments(data, "--space", "MFS", "--since", "2026-10-02")) == 0
        (root,) = (span for span in emitted.spans if span.name == "fetch")
        fetched = [span for span in emitted.spans if span.name == "fetch.document"]
        assert len(fetched) == pages + 1
        for document in fetched:
            assert (document.parent, document.trace_id != root.trace_id) == (0, True)
            assert [trace_id for trace_id, _ in document.links] == [root.trace_id]
        sizes.append(sum(1 for span in emitted.spans if span.trace_id == root.trace_id))
    three, thirty = sizes
    assert three == thirty


def a_store_with_a_page_of_each_ending(data: Path) -> None:
    """Store a page to build, one that pandoc fails on, and one whose space is not listed.

    The cache of conversions is random bytes, which the first run replaces.
    """
    store = RawStore(data / "raw", "confluence")
    listed = [listing_page("100", "Home", None, None), listing_page("101", "Broken", None, None)]
    with store.writing():
        store.put_space(v2_space(id=SPACE_ID), listed, [], [])
        store.put(Page, page_responses("100", "Home", 1, "<p>Home.</p>", []), FETCHED, {})
        store.put(Page, page_responses("101", "Broken", 1, "<p>BREAK</p>", []), FETCHED, {})
        elsewhere = page_responses("102", "Elsewhere", 1, "<p>Away.</p>", [], spaceId="999")
        store.put(Page, elsewhere, FETCHED, {})
    (data / "conversions.sqlite").write_bytes(hashlib.shake_256(b"cache").digest(8192))


def test_prepare_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Built, failed, unplaced, with a damaged cache, then a former one; then pandoc gone.

    Gone once the run began. The pandoc on PATH passes its input through, unless it holds
    BREAK. Then the work log, by the real pandoc: whole; a dry run; a problem and two
    transcripts of one id; a pandoc that gives no version; Ctrl-C; a folder that is none.
    """
    data = tmp_path / "data"
    a_store_with_a_page_of_each_ending(data)
    script = 'input=$(cat); case "$input" in *BREAK*) exit 3;; esac; printf "%s" "$input"'
    folder = fake_pandoc(tmp_path / "bin", script)
    arguments = [
        "prepare",
        "--yes",
        "--config",
        str(tmp_path / "none.toml"),
        "--data-dir",
        str(data),
    ]
    emitted = Emitted()
    with monkeypatch.context() as patch:
        patch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
        with emitted.gathering(telemetry, "prepare"):
            assert main(arguments) == ExitStatus.FAILED
        with closing(sqlite3.connect(data / "conversions.sqlite")) as connection:
            connection.executescript(
                "DROP TABLE conversions;"
                " CREATE TABLE conversions (key TEXT PRIMARY KEY, markdown TEXT NOT NULL);"
            )
        with emitted.gathering(telemetry, "prepare"):
            assert main(arguments) == ExitStatus.FAILED

        def gone() -> Pandoc:
            message = "pandoc: not found on PATH"
            raise PandocMissingError(message)

        patch.setattr(Pandoc, "find", gone)
        with emitted.gathering(telemetry, "prepare"):
            assert main(arguments) == ExitStatus.FAILED
    worklog = tmp_path / "todo"
    shutil.copytree(WORKLOG_FIXTURE, worklog)
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(worklog))
    worklog_alone = [*arguments, "worklog"]
    with emitted.gathering(telemetry, "prepare"):
        assert main(worklog_alone) == ExitStatus.OK
    with emitted.gathering(telemetry, "prepare"):
        assert main([*worklog_alone, "--dry-run"]) == ExitStatus.OK
    shutil.copytree(worklog / "transcripts/current", worklog / "transcripts/archive/2026/x")
    (worklog / "transcripts/misc/a.org").write_bytes(b"* Caf\xe9\n")
    with emitted.gathering(telemetry, "prepare"):
        assert main(worklog_alone) == ExitStatus.FAILED

    def no_version(_: Pandoc) -> str:
        message = "pandoc: exit status 9"
        raise PandocFailedError(message)

    def stopped(*_: object, **__: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(Pandoc, "org_converter", no_version)
        with emitted.gathering(telemetry, "prepare"):
            assert main(worklog_alone) == ExitStatus.FAILED
    with monkeypatch.context() as patch:
        patch.setattr(worklog_preparer, "prepare_worklog", stopped)
        with emitted.gathering(telemetry, "prepare"):
            assert main(worklog_alone) == ExitStatus.INTERRUPTED
    monkeypatch.setenv("KB_MCP_SOURCES__WORKLOG__PATH", str(tmp_path / "absent"))
    with emitted.gathering(telemetry, "prepare"):
        assert main(worklog_alone) == ExitStatus.REFUSED
    assert undocumented("prepare", emitted) == []


def by_meaning(data: Path, url: str) -> list[str]:
    """Write settings naming the tiny model at ``url``; give the options to them."""
    settings = data.parent / "config.toml"
    settings.write_text(
        f'model = "tiny"\nembedding_url = {json.dumps(url)}\n',
        encoding="utf-8",
    )
    return ["--config", str(settings), "--data-dir", str(data)]


def held_meanwhile(
    lock: Path, event: str, emitted: Emitted, then: Callable[[], object]
) -> threading.Thread:
    """Hold a lock file exclusive in a thread until a run waits for it, ``event``; then ``then``.

    Give the thread, started once it holds the lock; join it after the run.
    """
    taken = threading.Event()

    def hold() -> None:
        with lock.open("a") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            taken.set()
            deadline = time.monotonic() + 10
            while event not in emitted.events and time.monotonic() < deadline:
                time.sleep(0.01)
            then()

    thread = threading.Thread(target=hold)
    thread.start()
    assert taken.wait(10)
    return thread


def test_index_records_as_documented(telemetry: InMemory, tmp_path: Path) -> None:
    """By words alone, in the hybrid mode too: a file skipped, built whole; then updated.

    The mirror holds a page, one with a front matter refused, and the people of PERSONS,
    two of whose names could be several persons, with an alias whose key none holds, and
    two transcripts whose summaries link each other, which neither can be. An
    address off this machine, in the settings, is never asked. The update waits for the
    index's lock, then finds the index written by another run, and starts again; a run
    with nothing changed writes nothing; then no mirror.
    """
    data = tmp_path / "data"
    fillers(data / "docs", 5)
    for front in PERSONS:
        write(data / "docs", front)
    for one, other in (("t-20261022-1", "t-20261022-2"), ("t-20261022-2", "t-20261022-1")):
        write(data / "docs", worklog_document("transcript", one, "Loop", ("Alex",), other))
    (data / "aliases.toml").write_text('"Jo Placeholder" = "Robin Example"\n', encoding="utf-8")
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    options = by_meaning(data, "https://embeddings.example/v1")
    emitted = Emitted()
    with emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *options]) == ExitStatus.FAILED
    other = tmp_path / "other.sqlite"  # another run's index, of the mirror as it was
    build_index(data / "docs", other, MOMENT)
    broken.unlink()
    index = data / "index.sqlite"
    writing = held_meanwhile(
        data / "index.sqlite.lock", "index.lock_wait", emitted, lambda: other.replace(index)
    )
    with emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *options]) == ExitStatus.OK
    writing.join()
    with emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *options]) == ExitStatus.OK
    empty = tmp_path / "empty"
    with emitted.gathering(telemetry, "index"):
        assert main(["index", "--yes", *by_meaning(empty, URL)]) == ExitStatus.FAILED
    assert undocumented("index", emitted) == []
    assert not any(name.startswith(("http.", "vectors.")) for name in emitted.events)
    assert not (data / "vectors.sqlite").exists()


def test_embed_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """No index; a chunk refused during a prune; no endpoint; the mirror changed; then whole.

    The mirror holds a few pages, one with a front matter refused, which the index lacks,
    and one whose second section the endpoint refuses to embed, cut by sections. The
    last fills wait for the index's lock, then find it written by another run, and start
    again; then nothing changes, during a build. The ``index`` runs between are not
    gathered: what they record is ``index``'s.
    """
    monkeypatch.setenv("KB_MCP_CHUNKING", "sections")
    data = tmp_path / "data"
    fillers(data / "docs", 5)
    body = "# Rollback\n\nUndo the payout.\n\n## Release\n\nThe deploy of the seller service.\n"
    write(data / "docs", page("196845", "Rollback"), body)
    broken = data / "docs" / "confluence" / "ENG" / "1-broken.md"
    broken.write_text("---\ntitle: no other key\n---\n", encoding="utf-8")
    refused = "Rollback\nRelease\nThe deploy of the seller service."
    emitted = Emitted()
    with serving(Scripted()) as url, emitted.gathering(telemetry, "embed"):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    assert main(["index", "--yes", *by_meaning(data, URL)]) == ExitStatus.FAILED
    store, index = data / "vectors.sqlite", data / "index.sqlite"
    pruning = held_meanwhile(vector_cache.lock_of(store), "vectors.lock_wait", emitted, list)
    with serving(Scripted(refused={refused})) as url, emitted.gathering(telemetry, "embed"):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    pruning.join()
    with nothing_listening() as url, emitted.gathering(telemetry, "embed"):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    broken.unlink()
    write(data / "docs", page("196846", "Refund"), body.replace("payout", "refund"))
    with serving(Scripted()) as url, emitted.gathering(telemetry, "embed"):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.FAILED
    assert main(["index", "--yes", *by_meaning(data, URL)]) == ExitStatus.OK
    other = tmp_path / "other.sqlite"  # another run's index, with no chunks
    build_index(data / "docs", other, MOMENT)
    lock = vector_cache.lock_of(index)
    writing = held_meanwhile(lock, "index.lock_wait", emitted, lambda: other.replace(index))
    with serving(Scripted()) as url, emitted.gathering(telemetry, "embed"):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.OK
    writing.join()
    with (
        vector_cache.shared(store),
        serving(Scripted()) as url,
        emitted.gathering(telemetry, "embed"),
    ):
        assert main(["embed", "--yes", *by_meaning(data, url)]) == ExitStatus.OK
    assert undocumented("embed", emitted) == []
    assert emitted.events["embed.mirror_changed"] == {"changed", "added", "removed", "hint"}


def test_serve_records_as_documented(tmp_path: Path) -> None:
    """By meaning, each tool and a call refused; then, the endpoint stopped, by words alone.

    The second also lists the prompts, and writes one. Both rerank: the first through a
    scripted reranking server, the second through none, which falls back.

    The first server is spoken to as an agent does, from ``initialize``; the second by
    the SDK's client, from ``server/discover``. Each runs in a fresh interpreter, as
    agents start it, kept to the ports of the endpoint and of a scripted collector, which
    its telemetry goes to, with ``LIMIT_S`` seconds at its end: what it logged is read
    from its file, what it traced and measured at the collector.
    """
    data = tmp_path / "data"
    fillers(data / "docs")
    write(data / "docs", page("4002", "Holiday canteen", space="ENG"), "Leave for a meal.\n")
    write(data / "docs", issue("PROJ-7", "Kafka upgrade"))
    build_index(data / "docs", data / "index.sqlite", MOMENT, Embedding(tiny(), data / "v.db"))
    calls: list[tuple[str, dict[str, object]]] = [
        ("search", {"query": "vacation lunch"}),
        ("ask", {"question": "vacation lunch"}),
        ("read", {"ref": "PROJ-7"}),
        ("browse", {"space": "ENG"}),
        ("status", {}),
        ("search", {"query": "kafka", "filters": {"space": "NOPE"}}),
    ]

    async def search(command: StdioServerParameters) -> None:
        async with Client(command) as client:
            with anyio.fail_after(WAIT_S):
                await client.call_tool("search", {"query": "vacation lunch"})
                await client.call_tool("search", {"query": "lorem"})  # words find, to rerank
                await client.list_prompts()
                await client.get_prompt("brief", {"ref": "PROJ-7"})

    emitted = Emitted()
    for name, stopped in (("answering", False), ("stopped", True)):
        home, collector = tmp_path / name, Collector()
        with (
            nothing_listening() if stopped else serving(Scripted()) as url,
            nothing_listening() if stopped else serving(Reranks()) as reranking,
            collecting(collector) as endpoint,
        ):
            folder = home / ".config" / "kb-mcp"
            folder.mkdir(parents=True)
            (folder / "config.toml").write_text(
                f'data_dir = {json.dumps(str(data))}\nmodel = "tiny"\nsearch_mode = "hybrid"\n'
                f"embedding_url = {json.dumps(url)}\n"
                f"[telemetry]\nendpoint = {json.dumps(endpoint)}\n"
                f"[rerank]\nenabled = true\nurl = {json.dumps(reranking)}\ndepth = 4\n",
                encoding="utf-8",
            )
            places = (url, reranking, endpoint)
            ports = [int(each.rpartition(":")[2].partition("/")[0]) for each in places]
            given = {"ports": ports, "limit": LIMIT_S, "report": str(home / "report.json")}
            command = StdioServerParameters(
                command=sys.executable,
                args=["-m", "tests.guarded", json.dumps({**given, "arguments": ["serve"]})],
                env={"HOME": str(home)},
                cwd=ROOT,
            )
            if stopped:
                anyio.run(search, command)
            else:
                _, _, results = talk(command, calls)
                assert [result["isError"] for result in results] == [False] * 5 + [True]
        (log_file,) = user_log_folder(home).iterdir()
        emitted.collected(log_file, collector)
    assert undocumented("serve", emitted) == []


def test_eval_records_as_documented(telemetry: InMemory, tmp_path: Path) -> None:
    """Evaluated; a golden file refused; a query refused, so words for meaning; no endpoint.

    The mirror holds the golden questions' documents and fillers, indexed by words. The
    endpoint refuses to embed the second question, which a search by meaning then ranks
    by words.
    """
    data = tmp_path / "data"
    docs = data / "docs"
    fillers(docs)
    write(docs, page("4002", "Holiday canteen"), "# Holiday canteen\n\nLeave for a **meal**.\n")
    write(docs, page("4003", "Words"), "revert release\n")
    write(docs, issue("PROJ-7", "Kafka upgrade"))
    build_index(docs, data / "index.sqlite", MOMENT)
    golden = tmp_path / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    refused = tmp_path / "refused.yaml"
    refused.write_text("- {id: q1, question: x}\n", encoding="utf-8")
    emitted = Emitted()
    with serving(Scripted()) as url, emitted.gathering(telemetry, "eval"):
        assert main(["eval", "--yes", str(golden), *by_meaning(data, url)]) == 0
    with emitted.gathering(telemetry, "eval"):
        assert main(["eval", "--yes", str(refused), *by_meaning(data, URL)]) == ExitStatus.REFUSED
    answers = Scripted(refused={"revert release"})
    with serving(answers) as url, emitted.gathering(telemetry, "eval"):
        assert main(["eval", "--yes", str(golden), *by_meaning(data, url)]) == ExitStatus.FAILED
    with nothing_listening() as url, emitted.gathering(telemetry, "eval"):
        assert main(["eval", "--yes", str(golden), *by_meaning(data, url)]) == ExitStatus.FAILED
    assert undocumented("eval", emitted) == []


def test_check_records_as_documented(telemetry: InMemory, tmp_path: Path) -> None:
    """Nothing of its own: a run that reads the settings, and shows them."""
    settings = ["--config", str(tmp_path / "none.toml"), "--data-dir", str(tmp_path / "data")]
    emitted = Emitted()
    with emitted.gathering(telemetry, "check"):
        assert main(["check", *settings]) == 0
    assert undocumented("check", emitted) == []


def test_completion_records_as_documented(telemetry: InMemory) -> None:
    """Nothing at all, not even what the README says every command records: not observed.

    Its page lists nothing, and no event, span, instrument or record is emitted, even
    at -vv.
    """
    emitted = Emitted()
    with emitted.gathering(telemetry, "completion"):
        assert main(["completion", "-vv"]) == 0
    assert undocumented("completion", emitted) == []
    assert emitted == Emitted()


def test_doctor_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Signed in to Confluence; Jira busy, retried at once until the check fails.

    The certificate's check, which would reach the site itself, is said to pass.
    """

    def busy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/api/3/myself":
            return httpx.Response(503, headers={"retry-after": "0"})
        return FakeSite().handle(request)

    data = tmp_path / "data"
    signed_in(monkeypatch, busy, data)
    monkeypatch.setattr(http, "verified_by_public_cas", lambda _: True)
    arguments = ["doctor", "--config", str(tmp_path / "none.toml"), "--data-dir", str(data)]
    emitted = Emitted()
    with emitted.gathering(telemetry, "doctor"):
        assert main([*arguments, "--site", SITE]) == ExitStatus.FAILED
    assert undocumented("doctor", emitted) == []


def test_login_records_as_documented(
    telemetry: InMemory, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """Signed in, then a window closed: the browser is a stand-in, which signs in nowhere."""
    arguments = [
        "login",
        "atlassian",
        "--yes",
        "--config",
        str(tmp_path / "none.toml"),
        "--site",
        SITE,
    ]
    emitted = Emitted()
    monkeypatch.setattr(login_module, "save_session", lambda *_, **__: None)
    with emitted.gathering(telemetry, "login"):
        assert main(arguments) == 0

    def closed(*_: object, **__: object) -> None:
        message = "the sign-in window was closed"
        raise SignInFailedError(message)

    monkeypatch.setattr(login_module, "save_session", closed)
    with emitted.gathering(telemetry, "login"):
        assert main(arguments) == ExitStatus.SIGN_IN_AGAIN
    assert undocumented("login", emitted) == []


def test_model_records_as_documented(telemetry: InMemory, tmp_path: Path) -> None:
    """The tiny model ready; then no endpoint listening."""
    data = tmp_path / "data"
    emitted = Emitted()
    with serving(Scripted()) as url, emitted.gathering(telemetry, "model"):
        assert main(["model", "check", *by_meaning(data, url)]) == 0
    with nothing_listening() as url, emitted.gathering(telemetry, "model"):
        assert main(["model", "check", *by_meaning(data, url)]) == ExitStatus.FAILED
    assert undocumented("model", emitted) == []

"""``eval-agents``: prepare, the bridge to the real server over stdio, answers, grading (019).

The server is the command's own ``serve``, by meaning through 018's scripted endpoint,
started by the bridge as an agent's call starts it. The scripted agent at the end is
plain code that reads each prompt and runs the commands that it names.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shlex
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from kb_mcp.cli.main import main
from kb_mcp.evaluation.adapters.mcp_client import Answered
from kb_mcp.evaluation.app import agents
from kb_mcp.mcp.app.tools import Library
from kb_mcp.search.app.indexing import Embedding, build_index
from kb_mcp.search.app.meaning import Meaning
from tests.answers import estimate, parts
from tests.endpoint import Scripted, connector, serving, tiny
from tests.mirrors import MOMENT, fillers, issue, page, write
from tests.reference import Emitted, undocumented
from tests.test_observed import said as said_on

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from _pytest.tmpdir import TempPathFactory

    from tests.conftest import InMemory

QUESTIONS = {
    "q1": "How long does Kafka keep its logs?",
    "q2": "When are the brokers upgraded?",
    "q3": "Who is on call this week?",
    "q4": "What is the holiday canteen?",
}
# Each question's document, and the evidence that it holds, if any.
EXPECTED = {
    "q1": ("196845", "seven days"),
    "q2": ("PROJ-7", "in May"),
    "q3": ("196846", "on call"),
    "q4": ("196847", None),
}
GOLDEN = json.dumps(
    [
        {
            "id": name,
            "question": QUESTIONS[name],
            "expected": [ref],
            "evidence": {ref: phrase} if phrase else {},
        }
        for name, (ref, phrase) in EXPECTED.items()
    ]
)
FAILED, REFUSED, DECLINED = 1, 2, 1
CALLS = 12
SENTINEL = "answer-sentinel-5c1e"
MODEL = "claude-haiku-test"
VALID = {"found": True, "answer": "Seven days.", "sources": ["196845"]}
# A call as the bridge logs it.
LOGGED = '{"tool": "search", "arguments": {}, "tokens": 9, "seconds": 1.0, "status": "answered"}\n'
# The command line of eval-agents, as a prompt names it.
PROGRAM = [sys.executable, "-m", "kb_mcp", "eval-agents"]


@dataclass(frozen=True)
class World:
    """A scratch home whose settings serve a mirror by meaning, and a golden file."""

    home: Path
    data: Path
    golden: Path
    root: Path
    logs: Path


@pytest.fixture
def world(
    tmp_path: Path, tmp_path_factory: TempPathFactory, monkeypatch: MonkeyPatch
) -> Iterator[World]:
    """Index a mirror with the tiny model; settings search it in hybrid mode, endpoint up.

    The runs' log files, plan 016's, go to a folder of their own, beside the world, so
    that what the world holds is what the runs wrote of their own.
    """
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "kb-mcp").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    docs = data / "docs"
    fillers(docs)
    write(docs, page("196845", "Kafka"), "# Kafka\n\nKafka keeps its logs for seven days.\n")
    write(docs, issue("PROJ-7", "Upgrade"), "# Upgrade\n\nThe brokers move to 4.0 in May.\n")
    write(docs, page("196846", "Rota"), "# Rota\n\nAda is on call this week.\n")
    write(docs, page("196847", "Holiday canteen"), "# Holiday canteen\n\nLeave for a meal.\n")
    build_index(docs, data / "index.sqlite", MOMENT, Embedding(tiny(), data / "vectors.sqlite"))
    golden = tmp_path / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    logs = tmp_path_factory.mktemp("logs")
    with serving(Scripted()) as url:
        (home / ".config" / "kb-mcp" / "config.toml").write_text(
            f'data_dir = {json.dumps(str(data))}\nmodel = "tiny"\nsearch_mode = "hybrid"\n'
            f"embedding_url = {json.dumps(url)}\n"
            f"[logs]\ndir = {json.dumps(str(logs))}\n"
            "[rerank]\nenabled = false\n",  # the server that call starts: no reranker here
            encoding="utf-8",
        )
        yield World(home, data, golden, tmp_path, logs)


def prepared(world: World, out: Path, *more: str) -> int:
    """Prepare runs for Haiku into ``out``, without asking."""
    given = [str(world.golden), "--out", str(out), "--model", "haiku", "--yes", *more]
    return main(["eval-agents", "prepare", *given])


def runs_of(out: Path) -> list[dict[str, str]]:
    """Read the runs that ``prepare`` wrote, in their order."""
    return json.loads((out / "runs.json").read_text(encoding="utf-8"))["runs"]


def first(out: Path, surface: str) -> str:
    """Give the id of the first run on a surface."""
    return next(run["id"] for run in runs_of(out) if run["surface"] == surface)


def tree(folder: Path) -> list[str]:
    """List what a folder holds, at any depth."""
    return sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*"))


def bridged(out: Path, run: str, tool: str, arguments: object) -> list[str]:
    """Give the arguments of ``main`` for a call through the bridge."""
    return ["eval-agents", "call", str(out), run, tool, json.dumps(arguments)]


def test_one_seed_gives_the_same_files_and_each_surface_comes_first_half_the_time(
    world: World,
) -> None:
    """Two directories, one seed: the same runs and prompts, the directory aside."""
    one, two = world.root / "one", world.root / "two"
    assert prepared(world, one, "--sample", "2", "--seed", "5") == 0
    assert prepared(world, two, "--sample", "2", "--seed", "5") == 0
    prompts = [f"prompts/r00{number}.md" for number in range(1, 5)]
    assert tree(one) == tree(two) == ["prompts", *prompts, "runs.json"]
    for name in prompts:
        said = (one / name).read_text("utf-8").replace(str(one.resolve()), "DIR")
        assert said == (two / name).read_text("utf-8").replace(str(two.resolve()), "DIR")
    # Each prompt names its directory, and so has a hash of its own.
    unhashed = [
        [
            {key: value for key, value in run.items() if key != "prompt_sha256"}
            for run in runs_of(out)
        ]
        for out in (one, two)
    ]
    assert unhashed[0] == unhashed[1]
    runs = runs_of(one)
    assert all(
        run["prompt_sha256"] == hashlib.sha256((one / run["prompt"]).read_bytes()).hexdigest()
        for run in runs
    )
    assert [run["surface"] for run in runs] == ["A", "B", "B", "A"]
    assert [run["question"] for run in runs[::2]] == [run["question"] for run in runs[1::2]]
    assert all(QUESTIONS[run["question"]] in (one / run["prompt"]).read_text() for run in runs)


def listing(server: list[str], home: Path) -> tuple[str, list[dict[str, object]]]:
    """Ask a server what it lists, as a client: its instructions and tools."""
    found: list[tuple[str, list[dict[str, object]]]] = []

    async def session() -> None:
        command = StdioServerParameters(command=server[0], args=server[1:], env={"HOME": str(home)})
        async with Client(command) as client:
            tools = (await client.list_tools()).tools
            fields = {"name", "description", "input_schema"}
            found.append(
                (
                    client.instructions or "",
                    [
                        tool.model_dump(
                            mode="json", by_alias=True, exclude_none=True, include=fields
                        )
                        for tool in tools
                    ],
                )
            )

    anyio.run(session)
    return found[0]


def test_each_prompt_holds_what_serve_lists_for_its_surface(world: World) -> None:
    """The instructions and tools that ``serve --tools`` lists, as an agent would see them."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    server = json.loads((out / "runs.json").read_text("utf-8"))["server"]
    for run in runs_of(out):
        prompt = (out / run["prompt"]).read_text("utf-8")
        instructions, tools = listing([*server, "--tools", ",".join(run["tools"])], world.home)
        said = prompt.split("The server's instructions:\n")[1].split("\n\nIts tools,")[0]
        listed = prompt.split("as it lists them:\n")[1].split("\n\nTo call a tool")[0]
        assert (said, json.loads(listed)) == (instructions, tools)
        assert ("ask" in [tool["name"] for tool in tools]) is (run["surface"] == "B")


def test_the_remote_flag_reaches_the_server_exactly_when_given(world: World) -> None:
    """``--allow-remote-embeddings`` given to prepare is given to every server it names."""
    given, not_given = world.root / "given", world.root / "not-given"
    assert prepared(world, given, "--sample", "1", "--allow-remote-embeddings") == 0
    assert prepared(world, not_given, "--sample", "1") == 0
    servers = [json.loads((out / "runs.json").read_text())["server"] for out in (given, not_given)]
    assert ["--allow-remote-embeddings" in server for server in servers] == [True, False]


def test_a_call_prints_serve_s_answer_alone_and_logs_five_fields(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Ask on B, as the library answers it here; the log holds the call, never more."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    capsys.readouterr()
    run = first(out, "B")
    assert main(bridged(out, run, "ask", {"question": QUESTIONS["q1"]})) == 0
    printed = capsys.readouterr().out
    library = Library(
        world.data / "index.sqlite", world.data / "docs", Meaning(connector()), "hybrid"
    )
    answer = library.ask(QUESTIONS["q1"])
    assert printed == f"{answer}\n"
    [line] = (out / "calls" / f"{run}.jsonl").read_text("utf-8").splitlines()
    logged = json.loads(line)
    assert set(logged) == {"tool", "arguments", "tokens", "seconds", "status"}
    assert (logged["tool"], logged["arguments"], logged["status"]) == (
        "ask",
        {"question": QUESTIONS["q1"]},
        "answered",
    )
    assert logged["tokens"] == estimate(answer)


@dataclass(frozen=True)
class Refused:
    """A call that the bridge refuses, the calls made before it, and what the refusal says.

    Its run is the first on A unless one is named.
    """

    run: str | None
    tool: str
    arguments: object
    spent: int
    named: str


@pytest.mark.parametrize(
    "case",
    [
        Refused("r999", "search", {"query": "kafka"}, 0, "run: no such run"),
        Refused(None, "search", [1], 0, "JSON: the arguments must be one JSON object"),
        Refused(None, "ask", {"question": "kafka"}, 0, "tool: not served on this run's surface"),
        Refused(None, "search", {"query": "kafka"}, CALLS, "calls: this run's 12 are spent"),
    ],
)
def test_a_refused_call_exits_2_and_starts_no_server(
    world: World, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str], case: Refused
) -> None:
    """A run not there, arguments not an object, a tool not served, the 13th call."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = case.run or first(out, "A")
    (out / "calls").mkdir()
    (out / "calls" / f"{run}.jsonl").write_text(LOGGED * case.spent, "utf-8")

    def no_server(*_: object) -> None:
        message = "a server was started"
        raise AssertionError(message)

    monkeypatch.setattr(agents, "called", no_server)
    capsys.readouterr()
    assert main(bridged(out, run, case.tool, case.arguments)) == REFUSED
    assert case.named in capsys.readouterr().err


def command(out: Path, run: str, *more: str) -> list[str]:
    """Give the bridge's command line, as a prompt names it, for a run of ``out``."""
    prompt = (out / "prompts" / f"{run}.md").read_text("utf-8")
    line = next(line for line in prompt.splitlines() if line.endswith(" TOOL 'JSON'"))
    return [*shlex.split(line.removesuffix(" TOOL 'JSON'")), *more]


def test_two_calls_at_once_at_the_twelfth_give_one_answer(world: World) -> None:
    """Eleven made: of two calls at once, one is answered, the other refused, under a lock.

    Each call is a process of its own, as an agent's are, with the world's home.
    """
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = first(out, "A")
    (out / "calls").mkdir()
    (out / "calls" / f"{run}.jsonl").write_text(LOGGED * (CALLS - 1), "utf-8")
    calling = [
        sys.executable,
        "-m",
        "kb_mcp",
        *bridged(out, run, "search", {"query": "kafka"}),
    ]
    statuses: list[int] = []

    async def call() -> None:
        statuses.append((await anyio.run_process(calling, check=False)).returncode)

    async def both() -> None:
        async with anyio.create_task_group() as group:
            group.start_soon(call)
            group.start_soon(call)

    anyio.run(both)
    assert sorted(statuses) == [0, REFUSED]
    assert len((out / "calls" / f"{run}.jsonl").read_text("utf-8").splitlines()) == CALLS


def test_a_call_past_its_deadline_stops_the_server_and_is_logged(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """A deadline of a hundredth of a second: no answer, exit 1, the call logged timeout."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    runs = json.loads((out / "runs.json").read_text("utf-8"))
    (out / "runs.json").write_text(json.dumps({**runs, "call_s": 0.01}), "utf-8")
    run = first(out, "A")
    capsys.readouterr()
    started = time.monotonic()
    assert main(bridged(out, run, "search", {"query": "kafka"})) == FAILED
    assert time.monotonic() - started < CALLS
    assert capsys.readouterr().out.startswith("no answer within 0.01 seconds")
    [line] = (out / "calls" / f"{run}.jsonl").read_text("utf-8").splitlines()
    assert json.loads(line)["status"] == "timeout"


class Terminal(io.StringIO):
    """A terminal, as a run sees its stdin or its stderr: text that says it is one."""

    @override
    def isatty(self) -> bool:
        return True


def test_prepare_says_its_runs_bound_and_estimates_then_asks(
    world: World, monkeypatch: MonkeyPatch
) -> None:
    """Declined: exit 1, and no directory; the summary came before the question."""
    out = world.root / "runs"
    stdin, stderr = Terminal("n\n"), Terminal()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    golden = str(world.golden)
    given = ["prepare", golden, "--out", str(out), "--model", "haiku", "--sample", "2"]
    assert main(["eval-agents", *given]) == DECLINED
    said = stderr.getvalue()
    lines = ("bound: 12 calls of 60 s at most per run", "in all: 4 runs, 48 calls at most")
    assert all(-1 < said.index(line) < said.index("Proceed?") for line in lines)
    assert not out.exists()


def test_each_step_logs_to_a_file_of_its_command_which_expires_as_any(world: World) -> None:
    """Named ``eval-agents-<start>-<pid>.jsonl``, by plan 016's pattern: one of 2019 goes.

    A step's file named after the step, with its space, would match no command's
    pattern, and stay past its 30 days. Beside prepare's and the call's, the folder
    holds the files of the servers that they started.
    """
    expired = "eval-agents-20190101T000000Z-1.jsonl"
    (world.logs / expired).write_text("", "utf-8")
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    assert main(bridged(out, first(out, "A"), "status", {})) == 0
    names = [path.name for path in world.logs.iterdir()]
    assert all(
        re.fullmatch(r"[a-z][a-z-]*-[0-9]{8}T[0-9]{6}Z-[0-9]+\.jsonl", name) for name in names
    )
    assert len([name for name in names if name.startswith("eval-agents-")]) == len(
        ["prepare", "call"]
    )
    assert expired not in names


def test_a_dry_run_creates_nothing(world: World, capsys: CaptureFixture[str]) -> None:
    """It says what it would prepare, and writes no file."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "2", "--dry-run") == 0
    assert capsys.readouterr().out == f"4 runs would be prepared in {out}\n"
    assert not out.exists()


@pytest.mark.parametrize(
    ("place", "named"),
    [
        ("full", "--out: not empty"),
        ("home/Dropbox/runs", "--out: under a Dropbox folder"),
        ("repository/runs", "--out: inside the git working tree"),
    ],
)
def test_a_directory_not_empty_synced_or_in_a_git_tree_is_refused(
    world: World, capsys: CaptureFixture[str], place: str, named: str
) -> None:
    """Exit 2, the directory as it was."""
    (world.root / "full").mkdir()
    (world.root / "full" / "kept").write_text("", "utf-8")
    (world.root / "repository" / ".git").mkdir(parents=True)
    out = world.root / place
    before = tree(world.root)
    assert prepared(world, out) == REFUSED
    assert named in capsys.readouterr().err
    assert tree(world.root) == before


def test_call_and_answer_ask_nothing(world: World, monkeypatch: MonkeyPatch) -> None:
    """On terminals, a yes waiting: neither reads it, nor says a summary."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    stdin, stderr = Terminal("y\n"), Terminal()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stderr", stderr)
    run = first(out, "B")
    assert main(bridged(out, run, "ask", {"question": QUESTIONS["q1"]})) == 0
    assert main(["eval-agents", "answer", str(out), run, json.dumps(VALID)]) == 0
    assert stdin.read() == "y\n"
    assert "Proceed?" not in stderr.getvalue()


def answering(out: Path, run: str, given: str) -> int:
    """Send an answer for a run."""
    return main(["eval-agents", "answer", str(out), run, given])


def test_an_answer_is_read_strictly_kept_once_and_refused_twice_at_most(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Refused, naming the field, never the value; resent, kept; refused twice, a failure."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    first_run, second_run = (run["id"] for run in runs_of(out))
    capsys.readouterr()
    assert answering(out, first_run, json.dumps({"found": SENTINEL})) == REFUSED
    said = capsys.readouterr().err
    assert "found: " in said
    assert "send it once more" in said
    assert SENTINEL not in said
    assert answering(out, first_run, json.dumps(VALID)) == 0
    assert answering(out, first_run, json.dumps(VALID)) == REFUSED
    assert "is kept already" in capsys.readouterr().err
    assert answering(out, second_run, "{}") == REFUSED
    assert answering(out, second_run, "[]") == REFUSED
    assert "kept as your failure" in capsys.readouterr().err
    assert answering(out, second_run, json.dumps(VALID)) == REFUSED
    assert "was refused twice" in capsys.readouterr().err


def harness(out: Path, run: str, **fields: object) -> None:
    """Write the orchestrator's harness file of a run."""
    (out / "harness").mkdir(exist_ok=True)
    (out / "harness" / f"{run}.json").write_text(json.dumps(fields), "utf-8")


def answer_line(out: Path, run: str) -> list[str]:
    """Give the answer's command line, as a prompt names it, for a run of ``out``."""
    prompt = (out / "prompts" / f"{run}.md").read_text("utf-8")
    lines = prompt.splitlines()
    line = next(line for line in lines if line.endswith(" 'JSON'") and " TOOL " not in line)
    return shlex.split(line.removesuffix(" 'JSON'"))


def test_a_scripted_agent_reads_its_prompt_runs_its_bridge_and_is_graded(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Ask once on B, search then read on A, then the answer; grade counts what was spent.

    The commands are those that each prompt names, run as the program itself.
    """
    out = world.root / "runs"
    before = [path for path in tree(world.root) if not path.startswith("runs")]
    assert prepared(world, out, "--sample", "2") == 0
    handed: dict[str, int] = {}
    for run in runs_of(out):
        prompt = (out / run["prompt"]).read_text("utf-8")
        question = prompt.split("Question: ")[1].split("\n")[0]
        bridge, answering_ = command(out, run["id"]), answer_line(out, run["id"])
        assert bridge[: len(PROGRAM)] == answering_[: len(PROGRAM)] == PROGRAM

        def through(tool: str, arguments: dict[str, object], bridge: list[str] = bridge) -> str:
            capsys.readouterr()
            assert main([*bridge[3:], tool, json.dumps(arguments)]) == 0
            return capsys.readouterr().out.removesuffix("\n")

        if run["surface"] == "B":
            got = [through("ask", {"question": question})]
            ref = re.findall(r"^1\. .*? \| (\S+) \| section", parts(got[0])[1], re.MULTILINE)[0]
        else:
            found = through("search", {"query": question})
            [(ref, section)] = re.findall(r'read\(ref="([^"]+)", section=(\d+)\)', found)[:1]
            got = [found, through("read", {"ref": ref, "section": int(section)})]
        # The first passage, or the section read: its last line holds the answer here.
        quoted = parts(got[-1])[1].split("\n\n2. ")[0]
        sentence = [line for line in quoted.splitlines() if line.strip()][-1]
        reply = {"found": True, "answer": sentence, "sources": [ref]}
        reply["quotes"] = [{"ref": ref, "text": sentence}]
        assert main([*answering_[3:], json.dumps(reply)]) == 0
        harness(out, run["id"], status="returned", model=MODEL, tokens=1000)
        handed[run["id"]] = sum(estimate(each) for each in got)
    capsys.readouterr()
    assert main(["eval-agents", "--format", "json", "grade", str(out), "--yes"]) == 0
    results = json.loads(capsys.readouterr().out)
    outcomes = {each["run"]: each for each in results["outcomes"]}
    assert {each["result"] for each in outcomes.values()} == {"success"}
    assert (results["pairs"], results["left_out"]) == (len(("q", "q")), 0)
    assert {name: each["calls"] for name, each in outcomes.items()} == {
        run["id"]: {"ask": 1} if run["surface"] == "B" else {"search": 1, "read": 1}
        for run in runs_of(out)
    }
    assert {name: each["handed"] for name, each in outcomes.items()} == handed
    kept = (out / "results.json").read_text("utf-8")
    assert json.loads(kept)["models"] == [MODEL]
    assert all(
        outcomes[run["id"]]["prompt_sha256"]
        == hashlib.sha256((out / run["prompt"]).read_bytes()).hexdigest()
        for run in runs_of(out)
    )
    assert not any(text in kept for text in QUESTIONS.values())
    assert [path for path in tree(world.root) if not path.startswith("runs")] == before


def test_runs_that_failed_broke_a_rule_or_lost_their_server_give_no_result(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Returned without an answer: a failure; failed, invalid, a call timed out: no result.

    Their questions are out of the tests, and counted.
    """
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "2") == 0
    first_run, second, third, fourth = (run["id"] for run in runs_of(out))
    harness(out, first_run, status="returned")
    harness(out, second, status="failed")
    harness(out, third, status="invalid")
    harness(out, fourth, status="returned")
    (out / "calls").mkdir()
    line = {"tool": "search", "arguments": {}, "tokens": 0, "seconds": 60, "status": "timeout"}
    (out / "calls" / f"{fourth}.jsonl").write_text(json.dumps(line) + "\n", "utf-8")
    assert main(["eval-agents", "answer", str(out), fourth, json.dumps(VALID)]) == 0
    capsys.readouterr()
    assert main(["eval-agents", "--format", "json", "grade", str(out), "--yes"]) == 0
    results = json.loads(capsys.readouterr().out)
    assert [(each["result"], each["reason"]) for each in results["outcomes"]] == [
        ("failure", "no answer accepted"),
        ("no result", "failed"),
        ("no result", "invalid"),
        ("no result", "a call timeout"),
    ]
    assert results["counted"] == {"failure": 1, "no result": 3}
    assert (results["pairs"], results["left_out"]) == (0, len(("q", "q")))


def test_a_harness_file_not_as_written_exits_2_naming_run_and_field(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Its value is never said."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = runs_of(out)[0]["id"]
    harness(out, run, status=SENTINEL)
    capsys.readouterr()
    assert main(["eval-agents", "grade", str(out), "--yes"]) == REFUSED
    said = capsys.readouterr().err
    assert f"harness/{run}.json: status: " in said
    assert SENTINEL not in said


def test_grade_exits_1_past_twice_the_estimates(world: World, capsys: CaptureFixture[str]) -> None:
    """Model tokens reported past twice the estimate: the runs stop, the results kept."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    for run in runs_of(out):
        harness(out, run["id"], status="returned", tokens=10**9)
    capsys.readouterr()
    assert main(["eval-agents", "grade", str(out), "--yes"]) == FAILED
    said = capsys.readouterr().err
    assert said_on(said) == [("error", "eval.agent.past_estimates")]
    assert f"model_tokens={2 * 10**9}" in said
    assert (out / "results.json").exists()


@pytest.mark.parametrize("given", [[], ["--data-dir", "DATA", "--allow-remote-embeddings"]])
def test_each_call_starts_the_server_that_prepare_named(
    world: World, monkeypatch: MonkeyPatch, given: list[str]
) -> None:
    """The settings file, the data directory and 018's flag, as prepare was given them."""
    out = world.root / "runs"
    options = [str(world.data) if each == "DATA" else each for each in given]
    assert prepared(world, out, "--sample", "1", *options) == 0
    started: list[list[str]] = []

    def recorded(server: list[str], *_: object) -> Answered:
        started.append(server)
        return Answered("an answer", refused=False)

    monkeypatch.setattr(agents, "called", recorded)
    run = runs_of(out)[0]
    assert main(bridged(out, run["id"], "search", {"query": "kafka"})) == 0
    config = str((world.home / ".config" / "kb-mcp" / "config.toml").absolute())
    serve = [*PROGRAM[:3], "serve", "--config", config, *options]
    assert started == [[*serve, "--tools", ",".join(run["tools"])]]


@pytest.mark.parametrize(
    ("place", "written", "named"),
    [
        ("calls", '{"tool": "search"}\n', "calls/{run}.jsonl: arguments: Field required"),
        (
            "calls",
            '{"tool": "search", "arguments": {}, "tokens": 1, "seconds\n',
            "calls/{run}.jsonl:",
        ),
        ("answers", '{"found": true}', "answers/{run}.json: answer: Field required"),
    ],
)
def test_a_call_log_or_an_answer_not_as_written_exits_2_naming_it(
    world: World, capsys: CaptureFixture[str], place: str, written: str, named: str
) -> None:
    """The agents can write the directory: grade refuses what its own steps never wrote."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = runs_of(out)[0]["id"]
    harness(out, run, status="returned")
    (out / place).mkdir(exist_ok=True)
    name = f"{run}.jsonl" if place == "calls" else f"{run}.json"
    (out / place / name).write_text(written, "utf-8")
    capsys.readouterr()
    assert main(["eval-agents", "grade", str(out), "--yes"]) == REFUSED
    assert named.format(run=run) in capsys.readouterr().err


def test_grade_exits_1_past_twice_the_tokens_handed_over(
    world: World, capsys: CaptureFixture[str]
) -> None:
    """Calls that handed over past twice the estimate: the runs stop."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    (out / "calls").mkdir()
    for run in runs_of(out):
        harness(out, run["id"], status="returned")
        line = json.loads(LOGGED) | {"tokens": 10**6}
        (out / "calls" / f"{run['id']}.jsonl").write_text(json.dumps(line) + "\n", "utf-8")
    capsys.readouterr()
    assert main(["eval-agents", "grade", str(out), "--yes"]) == FAILED
    said = capsys.readouterr().err
    assert said_on(said) == [("error", "eval.agent.past_estimates")]
    assert f"handed={2 * 10**6}" in said


@pytest.mark.parametrize("status", ["failed", "invalid"])
def test_the_answer_of_a_run_without_a_result_is_not_read(
    world: World, capsys: CaptureFixture[str], status: str
) -> None:
    """Junk where the answer of a run failed or invalid would be: grading goes on."""
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = runs_of(out)[0]["id"]
    harness(out, run, status=status)
    (out / "answers").mkdir()
    (out / "answers" / f"{run}.json").write_text("not an answer", "utf-8")
    capsys.readouterr()
    assert main(["eval-agents", "--format", "json", "grade", str(out), "--yes"]) == 0
    outcomes = json.loads(capsys.readouterr().out)["outcomes"]
    assert (outcomes[0]["result"], outcomes[0]["reason"]) == ("no result", status)


def test_eval_agents_records_as_documented(
    world: World, telemetry: InMemory, monkeypatch: MonkeyPatch
) -> None:
    """Each step as an agent or the orchestrator runs it, and their refusals and failures.

    Plan 016's criterion 10: prepared; a call answered, then one refused; an answer kept;
    graded, then graded past the estimates; a directory refused; a surface whose server
    lists nothing in time. The servers that the steps start record in processes of their
    own, as ``serve.md`` lists it.
    """
    out = world.root / "runs"
    emitted = Emitted()
    with emitted.gathering(telemetry, "eval-agents"):
        assert prepared(world, out, "--sample", "1") == 0
        run = first(out, "B")
        assert main(bridged(out, run, "ask", {"question": QUESTIONS["q1"]})) == 0
        assert main(bridged(out, run, "nope", {})) == REFUSED
        assert main(["eval-agents", "answer", str(out), run, json.dumps(VALID)]) == 0
        for each in runs_of(out):
            harness(out, each["id"], status="returned", model=MODEL, tokens=1000)
        assert main(["eval-agents", "grade", str(out), "--yes"]) == 0
        for each in runs_of(out):
            harness(out, each["id"], status="returned", model=MODEL, tokens=10**9)
        assert main(["eval-agents", "grade", str(out), "--yes"]) == FAILED
        assert prepared(world, out) == REFUSED
        monkeypatch.setattr(agents, "LISTING_S", 0.001)
        assert prepared(world, world.root / "unlisted") == FAILED
    assert undocumented("eval-agents", emitted) == []


def test_calls_and_runs_are_measured_as_the_call_logs_and_the_results_say(
    world: World, telemetry: InMemory
) -> None:
    """Ask answered on B, a search that A's tool refuses; graded, A without an answer.

    B's answer quotes the evidence, a success; A's run, without one, a failure.

    Each call is counted by surface, tool and status, its tokens and seconds measured
    as its line of the call log has them; each run is counted by its outcome.
    """
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    a, b = first(out, "A"), first(out, "B")
    assert main(bridged(out, b, "ask", {"question": QUESTIONS["q1"]})) == 0
    assert main(bridged(out, a, "search", {"query": "kafka", "filters": {"space": "NOPE"}})) == 0
    # B quotes its question's expected document, its evidence, or a sentence of it.
    asked = next(each["question"] for each in runs_of(out) if each["id"] == b)
    ref, phrase = EXPECTED[asked]
    quote = {"ref": ref, "text": phrase or "Leave for a meal."}
    reply = {"found": True, "answer": quote["text"], "sources": [ref], "quotes": [quote]}
    assert main(["eval-agents", "answer", str(out), b, json.dumps(reply)]) == 0
    for run in (a, b):
        harness(out, run, status="returned", model=MODEL, tokens=1000)
    assert main(["eval-agents", "grade", str(out), "--yes"]) == 0
    measured = telemetry.measured()

    def points(name: str, *keys: str) -> dict[tuple[str, ...], object]:
        return {
            tuple(str((point.attributes or {})[key]) for key in keys): point
            for point in measured[name].data.data_points
        }

    lines = {
        surface: json.loads((out / "calls" / f"{run}.jsonl").read_text("utf-8"))
        for surface, run in (("A", a), ("B", b))
    }
    called = points(
        "kb_mcp.eval.agent.calls", "kb_mcp.surface", "gen_ai.tool.name", "kb_mcp.status"
    )
    assert {key: point.value for key, point in called.items()} == {
        ("B", "ask", "answered"): 1,
        ("A", "search", "refused"): 1,
    }
    by_tool = {("B", "ask"): lines["B"], ("A", "search"): lines["A"]}
    tokens = points("kb_mcp.eval.agent.tokens", "kb_mcp.surface", "gen_ai.tool.name")
    assert {key: point.sum for key, point in tokens.items()} == {
        key: line["tokens"] for key, line in by_tool.items()
    }
    seconds = points("kb_mcp.eval.agent.call.duration", "kb_mcp.surface", "gen_ai.tool.name")
    assert {key: point.sum for key, point in seconds.items()} == pytest.approx(
        {key: line["seconds"] for key, line in by_tool.items()}
    )
    judged = points("kb_mcp.eval.agent.runs", "kb_mcp.surface", "kb_mcp.outcome")
    assert {key: point.value for key, point in judged.items()} == {
        ("A", "failure"): 1,
        ("B", "success"): 1,
    }


def test_a_call_s_and_an_answer_s_json_are_not_logged_where_given(world: World) -> None:
    """Their runs' starts name the step and the run, and ``[not logged]`` for the JSON.

    The JSON is masked in its place, the last argument, even where an argument before it
    is equal to it: a second answer, the directory's path, refused as one is kept.
    """
    out = world.root / "runs"
    assert prepared(world, out, "--sample", "1") == 0
    run = first(out, "B")
    assert main(bridged(out, run, "ask", {"question": SENTINEL})) == 0
    given = json.dumps(VALID | {"quotes": [{"ref": "196845", "text": SENTINEL}]})
    assert main(["eval-agents", "answer", str(out), run, given]) == 0
    assert main(["eval-agents", "answer", str(out), run, str(out)]) == REFUSED
    files = sorted(world.logs.glob("eval-agents-*.jsonl"))
    starts = [
        json.loads(line)["arguments"]
        for path in files
        for line in path.read_text("utf-8").splitlines()
        if '"run.start"' in line
    ]
    assert [each for each in starts if each[1] != "prepare"] == [
        ["eval-agents", "call", str(out), run, "ask", "[not logged]"],
        ["eval-agents", "answer", str(out), run, "[not logged]"],
        ["eval-agents", "answer", str(out), run, "[not logged]"],
    ]
    assert not any(SENTINEL in path.read_text("utf-8") for path in files)

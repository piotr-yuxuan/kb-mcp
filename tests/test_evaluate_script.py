"""The one-click evaluation script on a Mac of fake programs (plan 085, D10 and D11).

The seam is PATH: each run of ``scripts/evaluate.py`` finds there a folder of fake programs
alone, which ``tests/fake_programs.py`` plays as the test's plan says, each call noted.
The addresses that ``kb-mcp check`` gives are this test's servers, or a port where nothing
listens; the home and the data directory are the test's. The results files that the fake
``kb-mcp`` writes take the format that ``eval`` and ``eval-rerank`` write, which a test
compares with real ones, so that a change of the format breaks these tests, not a run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from tests.endpoint import nothing_listening, serving
from tests.test_evaluate import GOLDEN, READERS, data, read_by

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.monkeypatch import MonkeyPatch

__all__ = ["data"]  # the fixture of test_evaluate, used here

ROOT = Path(__file__).parents[1]
FAKES = Path(__file__).with_name("fake_programs.py")
PROGRAMS = ("kb-mcp", "ollama", "open", "caffeinate", "llama-server", "uname", "less", "curl")
STEPS = ("search-mode", "chunking", "reranking", "embedding-model")
MODELS = ("qwen3-embedding:0.6b", "embeddinggemma:300m")
RERANKER = Path(".local/share/llama.cpp/qwen3-reranker-0.6b-q8_0.gguf")  # in the home
GOLDEN_SHA256 = "a" * 64
# A golden file whose question no file of the archive may hold.
QUESTIONS = "- id: q1\n  question: where is the zebra-17 canary kept\n  expected: ['4002']\n"
TEST = {"kind": "paired randomisation, two-sided", "samples": 10000, "seed": 11}
# Each mode's MRR@10 over all the questions, its search's and ask's answer tokens and its
# 95th percentile in seconds: hybrid ranks best, lexical answers shortest and fastest.
MODES = {
    "lexical": (0.5, 700, 2000, 0.010),
    "semantic": (0.72, 900, 2300, 0.050),
    "hybrid": (0.86, 800, 2500, 0.040),
}
# The other groups' MRR@10: excellent, poor and failing by the rules of thumb.
GROUPS = {"identifier": 0.95, "paraphrase": 0.35, "keyword": 0.25}
# Four questions: the first expected document comes at rank 1, 3, 7, or not in the first
# ten. Each hit reads so many tokens, and its snippet and its section hold the evidence or
# not. A reader of the hits answers the first from search's first answer, its snippet
# holding the evidence: 500 tokens. It answers the second once it has read two sections,
# 1,000 + 1,500 + 1,000, and reads no further; the third, 1,000 + 6,000; the last never:
# 25% within 2k tokens, 50% within 4k, 75% within 8k, median 5,250.
RANKS = {"q1": [1], "q2": [None, 3], "q3": [7], "q4": [None]}
SEARCHED = {"q1": 500, "q2": 1000, "q3": 1000, "q4": 1000}
HITS = {
    "q1": [(1800, True, True)],
    "q2": [(1500, False, False), (1000, False, True), (2000, False, False)],
    "q3": [(6000, False, True)],
    "q4": [(100, False, False)],
}
# The script's status when it refuses to begin; Ollama's wait in the test of deadlines,
# in seconds, and how much longer the run may take, its start and end.
REFUSED = 2
WAITED, SLACK = 2, 10
SKIPPED = {"id": "q9", "ref": "confluence:404", "why": "no document has this ref"}
# Each depth's MRR@10 and 95th percentile in seconds; depth 0, the order not reranked.
DEPTHS = {0: (0.6, 0.05), 10: (0.7, 1.0), 20: (0.75, 2.0), 30: (0.74, 3.0), 50: (0.74, 6.0)}


def measures(mrr: float, tokens: float = 0.0) -> dict:
    """Give a ranking's measures as a results file keeps them, each share at ``mrr``."""
    shares = dict.fromkeys(("recall", "reciprocal_rank", "ndcg", "success"), mrr)
    return shares | {"section": None, "tokens": tokens}


def verdict(rule: str, fixed: dict, control: str, kept: str | None, reason: str = "") -> dict:
    """Give a default rule's verdict as a results file keeps it."""
    found = {"rule": rule, "fixed": fixed, "control": control, "kept": kept}
    clauses = {key: {} for key in ("means", "adjusted", "losses", "spent", "failed")}
    return found | {"reason": reason or None, "untested": []} | clauses


def eval_results(golden: str = GOLDEN_SHA256, shift: float = 0, day: str = "2026-11-26") -> dict:
    """Give the results of eval on one index, MRR@10 over all the questions moved by shift."""
    hits = {
        question: [
            {"ref": "confluence:1", "section": 1, "read_tokens": read}
            | {"snippet_evidence": snippet, "section_evidence": section}
            for read, snippet, section in each
        ]
        for question, each in HITS.items()
    }
    asked = {"found": 1.0, "evidence": 0.75, "per_kilotoken": 0.3}
    index = {
        "model": MODELS[0],
        "chunking": "windows",
        "fingerprint": "f" * 64,
        "embedded": 40,
        "seconds": 1.0,
        "times": {mode: [tail / 2, tail] for mode, (*_, tail) in MODES.items()},
        "ask_times": {mode: [0.1, 0.2] for mode in MODES},
        "groups": {
            mode: {"all": measures(mrr + shift, search)}
            | {group: measures(value) for group, value in GROUPS.items()}
            for mode, (mrr, search, _, _) in MODES.items()
        },
        "asked": {mode: {"all": asked | {"tokens": ask}} for mode, (_, _, ask, _) in MODES.items()},
        "ranks": dict.fromkeys(MODES, RANKS),
        "costs": {"chunks": 63, "characters": 15777, "tokens": 42, "bytes": 1, "estimated": 3944},
        "documents": {"confluence": {"page": 32}},
        "documents_sha256": "d" * 64,
        "per": {
            mode: {q: measures(0.5, tokens) for q, tokens in SEARCHED.items()} for mode in MODES
        },
        "aligned": 4,
        "asked_per": {mode: dict.fromkeys(SEARCHED, asked | {"tokens": 2000}) for mode in MODES},
        "raw": {
            mode: {q: {"hits": hits[q], "passages": [], "ranking": []} for q in HITS}
            for mode in MODES
        },
    }
    reason = "a challenger of its family was not run"
    verdicts = [
        verdict("search mode", {"model": MODELS[0], "chunking": "windows"}, "hybrid", "hybrid"),
        verdict("chunking", {"model": MODELS[0]}, "windows", None, reason),
    ]
    built = f"{day}T09:00:00+00:00"
    found = {"golden_sha256": golden, "built_at": built, "skipped": [SKIPPED], "test": TEST}
    return found | {"indexes": [index], "verdicts": verdicts}


def rerank_results() -> dict:
    """Give the results of eval-rerank at the default rule's depths; depth 20 is kept."""
    arms = [
        {
            "depth": depth,
            "groups": {"all": measures(mrr), "identifier": measures(0.9), "keyword": measures(0.8)},
            "asked": {"all": {"found": 1.0, "evidence": 0.5, "tokens": 0.0, "per_kilotoken": None}},
            "times": [tail / 2, tail],
            "tokens": 1000 * depth,
            "recall": {"10": 0.9},
            "ranks": RANKS,
            "failed": 0,
        }
        for depth, (mrr, tail) in DEPTHS.items()
    ]
    found = {"golden_sha256": GOLDEN_SHA256, "test": TEST, "built_at": "2026-11-26T10:00:00+00:00"}
    found |= {"mode": "hybrid", "model": MODELS[0], "chunking": "windows", "fingerprint": "f" * 64}
    found |= {"costs": {"chunks": 63}, "documents": {}, "documents_sha256": "d" * 64, "skipped": []}
    found |= {"reranker": "qwen3-reranker-0.6b", "served": ["qwen3-reranker-0.6b"], "sample": None}
    return found | {"arms": arms, "verdicts": [verdict("reranking depth", {}, "none", "20")]}


def keys(results: dict) -> dict[str, set[str]]:
    """Name the keys of a results file that the script reads, at each level of its format."""
    named = {"file": set(results), "verdict": set(results["verdicts"][0])}
    for index in results.get("indexes", [])[:1]:
        question = next(each for each, raw in index["raw"]["hybrid"].items() if raw["hits"])
        raw = index["raw"]["hybrid"][question]
        named |= {"index": set(index), "per": set(index["per"]["hybrid"][question])}
        named |= {"measures": set(index["groups"]["hybrid"]["all"])}
        named |= {"asked": set(index["asked"]["hybrid"]["all"])}
        named |= {"raw": set(raw), "hit": set(raw["hits"][0])}
    for arm in results.get("arms", [])[:1]:
        named |= {"arm": set(arm), "measures": set(arm["groups"]["all"])}
        named |= {"asked": set(arm["asked"]["all"])}
    return named


def listing(_request: httpx.Request) -> httpx.Response:
    """Answer as an OpenAI-compatible API lists its models."""
    return httpx.Response(200, json={"object": "list", "data": []})


@dataclass
class Mac:
    """A Mac for the script: fake programs alone on PATH, a home, and what the fakes do."""

    root: Path
    plan: dict

    @property
    def home(self) -> Path:
        """The home, in which the data directory, Downloads and the reranker's model lie."""
        return self.root / "home"

    @property
    def data(self) -> Path:
        """The data directory that the fake ``kb-mcp check`` gives."""
        return Path(self.plan["settings"]["data_dir"])

    def log(self) -> list[dict]:
        """Give every call of a fake program, and what each noted, in order."""
        calls = self.root / "calls.jsonl"
        lines = calls.read_text("utf-8").splitlines() if calls.exists() else []
        return [json.loads(line) for line in lines]

    def calls(self, program: str) -> list[list[str]]:
        """Give the arguments of each call of a program, in order."""
        return [
            each["arguments"]
            for each in self.log()
            if each["program"] == program and each["event"] == "run"
        ]

    def environment(self, **more: str) -> dict[str, str]:
        """Write the plan; give a run's environment: the fakes alone on PATH, and the home."""
        (self.root / "plan.json").write_text(json.dumps(self.plan), "utf-8")
        return {"PATH": str(self.root / "bin"), "HOME": str(self.home), **more}

    def run(self, *options: str) -> subprocess.CompletedProcess[str]:
        """Run the script, its output to a pipe, each wait given a second, then the options."""
        waits = ["--ollama-wait", "1", "--reranker-wait", "1"]
        return subprocess.run(  # noqa: S603 the test's Python on the script, with a row's options
            [sys.executable, "scripts/evaluate.py", *waits, *options],
            env=self.environment(),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def archived(self, name: str) -> str:
        """Give a file of the run's archive, as text."""
        [archive] = (self.home / "Downloads").glob("kb-mcp evals 2*.zip")
        with zipfile.ZipFile(archive) as packed:
            return packed.read(name).decode()


@pytest.fixture
def mac(tmp_path: Path) -> Iterator[Mac]:
    """Give a Mac where every step runs: Ollama and a reranker answer, each model is there."""
    root = tmp_path / "mac"
    (root / "bin").mkdir(parents=True)
    played = [sys.executable, "-I", FAKES, root / "plan.json", root / "calls.jsonl"]
    for program in PROGRAMS:
        wrapper = root / "bin" / program
        wrapper.write_text(f'#!/bin/sh\nexec {shlex.join(map(str, played))} {program} "$@"\n')
        wrapper.chmod(0o755)
    golden = root / "home" / "kb-mcp" / "eval" / "golden.yaml"
    golden.parent.mkdir(parents=True)
    golden.write_text(QUESTIONS, "utf-8")
    with serving(listing) as embedding_url, serving(listing) as rerank_url:
        settings = {"data_dir": str(golden.parents[1]), "model": MODELS[0], "chunking": "windows"}
        settings |= {"search_mode": "hybrid", "embedding_url": embedding_url}
        settings |= {
            "rerank": {"enabled": False, "url": rerank_url, "model": "qwen3-reranker-0.6b"}
        }
        yield Mac(
            root,
            {
                "uname": "Darwin",
                "version": "kb-mcp 0.1.14",
                "settings": settings,
                "models": list(MODELS),
                "statuses": {},
                "runs": {
                    "eval": [{"results": eval_results()} for _ in range(3)],
                    "eval-rerank": [{"results": rerank_results()}],
                },
                "paged": str(root / "paged"),
                "download": str(root / "download"),
            },
        )


def said(text: str) -> str:
    """Give text on one line, its runs of white space as one space."""
    return " ".join(text.split())


def given(arguments: list[str], flag: str) -> list[str]:
    """Give the value that follows each time a flag is given, in order."""
    return [arguments[at + 1] for at, each in enumerate(arguments) if each == flag]


def started_llama_server(mac: Mac) -> list[list[str]]:
    """Give the arguments of each llama-server started, its --version aside."""
    return [each for each in mac.calls("llama-server") if each != ["--version"]]


def on_terminal(mac: Mac, **more: str) -> bytes:
    """Run the script on a pseudo-terminal, Enter typed ahead; give all it wrote there."""
    leader, follower = os.openpty()
    with subprocess.Popen(
        [sys.executable, "scripts/evaluate.py", "--ollama-wait", "1", "--reranker-wait", "1"],
        stdin=follower,
        stdout=follower,
        stderr=follower,
        env=mac.environment(TERM="xterm-256color", **more),
        cwd=ROOT,
        start_new_session=True,
    ) as process:
        os.close(follower)
        os.write(leader, b"\n")
        written, deadline = b"", time.monotonic() + 120
        while time.monotonic() < deadline:
            if select.select([leader], [], [], 0.2)[0]:
                try:
                    chunk = os.read(leader, 65536)
                except OSError:  # EIO, on Linux, once the script's side is closed
                    break
                if not chunk:
                    break
                written += chunk
            elif process.poll() is not None:
                break
    os.close(leader)
    return written


@pytest.mark.parametrize(
    ("options", "chunkings", "models"),
    [
        ((), ["sections", "windows"], ["custom:1b", MODELS[1]]),
        (
            (
                "--chunking",
                "section-paths",
                "--chunking",
                "windows",
                "--compare",
                "nomic-embed-text",
            ),
            ["section-paths", "windows"],
            ["custom:1b", "nomic-embed-text"],
        ),
        (
            ("--compare", "custom:1b", "--compare", MODELS[0]),
            ["sections", "windows"],
            ["custom:1b", MODELS[0]],
        ),
    ],
)
def test_the_settings_come_from_kb_mcp_check(
    mac: Mac, options: tuple[str, ...], chunkings: list[str], models: list[str]
) -> None:
    """D10: the data directory, the addresses, the model and chunking are check's, not defaults.

    Ollama and the reranker answer at check's addresses alone, so neither is opened nor
    started; the golden file and the logs are under check's data directory. The search
    mode's and the embedding model's steps take the setting's chunking; the chunking step
    compares those that --chunking names, by default the user's pair, sections and windows,
    whatever the setting. The setting's model comes first in the last step, then those that
    --compare names, each once, by default the user's embeddinggemma:300m; each is pulled.
    """
    elsewhere = mac.root / "elsewhere"
    (elsewhere / "eval").mkdir(parents=True)
    (elsewhere / "eval" / "golden.yaml").write_text(QUESTIONS, "utf-8")
    mac.plan["settings"] |= {
        "data_dir": str(elsewhere),
        "model": "custom:1b",
        "chunking": "small-to-big",
    }
    done = mac.run(*options)
    assert done.returncode == 0, done.stdout + done.stderr
    evaluations = [each for each in mac.calls("kb-mcp") if each[0] in {"eval", "eval-rerank"}]
    assert {each[1] for each in evaluations} == {str(elsewhere / "eval" / "golden.yaml")}
    search_mode, chunking, _, embedding = evaluations
    assert given(search_mode, "--chunking") == ["small-to-big"]
    assert given(chunking, "--chunking") == chunkings
    assert given(embedding, "--model") == models
    assert given(embedding, "--chunking") == ["small-to-big"]
    assert [each[1] for each in mac.calls("ollama") if each[0] == "show"] == models
    assert mac.calls("open") == []
    assert started_llama_server(mac) == []
    assert {log.name.split("-", 1)[1] for log in (elsewhere / "eval" / "logs").iterdir()} >= {
        f"{step}.log" for step in STEPS
    }
    assert not (mac.home / "kb-mcp" / "eval" / "logs").exists()


def test_an_older_kb_mcp_is_refused(mac: Mac) -> None:
    """D10: a kb-mcp older than this plan's release, 0.1.14, is refused, saying how to upgrade."""
    mac.plan["version"] = "kb-mcp 0.1.13"
    done = mac.run()
    assert done.returncode == REFUSED
    refusal = said(done.stdout)
    assert "kb-mcp 0.1.13" in refusal
    assert "0.1.14 or later" in refusal
    assert "uv tool install --force" in refusal
    assert mac.calls("kb-mcp") == [["--version"]]


@pytest.mark.parametrize("silent", [False, True])
def test_ollama_is_opened_only_when_the_endpoint_is_silent(mac: Mac, *, silent: bool) -> None:
    """D10: ``open -ga Ollama`` when its address does not answer, and then only."""
    with nothing_listening() as url:
        if silent:
            mac.plan["settings"]["embedding_url"] = url
        done = mac.run()
    assert mac.calls("open") == ([["-ga", "Ollama"]] if silent else [])
    if silent:  # nothing starts it here: the wait ends, and no step runs
        assert done.returncode == REFUSED
        assert f"Ollama did not answer at {url} within 1 s" in said(done.stdout)
        assert not [each for each in mac.calls("kb-mcp") if each[0] == "eval"]
    else:
        assert done.returncode == 0, done.stdout + done.stderr


def test_a_missing_model_is_pulled(mac: Mac) -> None:
    """D10: each model to evaluate that Ollama lacks is pulled, and no other."""
    mac.plan["models"] = [MODELS[0]]
    mac.run()
    assert [each for each in mac.calls("ollama") if each[0] == "pull"] == [["pull", MODELS[1]]]


def test_a_running_reranker_is_left_alone(mac: Mac) -> None:
    """D10: a reranker that answers is checked and used, and no llama-server is started."""
    done = mac.run()
    assert done.returncode == 0, done.stdout + done.stderr
    assert started_llama_server(mac) == []
    commands = [each[:2] for each in mac.calls("kb-mcp")]
    assert ["reranker", "check"] in commands
    assert commands.index(["reranker", "check"]) < [each[0] for each in commands].index(
        "eval-rerank"
    )


def test_llama_server_starts_only_for_reranking_and_stops_after(mac: Mac) -> None:
    """D10: started with the pinned model at the setting's address, stopped before the next step.

    In order: the chunking's eval, llama-server, its check, eval-rerank, llama-server stopped,
    the embedding model's eval.
    """
    (mac.home / RERANKER).parent.mkdir(parents=True)
    (mac.home / RERANKER).write_bytes(b"the model")
    with nothing_listening() as url:
        mac.plan["settings"]["rerank"]["url"] = url
        done = mac.run()
    assert done.returncode == 0, done.stdout + done.stderr
    [started] = started_llama_server(mac)
    assert started[:2] == ["-m", str(mac.home / RERANKER)]
    assert "--reranking" in started
    assert started[started.index("--port") + 1] == url.rsplit(":", 1)[1].split("/")[0]
    happened = [
        f"{each['program']} {each['event']} {' '.join(each['arguments'][:1])}" for each in mac.log()
    ]
    evaluations = [at for at, each in enumerate(happened) if each == "kb-mcp run eval"]
    assert (
        evaluations[1]
        < happened.index("llama-server run -m")
        < happened.index("kb-mcp run reranker")
        < happened.index("kb-mcp run eval-rerank")
        < happened.index("llama-server stopped -m")
        < evaluations[2]
    )


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_llama_server_stops_on_interruption_and_when_the_window_closes(
    mac: Mac, signum: signal.Signals
) -> None:
    """D10: on INT, TERM or HUP during the reranking, llama-server and the command stop."""
    (mac.home / RERANKER).parent.mkdir(parents=True)
    (mac.home / RERANKER).write_bytes(b"the model")
    mac.plan["runs"]["eval-rerank"] = [{"hold": True}]
    with nothing_listening() as url:
        mac.plan["settings"]["rerank"]["url"] = url
        with subprocess.Popen(
            [sys.executable, "scripts/evaluate.py", "--ollama-wait", "1", "--reranker-wait", "9"],
            env=mac.environment(),
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ) as process:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and not [
                each for each in mac.log() if each["event"] == "holding"
            ]:
                time.sleep(0.1)
            process.send_signal(signum)
            assert process.wait(timeout=30) == 128 + signum
    events = {(each["program"], each["event"]) for each in mac.log()}
    assert ("llama-server", "stopped") in events
    assert ("kb-mcp", "ended") in events


def test_a_wait_stops_at_its_deadline(mac: Mac) -> None:
    """D10: Ollama's wait, given 2 seconds here, ends then, saying so."""
    with nothing_listening() as url:
        mac.plan["settings"]["embedding_url"] = url
        start = time.monotonic()
        done = mac.run("--ollama-wait", str(WAITED))
        took = time.monotonic() - start
    assert done.returncode == REFUSED
    assert f"within {WAITED} s" in said(done.stdout)
    assert WAITED <= took < WAITED + SLACK


def test_a_download_resumes_and_is_kept_only_when_its_sha256_matches(
    mac: Mac, monkeypatch: MonkeyPatch
) -> None:
    """D10: curl resumes the .partial file, which becomes the model once its SHA-256 matches.

    The script's ``download`` is given the digest of this test's file, since the pinned
    model's cannot be met here.
    """
    content = bytes(range(256)) * 64
    Path(mac.plan["download"]).write_bytes(content)
    monkeypatch.setenv("PATH", mac.environment()["PATH"])
    target = mac.root / "models" / "reranker.gguf"
    target.parent.mkdir()
    partial = target.with_name("reranker.gguf.partial")
    partial.write_bytes(content[:1000])
    spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
    assert spec
    assert spec.loader
    script = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "evaluate", script)
    spec.loader.exec_module(script)
    digest = hashlib.sha256(content).hexdigest()
    assert script.download(target, "https://example.invalid/reranker", digest, 30) is None
    assert target.read_bytes() == content
    assert not partial.exists()
    assert [each["bytes"] for each in mac.log() if each["event"] == "served"] == [
        len(content) - 1000
    ]


def test_a_download_whose_sha256_differs_is_refused(mac: Mac) -> None:
    """D10: a model whose SHA-256 is not the pinned one is removed; the reranking is skipped."""
    Path(mac.plan["download"]).write_bytes(b"not the reranker")
    with nothing_listening() as url:
        mac.plan["settings"]["rerank"]["url"] = url
        done = mac.run()
    assert "SHA-256" in said(done.stdout)
    assert not (mac.home / RERANKER).exists()
    assert not (mac.home / RERANKER).with_name(f"{RERANKER.name}.partial").exists()
    assert started_llama_server(mac) == []
    assert [each[0] for each in mac.calls("kb-mcp") if each[0].startswith("eval")] == ["eval"] * 3


def test_a_failed_step_is_reported_and_the_next_runs(mac: Mac) -> None:
    """D10: the search mode's eval fails; the others run, and the run says it, exiting 1."""
    mac.plan["runs"]["eval"][0] = {"status": 1}
    done = mac.run()
    assert done.returncode == 1
    commands = [each[0] for each in mac.calls("kb-mcp") if each[0].startswith("eval")]
    assert commands == ["eval", "eval", "eval-rerank", "eval"]
    assert re.search(r"search-mode\W+failed", done.stdout)
    assert re.search(r"embedding-model\W+ok", done.stdout)


def test_eval_agents_is_not_run(mac: Mac) -> None:
    """D10: no eval-agents; --yes is given to eval and eval-rerank alone."""
    mac.run()
    commands = mac.calls("kb-mcp")
    assert not [each for each in commands if "eval-agents" in each]
    for each in commands:
        assert ("--yes" in each) == (each[0] in {"eval", "eval-rerank"})


def test_the_archive_holds_logs_results_and_analyses_not_the_golden_file(mac: Mac) -> None:
    """D10: logs without escape codes, results, analyses and a manifest; no golden question."""
    mac.run()
    [archive] = (mac.home / "Downloads").glob("kb-mcp evals *.zip")
    with zipfile.ZipFile(archive) as packed:
        files = {name: packed.read(name) for name in packed.namelist()}
    for step in STEPS:
        assert [
            name for name in files if name.startswith("logs/") and name.endswith(f"-{step}.log")
        ]
        assert files[f"analyses/{step}.txt"]
    assert len([name for name in files if name.startswith("results/")]) == len(STEPS)
    assert json.loads(files["manifest.json"])["versions"]["kb-mcp"] == "kb-mcp 0.1.14"
    logs = [text for name, text in files.items() if name.startswith("logs/")]
    assert b"questions 2/2, MRR@10 0.860\n" in b"".join(logs)
    assert not [text for text in logs if b"\x1b" in text]
    assert not [name for name, text in files.items() if b"zebra-17" in text or "golden" in name]


@pytest.mark.parametrize("way", ["terminal", "pipe", "NO_COLOR"])
def test_colour_and_pager_only_on_a_terminal(mac: Mac, way: str) -> None:
    """D11: on a terminal, colours and, on a key, the tables in less -RS; else plain text."""
    if way == "pipe":
        written = mac.run().stdout.encode()
    else:
        written = on_terminal(mac, **({"NO_COLOR": "1"} if way == "NO_COLOR" else {}))
    assert b"Step 4 of 4" in written
    if way == "terminal":
        assert b"\x1b[" in written
        assert mac.calls("less") == [["-RS"]]
        assert b"\x1b[1m" in Path(mac.plan["paged"]).read_bytes()
    else:
        assert b"\x1b" not in written
        assert mac.calls("less") == []


def test_progress_names_the_step_and_its_last_duration(mac: Mac) -> None:
    """D11: each step's rule says "step N of 4", then its command, and its time last time.

    The last time is the previous archive's manifest's; the time elapsed ends the step.
    """
    (mac.home / "Downloads").mkdir()
    steps = [{"name": "chunking", "status": "ok", "seconds": 750}]
    with zipfile.ZipFile(mac.home / "Downloads" / "kb-mcp evals 20261120T090000Z.zip", "w") as old:
        old.writestr("manifest.json", json.dumps({"steps": steps}))
    progress = said(mac.run().stdout)
    for number, step in enumerate(STEPS, 1):
        assert f"Step {number} of 4: {step}" in progress
    assert re.search(
        r"Step 2 of 4: chunking\W+kb-mcp eval \S+golden\.yaml [^;]*; 12\.5 min last", progress
    )
    assert re.search(r"chunking: done in \d+\.\d min; 12\.5 min last time", progress)
    assert "search-mode: done in" in progress
    assert "last time" not in progress.partition("Step 3 of 4")[2]


def test_the_analysis_reads_verdicts_groups_ranks_tokens_and_reader(mac: Mac, data: Path) -> None:
    """D11, from the results files: verdicts, MRR@10 by the rules of thumb, ranks, tokens.

    Then what a reader of the hits spends, and the questions skipped. The results files
    that the fakes write have the keys of the ones that eval and eval-rerank write here.
    """
    for command, _ in READERS[:2]:
        assert read_by(data, command, GOLDEN) == 0
    real = {
        path.name.endswith("-rerank.json"): json.loads(path.read_text("utf-8"))
        for path in (data / "eval" / "results").glob("*.json")
    }
    assert keys(eval_results()) == keys(real[False])
    assert keys(rerank_results()) == keys(real[True])
    mac.run()
    analysis = mac.archived("analyses/search-mode.txt")
    assert "Search mode for qwen3-embedding:0.6b, windows: hybrid stays.\n" in analysis
    assert (
        "Chunking for qwen3-embedding:0.6b: no verdict, since a challenger of its family was"
        " not run.\n"
    ) in analysis
    hybrid = analysis.partition("qwen3-embedding:0.6b, windows, hybrid\n")[2]
    assert hybrid.startswith(
        "  MRR@10: all 0.860 excellent, identifier 0.950 excellent, paraphrase 0.350 poor,"
        " keyword 0.250 failing\n"
        "  First expected document at rank 1: 25%, 2 to 3: 25%, 4 to 10: 25%, missed: 25%\n"
        "  Answer tokens: search 800, ask 2,500; E/kT 0.300\n"
        "  A reader of the hits answers 25% within 2k tokens, 50% within 4k, 75% within 8k;"
        " median 5,250 tokens\n"
    )
    assert "  MRR@10: all 0.720 good," in analysis
    assert "  MRR@10: all 0.500 fair," in analysis
    assert "Skipped: q9 (confluence:404, no document has this ref)\n" in analysis
    reranking = mac.archived("analyses/reranking.txt")
    assert reranking.startswith("Reranking depth: 20, in place of none.\n")
    assert "depth 20\n  MRR@10: all 0.750 good, identifier 0.900 excellent" in reranking


def test_the_analysis_compares_with_the_last_run_on_the_same_golden_file(mac: Mac) -> None:
    """D11: each arm against the last results of its command on the golden file, as noise.

    The results of another golden file, newer, and of an older run are passed over; so are
    those of this run's earlier steps.
    """
    folder = mac.data / "eval" / "results"
    folder.mkdir(parents=True)
    for name, results in {
        "20261120T090000Z": eval_results(shift=-0.36, day="2026-11-20"),
        "20261124T090000Z": eval_results(shift=-0.16, day="2026-11-24"),
        "20261125T090000Z": eval_results(golden="b" * 64, shift=-0.76, day="2026-11-25"),
    }.items():
        (folder / f"{name}.json").write_text(json.dumps(results), "utf-8")
    mac.run()
    for step in ("search-mode", "chunking"):
        analysis = mac.archived(f"analyses/{step}.txt")
        assert "Against the last run on the same golden file:\n" in analysis
        assert (
            "  qwen3-embedding:0.6b, windows, hybrid, against 2026-11-24: MRR@10 0.860 (+0.160),"
            " Evidence@ask 0.750 (+0.000)\n"
        ) in analysis
        assert "Differences under 0.07 are noise at 100 questions.\n" in analysis


def test_the_tables_mark_the_best_of_each_column(mac: Mac) -> None:
    """D11: in the pager, the best of each column in bold, and the control's row marked.

    The best MRR@10 of the search modes is hybrid's, the fewest search tokens and the
    fastest search lexical's; of the depths, 20 ranks best. The control is the setting's
    search mode, or the order not reranked.
    """
    on_terminal(mac)
    paged = Path(mac.plan["paged"]).read_text("utf-8")
    search_mode = paged.partition("search-mode: the measures")[2].partition("chunking:")[0]
    reranking = paged.partition("reranking: the measures")[2].partition("embedding-model:")[0]

    def bold(value: str, table: str) -> bool:
        return re.search(rf"\x1b\[1m *{re.escape(value)}\x1b\[0m", table) is not None

    assert [bold(each, search_mode) for each in ("0.860", "700", "10", "0.720", "900")] == [
        *(True, True, True),
        *(False, False),
    ]
    assert [bold(each, reranking) for each in ("0.750", "0.700", "0.600")] == [True, False, False]
    assert "qwen3-embedding:0.6b, windows, hybrid (control)" in search_mode
    assert "qwen3-embedding:0.6b, windows, lexical (control)" not in search_mode
    assert "none (control)" in reranking
    assert "depth 20 (control)" not in reranking


def test_it_refuses_off_macos(mac: Mac) -> None:
    """D10: off macOS, by the uname on PATH, it refuses before kb-mcp, saying what to do."""
    mac.plan["uname"] = "Linux"
    done = mac.run()
    assert done.returncode == REFUSED
    refusal = said(done.stdout)
    assert "macOS alone" in refusal
    assert "uname says Linux" in refusal
    assert "run kb-mcp eval and kb-mcp eval-rerank yourself" in refusal
    assert mac.calls("kb-mcp") == []

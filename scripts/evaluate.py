#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["rich>=15,<16"]
# ///
"""Run kb-mcp's evaluations on this Mac, say what each found, and pack them to share.

``evaluate.command`` runs it from Finder. It readies the machine (macOS, kb-mcp OLDEST or
later and its settings, Ollama and the models, a reranker), runs the steps in the default
rules' order, each logged and analysed, the next one run after a failure, then packs the
logs, results, analyses and a manifest of versions into ``~/Downloads/kb-mcp evals
<stamp>.zip``, never the golden file. A llama-server started here stops once the
reranking ends, however it ends. Colours, the commands' bars and the pager are a
terminal's: a pipe or NO_COLOR gets plain text. Every program it runs is found on PATH.
Exit 0 when each step that ran succeeded, 1 when one did not, 2 when it refused to begin,
and 128 plus the signal's number on INT, TERM or HUP.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from http import HTTPStatus
from http.client import HTTPException
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from rich.console import Console
from rich.table import Column, Table
from rich.text import Text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from contextlib import AbstractContextManager

OLDEST = (0, 1, 14)  # the release of kb-mcp whose results this script reads
# The reranker that llama-server serves when none answers, pinned, and the server's flags,
# as docs/how-to/reranking.md gives them.
MODEL_FILE = ".local/share/llama.cpp/qwen3-reranker-0.6b-q8_0.gguf"  # in the home
MODEL_URL = (
    "https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF/resolve/"
    "a02f48bb4f057028298c21fa033da2b30d7742d5/qwen3-reranker-0.6b-q8_0.gguf"
)
MODEL_SHA256 = "22c9979ce4fbcdc5acdc310c6641c32797eff1aa980b8f7a2db8a8ea23429a48"
LLAMA_FLAGS = ("--reranking", "--alias", "qwen3-reranker-0.6b", "-c", "8192")
# Each step, in the default rules' order, with the rule that gives its verdict.
STEPS = {"search-mode": "search mode", "chunking": "chunking", "reranking": "reranking depth"}
STEPS |= {"embedding-model": "embedding model"}
# The chunkings that the chunking step compares, and the models that the last step compares
# with the setting's, unless options name others: the user's, since another's first run
# embeds the whole mirror anew, for hours.
CHUNKINGS = ("sections", "windows")
COMPARED = ("embeddinggemma:300m",)
UNRULED = "no verdict recorded"  # by a step whose results hold no verdict of its rule
PULL_S = DOWNLOAD_S = 30 * 60  # seconds that a pull, and the download, may take
STOP_S = 10  # seconds that a process stopped may take to end
# MRR@10's rules of thumb, a reader's budgets in tokens, and the noise at 100 questions.
THUMBS = ((0.85, "excellent"), (0.70, "good"), (0.50, "fair"), (0.30, "poor"))
BUDGETS = (2000, 4000, 8000)
NOISE = 0.07
# Where the first expected document lands: rank 1, 2 to 3, 4 to 10, or missed.
LANDING = ((1, 1), (2, 3), (4, 10), (0, 0))
# The tables' columns, each with the better of two values: max for shares, min for counts.
COLUMNS = {"MRR@10": max, "Recall@10": max, "Success@1": max, "Evidence@ask": max}
COLUMNS |= {"E/kT": max, "Search tokens": min, "Ask tokens": min, "Search 95th, ms": min}
# A terminal's escape sequences: CSI, OSC and the others of two bytes.
ESCAPES = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
# The servers asked are on this machine: no proxy, whatever the system's settings say.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class NotReadyError(Exception):
    """The machine is not ready for the steps: the message says why and what to do."""


class Settings(NamedTuple):
    """What the steps read of kb-mcp's resolved settings."""

    data: Path
    model: str
    search_mode: str
    chunking: str
    embedding_url: str
    rerank_url: str


class Run(NamedTuple):
    """What the steps of a run share."""

    console: Console
    fancy: bool  # colours, the commands' own bars and the pager: on a terminal alone
    settings: Settings
    stamp: str
    last: dict[str, float]  # each step's seconds in the previous archive
    earlier: list[Path]  # the results files from before this run, oldest first


class Done(NamedTuple):
    """How a step ended, and what its results said."""

    name: str
    status: str
    seconds: float
    verdict: str
    results: Path | None
    analysis: list[str]
    arms: dict[str, dict]


def interrupted(signum: int, _frame: object) -> None:
    """Leave on INT, TERM or HUP through every ``finally``, which stops what was started."""
    raise SystemExit(128 + signum)


def run_command(
    command: list[str], seconds: float | None, *, shown: bool = False, given: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a command found on PATH, its output captured unless shown, given text if any.

    One not found exits 127, as in a shell, and one past its seconds 124, as timeout's.
    """
    try:
        return subprocess.run(  # noqa: S603 found on PATH by design, arguments built here
            command,
            input=given,
            stdin=subprocess.DEVNULL if given is None else None,
            capture_output=not shown,
            text=True,
            timeout=seconds,
            check=False,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, "", f"{command[0]}: not found on PATH")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "", f"{command[0]}: past {seconds} s")


def started(command: list[str], **streams: object) -> subprocess.Popen[bytes]:
    """Start a command found on PATH in a process group of its own, for ``stop`` to end."""
    return subprocess.Popen(command, start_new_session=True, **streams)  # noqa: S603 as above


def stop(process: subprocess.Popen[bytes]) -> None:
    """End a process started here and its own: TERM, then KILL past STOP_S.

    macOS refuses a signal to a group of zombies, EPERM: there is nothing left to end.
    """
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(STOP_S)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def answers(url: str, seconds: float = 0) -> bool:
    """Say whether an OpenAI-compatible API here lists its models within the seconds given."""
    deadline = time.monotonic() + seconds
    while True:
        listed = f"{url.rstrip('/')}/models"
        with (
            contextlib.suppress(OSError, HTTPException, ValueError),
            DIRECT.open(listed, timeout=2) as answer,
        ):
            if answer.status == HTTPStatus.OK:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(1, max(deadline - time.monotonic(), 0)))


def ready(console: Console) -> tuple[Settings, str]:
    """Check the system, kb-mcp's version and the golden file; give the settings and version.

    Raises NotReadyError, saying what to do, off macOS, for a kb-mcp older than OLDEST,
    when ``kb-mcp check`` gives no settings, or without a golden file.
    """
    system = run_command(["uname"], 10).stdout.strip()
    if system != "Darwin":
        message = (
            f"This script runs on macOS alone, and uname says {system or 'nothing'}: elsewhere,"
            " run kb-mcp eval and kb-mcp eval-rerank yourself, as"
            " docs/how-to/golden-questions.md and docs/how-to/reranking.md say."
        )
        raise NotReadyError(message)
    version = run_command(["kb-mcp", "--version"], 60).stdout.strip()
    numbers = re.search(r"(\d+)\.(\d+)\.(\d+)", version)
    if not numbers or tuple(map(int, numbers.groups())) < OLDEST:
        message = (
            f"{version or 'kb-mcp is not on PATH'}: this script needs kb-mcp"
            f" {'.'.join(map(str, OLDEST))} or later. In kb-mcp's checkout, run git pull,"
            " then uv tool install --force ., then this script again."
        )
        raise NotReadyError(message)
    console.print(version, style="green")
    checked = run_command(["kb-mcp", "check", "--format", "json"], 60)
    try:
        found = json.loads(checked.stdout)["settings"]
        values = [found[name] for name in ("data_dir", "model", "search_mode", "chunking")]
        values += [found["embedding_url"], found["rerank"]["url"]]
    except (ValueError, KeyError, TypeError):
        values = []
    if checked.returncode or not values or not all(isinstance(each, str) for each in values):
        message = (
            f"kb-mcp check gave no settings ({checked.stderr.strip() or checked.returncode}):"
            " fix what it says, then run this script again."
        )
        raise NotReadyError(message)
    settings = Settings(Path(values[0]), *values[1:])
    if not (golden := settings.data / "eval" / "golden.yaml").is_file():
        message = (
            f"No golden file at {golden}: write one as docs/how-to/golden-questions.md says,"
            " then run this script again."
        )
        raise NotReadyError(message)
    return settings, version


def ollama_ready(console: Console, url: str, models: list[str], seconds: float) -> None:
    """Make Ollama answer at its address, opening it if silent; pull each model it lacks.

    Raises NotReadyError when Ollama does not answer within the seconds given, since every
    step embeds. A model not pulled is said, and the steps that need it fail.
    """
    if not answers(url):
        console.print(f"Ollama does not answer at {url}: opening it.", style="yellow")
        run_command(["open", "-ga", "Ollama"], 60)
        if not answers(url, seconds):
            message = f"Ollama did not answer at {url} within {seconds:g} s: start it, then again."
            raise NotReadyError(message)
    console.print(f"Ollama answers at {url}.", style="green")
    for model in models:
        if run_command(["ollama", "show", model], 60).returncode == 0:
            console.print(f"{model}: in Ollama.", style="green")
            continue
        console.print(f"{model}: not in Ollama; pulling it.", style="yellow")
        if pulled := run_command(["ollama", "pull", model], PULL_S, shown=True).returncode:
            console.print(f"{model}: not pulled (exit {pulled}); its steps will fail.", style="red")


def download(target: Path, url: str, sha256: str, seconds: float) -> str | None:
    """Download a file by curl into ``<target>.partial``, resumed; keep it if its SHA-256 matches.

    Give None once the file is there, else why not: curl failed or took longer than the
    seconds given, the part kept for the next run to resume; or the SHA-256 differs, the
    part then removed.
    """
    if target.is_file():
        return None
    partial = target.with_name(f"{target.name}.partial")
    partial.parent.mkdir(parents=True, exist_ok=True)
    command = ["curl", "-L", "--fail", "-C", "-", "-o", str(partial), url]
    if fetched := run_command(command, seconds, shown=True).returncode:
        return f"the download of {target.name} stopped (exit {fetched}); run again to resume it"
    with partial.open("rb") as part:
        digest = hashlib.file_digest(part, "sha256").hexdigest()
    if digest != sha256:
        partial.unlink()
        return f"{target.name}'s SHA-256 is {digest}, not {sha256}: the download is removed"
    partial.rename(target)
    return None


def logged(run: Run, command: list[str], name: str) -> int:
    """Run a command under ``caffeinate -i`` on a pseudo-terminal; give its exit status.

    Its output goes to ``<data>/eval/logs/<stamp>-<name>.log`` line by line, without escape
    codes, each line as its last carriage return left it; and to the screen as it comes on
    a terminal, else as logged.
    """
    size = shutil.get_terminal_size()
    shape = {"COLUMNS": str(size.columns), "LINES": str(size.lines)}
    leader, follower = os.openpty()
    streams = {"stdin": subprocess.DEVNULL, "stdout": follower, "stderr": follower}
    process = started(["caffeinate", "-i", *command], env=os.environ | shape, **streams)
    os.close(follower)
    pending = b""
    with (run.settings.data / "eval" / "logs" / f"{run.stamp}-{name}.log").open("w") as log:
        try:
            while True:
                try:
                    chunk = os.read(leader, 65536)
                except OSError:  # EIO, on Linux, once the command's side is closed
                    break
                if not chunk:
                    break
                if run.fancy:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.flush()
                *lines, pending = (pending + chunk).split(b"\n")
                for line in map(plain, lines):
                    log.write(f"{line}\n")
                    if not run.fancy:
                        sys.stdout.write(f"{line}\n")
        finally:
            stop(process)
            os.close(leader)
        log.write(plain(pending))
    return process.returncode


def plain(line: bytes) -> str:
    """Give a terminal's line as text: no escape codes, as its last carriage return left it."""
    return ESCAPES.sub(b"", line).decode(errors="replace").removesuffix("\r").rpartition("\r")[2]


@contextlib.contextmanager
def reranker(run: Run, seconds: float) -> Iterator[str | None]:
    """Yield None once a reranker answers and passes ``kb-mcp reranker check``, else why not.

    One that answers already is left alone. Else llama-server starts at the setting's
    address with the pinned model, downloaded if missing, and stops on leaving, however the
    reranking ended.
    """
    url, console, process = run.settings.rerank_url, run.console, None
    model, why = Path.home() / MODEL_FILE, None
    try:
        if answers(url):
            console.print(f"A reranker answers at {url}: left alone.", style="green")
        elif not shutil.which("llama-server"):
            why = "llama-server is not on PATH: brew install llama.cpp, then run again"
        elif not (why := download(model, MODEL_URL, MODEL_SHA256, DOWNLOAD_S)):
            address = urllib.parse.urlsplit(url)
            place = ["--host", str(address.hostname), "--port", str(address.port or 80)]
            log = run.settings.data / "eval" / "logs" / f"{run.stamp}-llama-server.log"
            console.print(f"Starting llama-server at {address.netloc}, logged in {log}.")
            with log.open("wb") as written:
                command = ["llama-server", "-m", str(model), *place, *LLAMA_FLAGS]
                process = started(command, stdin=subprocess.DEVNULL, stdout=written, stderr=written)
            if not answers(url, seconds):
                why = f"llama-server did not answer within {seconds:g} s; its log says why"
        if not why and (status := logged(run, ["kb-mcp", "reranker", "check"], "reranker-check")):
            why = f"kb-mcp reranker check exited {status}; its log says why"
        yield why
    finally:
        if process:
            stop(process)
            console.print("Stopped the llama-server started here.", style="green")


def arms(results: dict) -> dict[str, dict]:
    """Give each arm of a results file by its label, with what the analysis and tables read.

    An arm of eval's is an index's mode, named by its model, chunking and mode; one of
    eval-rerank's, a depth, ``none`` for the order not reranked. A reader of an eval arm's
    hits reads its search's first answer, then, unless a snippet holds the evidence, each
    hit's section in rank order until one does: it spends, by question, the tokens read,
    or infinity when no hit holds it.
    """
    found = {}
    for index in results.get("indexes", []):
        for mode, groups in index["groups"].items():
            raw, spent = index.get("raw", {}).get(mode, {}), []
            for question, measures in index.get("per", {}).get(mode, {}).items():
                hits = raw.get(question, {}).get("hits", [])
                ends = [at for at, hit in enumerate(hits) if hit["section_evidence"]]
                reads = sum(hit["read_tokens"] for hit in hits[: ends[0] + 1]) if ends else math.inf
                held = any(hit["snippet_evidence"] for hit in hits)
                spent.append(measures["tokens"] + (0 if held else reads))
            asked, ranks, times = index["asked"][mode], index["ranks"][mode], index["times"][mode]
            label = f"{index['model']}, {index['chunking']}, {mode}"
            found[label] = arm(groups, asked["all"], ranks, times, spent)
    for each in results.get("arms", []):
        label = f"depth {each['depth']}" if each["depth"] else "none"
        found[label] = arm(each["groups"], each["asked"]["all"], each["ranks"], each["times"], [])
    return found


def arm(groups: dict, asked: dict, ranks: dict, times: list, spent: list[float]) -> dict:
    """Give what the analysis and the tables read of an arm; no tokens counted is none."""
    every = groups["all"]
    shares = (every["reciprocal_rank"], every["recall"], every["success"], asked["evidence"])
    tokens = (every.get("tokens") or None, asked.get("tokens") or None)
    measured = (*shares, asked.get("per_kilotoken"), *tokens, times[1] * 1000)
    return {
        "measures": dict(zip(COLUMNS, measured, strict=True)),
        "groups": {group: each["reciprocal_rank"] for group, each in groups.items()},
        "ranks": ranks,
        "spent": spent,
    }


def said(verdict: dict) -> str:
    """Say a default rule's verdict in one sentence: the value kept, or why there is none."""
    kept, control = verdict["kept"], verdict["control"]
    if kept is None:
        outcome = f"no verdict, since {verdict['reason']}"
    elif kept == control:
        outcome = f"{kept} stays"
    else:
        outcome = f"{kept}, in place of {control}"
    held = f" for {', '.join(verdict['fixed'].values())}" if verdict["fixed"] else ""
    return f"{verdict['rule'].capitalize()}{held}: {outcome}."


def analysis(results: dict, found: dict[str, dict], earlier: list[Path]) -> list[str]:
    """Say in a few lines what a step's results found, and what changed since the last run."""
    lines = [said(each) for each in results["verdicts"]]
    for label, each in found.items():
        best = [min(filter(None, ranks), default=0) for ranks in each["ranks"].values()] or [0]
        landed = [sum(low <= rank <= high for rank in best) / len(best) for low, high in LANDING]
        mrr = ", ".join(
            f"{group} {value:.3f} {next((word for at, word in THUMBS if value >= at), 'failing')}"
            for group, value in each["groups"].items()
        )
        lines += [label, f"  MRR@10: {mrr}"]
        lines.append(
            "  First expected document at rank 1: {:.0%}, 2 to 3: {:.0%}, 4 to 10: {:.0%},"
            " missed: {:.0%}".format(*landed)
        )
        measures, spent = each["measures"], each["spent"]
        if measures["Search tokens"]:
            ratio = "n/a" if measures["E/kT"] is None else f"{measures['E/kT']:.3f}"
            lines.append(
                f"  Answer tokens: search {measures['Search tokens']:,.0f},"
                f" ask {measures['Ask tokens'] or 0:,.0f}; E/kT {ratio}"
            )
        if spent:
            shares = [sum(cost <= budget for cost in spent) / len(spent) for budget in BUDGETS]
            middle = statistics.median(spent)
            median = "beyond any budget" if middle == math.inf else f"{middle:,.0f} tokens"
            lines.append(
                "  A reader of the hits answers {:.0%} within 2k tokens, {:.0%} within 4k,"
                " {:.0%} within 8k; median {}".format(*shares, median)
            )
    skipped = [f"{each['id']} ({each['ref']}, {each['why']})" for each in results["skipped"]]
    lines += [f"Skipped: {'; '.join(skipped)}"] if skipped else []
    return lines + compared(results, found, earlier)


def compared(results: dict, found: dict[str, dict], earlier: list[Path]) -> list[str]:
    """Give each arm's changes since the last results of its command on the same golden file."""
    rerank, then = "arms" in results, {}
    for path in reversed(earlier):
        if then.keys() >= found.keys():
            break
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError, AttributeError):
            before = json.loads(path.read_text(encoding="utf-8"))
            if ("arms" in before) == rerank and before["golden_sha256"] == results["golden_sha256"]:
                for label, each in arms(before).items():
                    then.setdefault(label, (before["built_at"][:10], each["measures"]))
    lines = []
    for label, each in found.items():
        date, was = then.get(label, ("", {}))
        changes = ", ".join(
            f"{name} {now:.3f} ({now - was[name]:+.3f})"
            for name in ("MRR@10", "Evidence@ask")
            if (now := each["measures"][name]) is not None and was.get(name) is not None
        )
        lines += [f"  {label}, against {date}: {changes}"] if changes else []
    title = "Against the last run on the same golden file:"
    return [title, *lines, f"Differences under {NOISE} are noise at 100 questions."] * bool(lines)


def step(
    run: Run,
    name: str,
    command: list[str],
    readied: Callable[[], AbstractContextManager[str | None]] = contextlib.nullcontext,
    unruled: str = UNRULED,
) -> Done:
    """Run a step once readied, logged on a pseudo-terminal; analyse the results it wrote.

    Its verdict is its rule's, else ``unruled``, which says why there is none.
    """
    console, last = run.console, run.last.get(name)
    console.rule(f"Step {[*STEPS].index(name) + 1} of {len(STEPS)}: {name}", style="cyan")
    since = f"; {last / 60:.1f} min last time" if last else ""
    console.print(f"{' '.join(command)}{since}", style="dim")
    folder = run.settings.data / "eval" / "results"
    before = {path: path.stat().st_mtime_ns for path in folder.glob("*.json")}
    start = time.monotonic()
    with readied() as why_not:
        if why_not:
            console.print(f"{name}: skipped, as {why_not}.", style="yellow")
            return Done(name, f"skipped: {why_not}", 0, "", None, [], {})
        status = logged(run, command, name)
    seconds = time.monotonic() - start
    after = {path: path.stat().st_mtime_ns for path in folder.glob("*.json")}
    written = sorted(path for path, changed in after.items() if before.get(path) != changed)
    try:
        results = json.loads(written[-1].read_text(encoding="utf-8")) if written else {}
        found = arms(results)
        lines = analysis(results, found, run.earlier) if results else []
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        results, found, lines = {}, {}, [f"Its results could not be read: {error!r}"]
    if status or not results:
        state = f"failed, exit {status}" if status else "failed, no results read"
        console.print(f"{name}: {state}, after {seconds / 60:.1f} min{since}.", style="red")
        return Done(name, state, seconds, "", None, lines, {})
    verdict = "; ".join(said(each) for each in results["verdicts"] if each["rule"] == STEPS[name])
    console.print(f"{name}: done in {seconds / 60:.1f} min{since}.", style="green")
    for line in lines:
        console.print(line)
    return Done(name, "ok", seconds, verdict or unruled, written[-1], lines, found)


def tables(ended: list[Done], settings: Settings, *first: Table, colour: bool) -> str:
    """Write tables, then each step's arms as one: the best of a column bold, the control marked.

    They are wide enough for a pager that scrolls sideways. Values compare as reported:
    shares to three decimals, counts whole.
    """
    written = StringIO()
    console = Console(file=written, width=240, color_system="standard" if colour else None)
    controls = (f"{settings.model}, {settings.chunking}, {settings.search_mode}", "none")
    for each in first:
        console.print(each)
    for done in (each for each in ended if each.arms):
        rows = {
            label: [
                None if value is None else round(value, 3 if better is max else None)
                for value, better in zip(each["measures"].values(), COLUMNS.values(), strict=True)
            ]
            for label, each in done.arms.items()
        }
        best = [
            better((row[at] for row in rows.values() if row[at] is not None), default=None)
            for at, better in enumerate(COLUMNS.values())
        ]
        columns = [Column(name, justify="right") for name in COLUMNS]
        table = Table("Arm", *columns, title=f"{done.name}: the measures", title_justify="left")
        for label, row in rows.items():
            cells = []
            for value, top in zip(row, best, strict=True):
                text = (
                    "n/a" if value is None else format(value, "," if type(value) is int else ".3f")
                )
                cells.append(Text(text, "bold" if value is not None and value == top else ""))
            table.add_row(f"{label} (control)" if label in controls else label, *cells)
        console.print(table)
    return written.getvalue()


def finish(run: Run, ended: list[Done], version: str) -> None:
    """Show the steps, pack the run into its archive, and page the measures' tables on a key."""
    steps = Table("Step", "Status", "Minutes", "Verdict", title="The steps", title_justify="left")
    for done in ended:
        steps.add_row(done.name, done.status, f"{done.seconds / 60:.1f}", done.verdict)
    run.console.print(steps)
    versions = {"kb-mcp": version, "macOS": platform.mac_ver()[0], "Python": sys.version.split()[0]}
    for program in ("ollama", "llama-server"):
        answer = run_command([program, "--version"], 30)
        versions[program] = " ".join(f"{answer.stdout} {answer.stderr}".split())
    manifest = {
        "stamp": run.stamp,
        "versions": versions,
        "settings": run.settings._asdict() | {"data": str(run.settings.data)},
        "steps": [
            {"name": each.name, "status": each.status, "seconds": round(each.seconds, 1)}
            | {"verdict": each.verdict, "results": each.results and each.results.name}
            for each in ended
        ],
    }
    (Path.home() / "Downloads").mkdir(exist_ok=True)
    archive = Path.home() / "Downloads" / f"kb-mcp evals {run.stamp}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as packed:
        packed.writestr("manifest.json", json.dumps(manifest, indent=1))
        for log in sorted((run.settings.data / "eval" / "logs").glob(f"{run.stamp}-*.log")):
            packed.write(log, f"logs/{log.name}")
        for done in ended:
            if done.results:
                packed.write(done.results, f"results/{done.results.name}")
            packed.writestr(f"analyses/{done.name}.txt", "\n".join([*done.analysis, ""]))
        packed.writestr("analyses/summary.txt", tables(ended, run.settings, steps, colour=False))
    run.console.print(f"The archive: {archive}", style="green")
    if not run.fancy:
        run.console.print(tables(ended, run.settings, colour=False))
        return
    with contextlib.suppress(EOFError):
        input("Press Enter to page through the measures' tables; q leaves the pager. ")
        coloured = tables(ended, run.settings, colour=True)
        run_command(["less", "-RS"], None, shown=True, given=coloured)


def main() -> int:
    """Ready the machine, run the steps, say what they found and pack them; give the status."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").partition("\n")[0])
    parser.add_argument("--ollama-wait", type=float, default=60, help="seconds for Ollama to start")
    parser.add_argument("--reranker-wait", type=float, default=120, help="seconds for llama-server")
    parser.add_argument(
        "--chunking",
        action="append",
        metavar="NAME",
        help=f"a chunking that the chunking step compares, once for each; {' and '.join(CHUNKINGS)}"
        " by default, since another's first run embeds the whole mirror anew, for hours",
    )
    parser.add_argument(
        "--compare",
        action="append",
        metavar="MODEL",
        help="a model that the last step compares with the setting's, once for each;"
        f" {', '.join(COMPARED)} by default",
    )
    options = parser.parse_args()
    fancy = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    terminal = {"markup": False, "emoji": False, "highlight": False, "soft_wrap": True}
    console = Console(color_system="auto" if fancy else None, **terminal)
    for each in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(each, interrupted)
    try:
        settings, version = ready(console)
        models = [*dict.fromkeys((settings.model, *(options.compare or COMPARED)))]
        ollama_ready(console, settings.embedding_url, models, options.ollama_wait)
    except NotReadyError as error:
        console.print(str(error), style="red")
        return 2
    try:
        with zipfile.ZipFile(max((Path.home() / "Downloads").glob("kb-mcp evals *.zip"))) as packed:
            steps = json.loads(packed.read("manifest.json"))["steps"]
        last = {each["name"]: float(each["seconds"]) for each in steps if each["status"] == "ok"}
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        last = {}
    stamp, folder = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), settings.data / "eval"
    run = Run(console, fancy, settings, stamp, last, sorted(folder.glob("results/*.json")))
    (folder / "logs").mkdir(parents=True, exist_ok=True)
    with (folder / "logs" / f"{stamp}-readiness.log").open("w") as log:
        log.write(f"$ kb-mcp --version\n{version}\n")
        for command in (["kb-mcp", "doctor", "--detail", "detailed"], ["kb-mcp", "model", "check"]):
            answer = run_command(command, 300)
            log.write(f"$ {' '.join(command)}\n{answer.stdout}{answer.stderr}")
            style = "yellow" if answer.returncode else "green"
            console.print(f"{' '.join(command)}: exit {answer.returncode}", style=style)
    evaluate = ["kb-mcp", "eval", str(folder / "golden.yaml"), "--detail", "detailed", "--yes"]
    chunkings = [flag for each in options.chunking or CHUNKINGS for flag in ("--chunking", each)]
    compared = [flag for each in models for flag in ("--model", each)]
    rerank, wait = ["kb-mcp", "eval-rerank", *evaluate[2:]], options.reranker_wait
    unweighed = UNRULED  # as by a kb-mcp older than the embedding model's rule
    if len(models) == 1:
        unweighed = "no verdict: one model measured; name another with --compare"
    ended = [
        step(run, "search-mode", [*evaluate, "--chunking", settings.chunking]),
        step(run, "chunking", [*evaluate, *chunkings]),
        step(run, "reranking", rerank, lambda: reranker(run, wait)),
        step(
            run,
            "embedding-model",
            [*evaluate, *compared, "--chunking", settings.chunking],
            unruled=unweighed,
        ),
    ]
    finish(run, ended, version)
    return int(any(not each.status.startswith(("ok", "skipped")) for each in ended))


if __name__ == "__main__":
    sys.exit(main())

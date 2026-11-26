"""The programs that the evaluation script's tests put on PATH, alone there.

``tests/test_evaluate_script.py`` writes a wrapper for each, which runs
``python -I fake_programs.py PLAN CALLS PROGRAM ARGUMENTS...``. Each call appends its
program and arguments to CALLS, a line of JSON, then does what PLAN, a JSON file, says:
kb-mcp prints its version and settings and writes the results of its evaluations,
llama-server serves until TERM, curl resumes a download, less keeps what it pages. The
standard library alone, since nothing else is on PATH.
"""

from __future__ import annotations

import json
import signal
import socketserver
import sys
import time
from pathlib import Path
from typing import NamedTuple

HOLD_S = 60  # how long a held command waits for the signal that ends it
EVALUATIONS = ("eval", "eval-rerank")


class Call(NamedTuple):
    """One call of a fake program: its plan, its arguments, and the calls before it."""

    plan: dict
    program: str
    arguments: list[str]
    calls: Path
    earlier: list[dict]

    def note(self, event: str, **more: object) -> None:
        """Append what this call did to the calls, as a line of JSON."""
        line = {"program": self.program, "arguments": self.arguments, "event": event, **more}
        with self.calls.open("a", encoding="utf-8") as calls:
            calls.write(json.dumps(line) + "\n")

    def held(self) -> None:
        """Wait for the signal that ends this call, noting it, then leave."""

        def ended(signum: int, _frame: object) -> None:
            self.note("ended", signal=signum)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, ended)
        self.note("holding")
        time.sleep(HOLD_S)


class Listing(socketserver.StreamRequestHandler):
    """Answer any request as an OpenAI-compatible API lists its models, then close."""

    def handle(self) -> None:
        """Read the request's first line and answer it."""
        self.rfile.readline()
        body = b'{"object": "list", "data": []}'
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        self.wfile.write(head.encode() + body)


class Server(socketserver.TCPServer):
    """A server that may take a port just left."""

    allow_reuse_address = True


def kb_mcp(call: Call) -> int:
    """Print the version or the settings, or evaluate: write the results that the plan gives."""
    words = call.arguments[:2] if call.arguments[0] in {"model", "reranker"} else call.arguments[:1]
    command = " ".join(words)
    if command == "--version":
        sys.stdout.write(f"{call.plan['version']}\n")
    elif command == "check":
        sys.stdout.write(json.dumps({"settings": call.plan["settings"], "layers": {}}) + "\n")
    elif command not in EVALUATIONS:
        sys.stdout.write(f"{command}: checked\n")
        return call.plan["statuses"].get(command, 0)
    if command not in EVALUATIONS:
        return 0
    done = sum(each["arguments"][:1] == [command] for each in call.earlier)
    runs = call.plan["runs"][command]
    run = runs[done] if done < len(runs) else {}
    sys.stdout.write("\x1b[1mquestions\x1b[0m 1/2\r\x1b[2Kquestions 2/2, MRR@10 0.860\n")
    sys.stdout.flush()
    if run.get("hold"):
        call.held()
    if "results" in run:
        folder = Path(call.plan["settings"]["data_dir"]) / "eval" / "results"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{time.strftime('%Y%m%dT%H%M%S')}{done}Z{'-rerank' * (command == 'eval-rerank')}"
        (folder / f"{name}.json").write_text(json.dumps(run["results"]), encoding="utf-8")
    return run.get("status", 0)


def llama_server(call: Call) -> int:
    """Say its version; or serve at the port given, if the plan lets it, until TERM."""
    if "--version" in call.arguments:
        sys.stdout.write("version: 1 (fake)\n")
        return 0

    def stopped(signum: int, _frame: object) -> None:
        call.note("stopped", signal=signum)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stopped)
    if not call.plan.get("llama_serves", True):
        time.sleep(HOLD_S)
        return 0
    port = int(call.arguments[call.arguments.index("--port") + 1])
    with Server(("127.0.0.1", port), Listing) as server:
        call.note("serving")
        server.serve_forever()
    return 0


def curl(call: Call) -> int:
    """Write the plan's download to the file named by -o, from its size if resumed by -C."""
    target = Path(call.arguments[call.arguments.index("-o") + 1])
    content = Path(call.plan["download"]).read_bytes()
    start = target.stat().st_size if "-C" in call.arguments and target.exists() else 0
    with target.open("ab" if start else "wb") as written:
        written.write(content[start:])
    call.note("served", bytes=len(content) - start)
    return 0


def ollama(call: Call) -> int:
    """Hold the plan's models, pull any, and say a version."""
    if call.arguments[0] == "show":
        return 0 if call.arguments[1] in call.plan["models"] else 1
    if call.arguments[0] != "pull":
        sys.stdout.write("ollama version is 0.0.0 (fake)\n")
    return 0


def less(call: Call) -> int:
    """Keep what it is given to page, where the plan says."""
    Path(call.plan["paged"]).write_bytes(sys.stdin.buffer.read())
    return 0


def uname(call: Call) -> int:
    """Name the plan's system."""
    sys.stdout.write(f"{call.plan['uname']}\n")
    return 0


def caffeinate(call: Call) -> int:
    """Run the command after -i in this process, as caffeinate keeps a Mac awake for it."""
    return called(call.plan, call.calls, call.arguments[1], call.arguments[2:])


PROGRAMS = {
    "kb-mcp": kb_mcp,
    "llama-server": llama_server,
    "curl": curl,
    "ollama": ollama,
    "less": less,
    "uname": uname,
    "caffeinate": caffeinate,
    "open": lambda _call: 0,
}


def called(plan: dict, calls: Path, program: str, arguments: list[str]) -> int:
    """Note a call of the program, then act as it, as the plan says."""
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    earlier = [each for each in map(json.loads, lines) if each["program"] == program]
    call = Call(plan, program, arguments, calls, earlier)
    call.note("run")
    return PROGRAMS[program](call)


def main() -> int:
    """Act as the program that the wrapper names."""
    plan, calls, program, *arguments = sys.argv[1:]
    return called(
        json.loads(Path(plan).read_text(encoding="utf-8")), Path(calls), program, arguments
    )


if __name__ == "__main__":
    sys.exit(main())

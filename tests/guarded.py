"""Run the command as its console script does, in a fresh interpreter, kept off the network.

Run as ``python -m tests.guarded`` from the repository, it reads what to run as JSON,
from its argument or else from stdin: ``ports``, the ports of this machine that the run
may connect to, none where it may make no socket at all; ``limit``, how long telemetry
has at the run's end, in seconds, where it may connect; ``report``, a file that the
names of the threads started, the classes of OpenTelemetry's providers and whether its
SDK was imported are written to once the run ends; and ``arguments``, the command's.
Any other use of the network ends the process at once, with status 3, the event said on
stderr. Read from stdin, what to run leaves the run's stdin at its end, as a pipe that
says nothing; given as the argument, it leaves stdin to the run, such as ``serve``'s
protocol.
"""

from __future__ import annotations

import importlib
import json
import os
import signal
import sys
from pathlib import Path

from kb_mcp.cli.main import main

# The status that a run reaching for the network ends with.
REACHED = 3
# What exports telemetry, which a run imports only once it has an endpoint.
TELEMETRY = "kb_mcp.observability.adapters.telemetry"
# What makes a connection, or looks a name up, or opens a port.
NETWORK = frozenset({"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname"})

given = json.loads(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read())
ports, report = {int(port) for port in given["ports"]}, Path(given["report"])
started: list[str] = []


def guard(event: str, arguments: tuple[object, ...]) -> None:
    """Note each thread started; end the process at a use of the network not allowed."""
    if event == "_thread.start_joinable_thread":
        bootstrap = arguments[0]
        started.append(bootstrap.__self__.name)
        return
    if event == "socket.__new__":
        allowed = bool(ports)
    elif event in NETWORK:
        place = arguments[1] if event == "socket.connect" else arguments[:2]
        here = {("127.0.0.1", each) for each in ports}
        allowed = event != "socket.bind" and tuple(place)[:2] in here
    else:
        allowed = True
    if not allowed:
        sys.stderr.write(f"network: {event}\n")
        os._exit(REACHED)


# Where the run may connect, what exports telemetry is imported before the guard is on:
# urllib3, at its import, binds a socket of this machine to learn whether it has IPv6.
if ports:
    importlib.import_module(TELEMETRY).LIMIT_S = float(given["limit"])
# Ctrl-C raises KeyboardInterrupt, as in a terminal, even where the tests run in the
# background, whose children inherit SIGINT ignored.
signal.signal(signal.SIGINT, signal.default_int_handler)
sys.addaudithook(guard)
status = main(given["arguments"])
# Imported once the run is over: earlier, OpenTelemetry would read the variables that a
# run takes out of its environment before importing it.
trace, metrics = (importlib.import_module(f"opentelemetry.{name}") for name in ("trace", "metrics"))
kinds = [type(trace.get_tracer_provider()), type(metrics.get_meter_provider())]
left = {
    "threads": started,
    "providers": [f"{kind.__module__}.{kind.__qualname__}" for kind in kinds],
    "sdk": any(name.startswith("opentelemetry.sdk") for name in sys.modules),
}
report.write_text(json.dumps(left), "utf-8")
sys.exit(status)

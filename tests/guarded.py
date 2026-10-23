"""Run the command as its console script does, in a fresh interpreter, kept off the network.

Run as ``python -m tests.guarded`` from the repository, it reads what to run on stdin,
as JSON: ``port``, the port of this machine that the run may connect to, or 0 where it
may make no socket at all; ``limit``, how long telemetry has at the run's end, in
seconds, where it may connect; ``report``, a file that the names of the threads started,
the classes of OpenTelemetry's providers and whether its SDK was imported are written
to once the run ends; and ``arguments``, the command's. Any other use of the network
ends the process at once, with status 3, the event said on stderr. The run's stdin is
then at its end, as a pipe that says nothing.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

from opentelemetry import metrics, trace

from atlassian_offline_mcp.cli.main import main

# The status that a run reaching for the network ends with.
REACHED = 3
# What exports telemetry, which a run imports only once it has an endpoint.
TELEMETRY = "atlassian_offline_mcp.observability.adapters.telemetry"
# What makes a connection, or looks a name up, or opens a port.
NETWORK = frozenset({"socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname"})

given = json.loads(sys.stdin.read())
port, report = int(given["port"]), Path(given["report"])
started: list[str] = []


def guard(event: str, arguments: tuple[object, ...]) -> None:
    """Note each thread started; end the process at a use of the network not allowed."""
    if event == "_thread.start_joinable_thread":
        bootstrap = arguments[0]
        started.append(bootstrap.__self__.name)
        return
    if event == "socket.__new__":
        allowed = bool(port)
    elif event in NETWORK:
        place = arguments[1] if event == "socket.connect" else arguments[:2]
        allowed = event != "socket.bind" and tuple(place)[:2] == ("127.0.0.1", port)
    else:
        allowed = True
    if not allowed:
        sys.stderr.write(f"network: {event}\n")
        os._exit(REACHED)


# Where the run may connect, what exports telemetry is imported before the guard is on:
# urllib3, at its import, binds a socket of this machine to learn whether it has IPv6.
if port:
    importlib.import_module(TELEMETRY).LIMIT_S = float(given["limit"])
sys.addaudithook(guard)
status = main(given["arguments"])
kinds = [type(trace.get_tracer_provider()), type(metrics.get_meter_provider())]
left = {
    "threads": started,
    "providers": [f"{kind.__module__}.{kind.__qualname__}" for kind in kinds],
    "sdk": any(name.startswith("opentelemetry.sdk") for name in sys.modules),
}
report.write_text(json.dumps(left), "utf-8")
sys.exit(status)

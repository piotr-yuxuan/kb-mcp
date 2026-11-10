"""Telemetry: how a record is exported, then runs of the command, each in a fresh interpreter.

Off by default; on, everything goes to a scripted collector on this machine under the
program's name, whatever the environment says; and a run ends in bounded time whatever
the collector does, saying once that telemetry was not delivered.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import structlog
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider

from kb_mcp.cli.main import main
from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.observability.adapters.logs import SDK
from kb_mcp.observability.adapters.telemetry import Exported
from kb_mcp.observability.app.observed import early
from kb_mcp.sources.atlassian.fetch.adapters.session_file import COOKIES, write_cookies
from tests.collector import LOGS, METRICS, TRACES, Collector, attributes, collecting, plain
from tests.endpoint import nothing_listening
from tests.test_api_token import (
    ADDRESS,
    AUTHORISATION,
    CREDENTIAL,
    EMAIL,
    ENCODED,
    HOST,
    KEY,
    KEY_SENTINEL,
    SENTINEL,
    SIGN_IN_NEEDED,
    fetch_arguments,
    served,
)
from tests.test_fetching import SITE
from tests.test_observed import said
from tests.test_settings import user_log_folder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from _pytest.capture import CaptureFixture
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

    from tests.conftest import InMemory

ROOT = Path(__file__).parents[1]
PROGRAM = "kb-mcp"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
# The limit that telemetry has at a run's end, as plan 016 injects it for the bounded exit,
# and the time that the end then takes at most, from ``run.end`` to the exit, when the
# endpoint refuses and when it never answers.
LIMIT_S = 1.0
REFUSING_S = 2.0
SILENT_S = 3.0
# A limit that only Ctrl-C cuts short, in seconds.
AWAITED_S = 10.0
# An endpoint that a run may not reach, by the guard, nor need to.
ENDPOINT = "http://127.0.0.1:4318"
# Every variable that names a proxy, in both cases, as requests and urllib read them.
PROXIES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
# OpenTelemetry's variables that the API reads on its import, or at the first call for a
# provider, each naming its choice among the entry points that the SDK installs.
PROVIDERS = {
    "OTEL_PYTHON_TRACER_PROVIDER": "sdk_tracer_provider",
    "OTEL_PYTHON_METER_PROVIDER": "sdk_meter_provider",
    "OTEL_PYTHON_LOGGER_PROVIDER": "sdk_logger_provider",
    "OTEL_PYTHON_CONTEXT": "contextvars_context",
}
# The same, each naming what is installed nowhere.
UNKNOWN_PROVIDERS = dict.fromkeys(PROVIDERS, "elsewhere")
# A saved session's cookie, which no sink may show.
COOKIE = "cookie-sentinel-7e3b"
# What no sink may show: the token, the key, the credential's base64 and the cookie.
SECRETS = (SENTINEL, KEY_SENTINEL, ENCODED, COOKIE)


@dataclass(frozen=True)
class Ran:
    """A run of the command in a fresh interpreter: what it said, when it ended, what it left."""

    status: int
    err: str
    ended: datetime
    threads: list[str]
    connections: int
    providers: list[str]
    sdk: bool


def guarded(
    home: Path, port: int, arguments: list[str], environment: Mapping[str, str], limit: float
) -> Ran:
    """Run the command with ``arguments`` from a scratch home, reaching ``port`` alone.

    It runs as ``tests.guarded`` has it, its environment holding ``HOME`` and
    ``environment`` only, and telemetry has ``limit`` seconds at the run's end. A port
    of 0 lets no socket be made at all.
    """
    report = home / "report.json"
    ports = [port] if port else []
    given = {"ports": ports, "limit": limit, "report": str(report), "arguments": arguments}
    child = subprocess.run(
        [sys.executable, "-m", "tests.guarded"],
        input=json.dumps(given),
        capture_output=True,
        text=True,
        env={"HOME": str(home), **environment},
        cwd=ROOT,
        check=False,
    )
    ended = datetime.now(UTC)
    left = json.loads(report.read_text("utf-8")) if report.exists() else {}
    return Ran(
        child.returncode,
        child.stderr,
        ended,
        left.get("threads", []),
        left.get("connections", 0),
        left.get("providers", []),
        left.get("sdk", False),
    )


def check(home: Path, endpoint: str | None) -> list[str]:
    """Give the arguments of ``check`` with settings naming ``endpoint``, if any, as telemetry's."""
    config = home / "config.toml"
    if endpoint is not None:
        config.write_text(f'[telemetry]\nendpoint = "{endpoint}"\n', "utf-8")
    return ["check", "--config", str(config), "--data-dir", str(home / "data")]


def port_of(endpoint: str) -> int:
    """Give the port of an endpoint as the settings take it, ``http://<address>:<port>``."""
    return int(endpoint.rpartition(":")[2])


def logged(home: Path) -> list[dict[str, object]]:
    """Give the lines of the one log file that a run left in the scratch home's log folder."""
    (path,) = user_log_folder(home).iterdir()
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def ending_s(home: Path, ran: Ran) -> float:
    """Give the seconds from a run's ``run.end``, its work done, to its process's exit.

    What telemetry's limits bound, and no more: an interpreter's start and imports come
    before it, 0.2 to 0.8 s alone, but over 3 s at a load of 30, which no limit bounds.
    """
    (end,) = (line for line in logged(home) if line["event"] == "run.end")
    return (ran.ended - datetime.fromisoformat(str(end["timestamp"]))).total_seconds()


def test_an_exported_record_has_the_event_as_body_its_fields_and_the_span_around_it(
    caplog: LogCaptureFixture,
) -> None:
    """From INFO, the SDK's own records aside; the record itself is left to the other sinks.

    An event's level, logger, time and the event itself are the exported record's own
    fields, not attributes; its command is one more. A library's record has its message,
    a mapping too, and the fields given as its ``extra``, their secrets redacted.
    """
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    tracer = TracerProvider(shutdown_on_exit=False).get_tracer(__name__)
    root, sink = logging.getLogger(), Exported(provider, "check")
    with early():
        root.addHandler(sink)
        try:
            with tracer.start_as_current_span("phase") as span:
                structlog.get_logger("some.module").info("thing.done", count=2, nested={"a": 1})
            structlog.get_logger("some.module").debug("thing.detail")
            logging.getLogger("some.library").warning("%s failed", "it")
            logging.getLogger("some.library").warning({"not": "an event"})
            logging.getLogger("some.library").warning(
                "signed in",
                extra={"authorization": "Bearer sentinel", "x": {"api_key": "sentinel"}},
            )
            logging.getLogger(f"{SDK}.sdk.trace").error("export failed")
        finally:
            root.removeHandler(sink)
    event, library, mapping, extra = (
        exported.log_record for exported in exporter.get_finished_logs()
    )
    assert event.body == "thing.done"
    assert dict(event.attributes or {}) == {"count": 2, "nested": {"a": 1}, "command": "check"}
    context = span.get_span_context()
    assert (event.trace_id, event.span_id) == (context.trace_id, context.span_id)
    assert library.body == "it failed"
    assert dict(library.attributes or {}) == {"command": "check"}
    assert library.trace_id == 0
    assert mapping.body == "{'not': 'an event'}"
    assert dict(extra.attributes or {}) == {
        "authorization": "[redacted]",
        "x": {"api_key": "[redacted]"},
        "command": "check",
    }
    assert caplog.records[0].msg["event"] == "thing.done"


def test_no_secret_reaches_the_files_stderr_or_telemetry_at_debug(
    telemetry: InMemory,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Plan 016's criterion 6, on the scripted site at -vv, telemetry on in this process.

    First a download signing in by token, which the site refuses with 401; then one by
    a saved session, whose site fails, the session's cookie a local of the failing
    frame, after an event nesting the credential and the cookie under
    ``headers.Authorization``, and a library's record giving both as its fields. No
    secret is in the files, on stderr, in a span, a metric or an exported record. The
    SDK's providers are this session's, over in-memory exporters; the records are
    exported as ``exporting`` has it, through ``Exported``.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(time, "sleep", lambda _: None)
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    root, sink = logging.getLogger(), Exported(provider, "fetch")

    def site(request: httpx.Request) -> httpx.Response:
        if "authorization" in request.headers:
            return httpx.Response(401)
        cookie = request.headers.get("cookie", "")
        both = [AUTHORISATION, cookie]
        structlog.get_logger().warning("scripted.sent", headers={"Authorization": both})
        logging.getLogger("some.library").warning(
            "sent", extra={"authorization": AUTHORISATION, "cookie": cookie}
        )
        message = "the site broke"
        raise RuntimeError(message)

    sent = served(monkeypatch, site)
    monkeypatch.setenv(KEY, KEY_SENTINEL)
    root.addHandler(sink)
    try:
        with monkeypatch.context() as token:
            token.setenv(EMAIL, ADDRESS)
            token.setenv(CREDENTIAL, SENTINEL)
            assert main(fetch_arguments(tmp_path, "-vv")) == SIGN_IN_NEEDED
        session = tmp_path / "kb-mcp" / "session" / COOKIES
        write_cookies(session, [{"name": "tenant.session.token", "value": COOKIE, "domain": HOST}])
        assert main(fetch_arguments(tmp_path, "-vv")) == ExitStatus.FAILED
    finally:
        root.removeHandler(sink)
    assert any(COOKIE in request.headers.get("cookie", "") for request in sent)
    out, err = capsys.readouterr()
    files = "".join(path.read_text("utf-8") for path in user_log_folder(tmp_path).iterdir())
    spans = "".join(span.to_json() for span in telemetry.spans.get_finished_spans())
    data = telemetry.reader.get_metrics_data()
    exported = "".join(record.to_json() for record in exporter.get_finished_logs())
    assert "scripted.sent" in files
    assert '"exception"' in files
    assert "scripted.sent" in exported
    for shown in (out + err, files, spans, "" if data is None else data.to_json(), exported):
        assert [secret for secret in SECRETS if secret in shown] == []


@pytest.mark.parametrize(
    ("setting", "environment"),
    [
        (False, {}),
        (True, {"OTEL_SDK_DISABLED": "true"}),
        (False, {"OTEL_EXPORTER_OTLP_ENDPOINT": ENDPOINT, "OTEL_SDK_DISABLED": "TRUE"}),
        (False, PROVIDERS),
        (False, UNKNOWN_PROVIDERS),
    ],
)
def test_off_check_installs_no_provider_starts_no_thread_and_opens_no_socket(
    tmp_path: Path, *, setting: bool, environment: dict[str, str]
) -> None:
    """Without an endpoint, or with one that ``OTEL_SDK_DISABLED`` turns off: nothing is sent.

    Any socket at all would end the run, with status 3; no thread starts, the SDK is not
    even imported, and the API's providers are its own, which trace and measure nothing,
    whatever provider OpenTelemetry's variables name, the SDK's or one installed nowhere.
    Stderr says only what the settings ignored.
    """
    endpoint = ENDPOINT if setting else None
    ran = guarded(tmp_path, 0, check(tmp_path, endpoint), environment, LIMIT_S)
    assert ran.status == 0
    assert all(line.startswith("ignored: ") for line in ran.err.splitlines())
    assert ran.threads == []
    assert not ran.sdk
    assert ran.providers
    assert not any(provider.startswith("opentelemetry.sdk.") for provider in ran.providers)


@pytest.mark.parametrize("variable", [False, True])
def test_on_all_arrives_at_this_machine_under_the_program_s_name_whatever_the_environment(
    tmp_path: Path, *, variable: bool
) -> None:
    """No proxy is taken, and OpenTelemetry's variables name neither the service nor where.

    The endpoint is the setting's, or ``OTEL_EXPORTER_OTLP_ENDPOINT``'s. Every proxy and
    every signal's own endpoint name a port where nothing listens, which the run dies
    reaching; the service's name and attributes name another, and gRPC is asked for;
    the API's variables name the SDK's providers, and the sampler none. Traces, metrics
    and the records from INFO arrive, each record with the event as body and its
    command, none of the SDK's own; none shows the secrets that the settings hold.
    """
    collector = Collector()
    with nothing_listening() as dead, collecting(collector) as endpoint:
        elsewhere = dead.removesuffix("/v1")
        environment = {
            **dict.fromkeys(PROXIES, elsewhere),
            **PROVIDERS,
            "OTEL_TRACES_SAMPLER": "always_off",
            "OTEL_SERVICE_NAME": "elsewhere",
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=elsewhere,service.instance.id=elsewhere",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": f"{elsewhere}/v1/traces",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": f"{elsewhere}/v1/metrics",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": f"{elsewhere}/v1/logs",
            **({"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint} if variable else {}),
            EMAIL: ADDRESS,
            CREDENTIAL: SENTINEL,
            KEY: KEY_SENTINEL,
        }
        arguments = check(tmp_path, None if variable else endpoint)
        ran = guarded(tmp_path, port_of(endpoint), arguments, environment, LIMIT_S)
    layer = "OTEL_EXPORTER_OTLP_ENDPOINT" if variable else "config.toml"
    assert (ran.status, ran.err) == (0, f"telemetry: on, to {endpoint} ({layer})\n")
    run = logged(tmp_path)[0]["run"]
    assert {path for path, _ in collector.sent} == {TRACES, METRICS, LOGS}
    for resource in collector.resources():
        assert resource == {
            "service.name": PROGRAM,
            "service.version": VERSION,
            "service.instance.id": run,
        }
    records = collector.records()
    assert not any(scope.partition(".")[0] == SDK for scope, _ in records)
    assert [plain(record.body) for _, record in records] == ["run.start", "run.end"]
    for _, record in records:
        assert attributes(record.attributes)["command"] == "check"
    for _, body in collector.sent:
        assert [secret for secret in SECRETS if secret.encode() in body] == []


@pytest.mark.parametrize("command", ["check", "serve"])
def test_a_command_that_only_reads_says_that_opentelemetry_s_variable_turned_telemetry_on(
    tmp_path: Path, command: str
) -> None:
    """One line on stderr, though the collector takes everything: the variable is shared.

    An agent starts ``serve`` with its own environment, which may hold the variable for
    another program. -q leaves the line out. ``serve``, with stdin at its end, serves
    nothing, and so sends no span.
    """
    collector = Collector()
    with collecting(collector) as endpoint:
        arguments = [command, *check(tmp_path, None)[1:]]
        environment = {"OTEL_EXPORTER_OTLP_ENDPOINT": endpoint}
        ran = guarded(tmp_path, port_of(endpoint), arguments, environment, LIMIT_S)
        quiet = guarded(tmp_path, port_of(endpoint), [*arguments, "-q"], environment, LIMIT_S)
    on = f"telemetry: on, to {endpoint} (OTEL_EXPORTER_OTLP_ENDPOINT)\n"
    assert (ran.status, ran.err) == (0, on)
    assert (quiet.status, quiet.err) == (0, "")
    assert {path for path, _ in collector.sent} >= {METRICS, LOGS}


def test_a_run_is_one_trace_whose_root_holds_its_records_and_says_its_command_and_status(
    tmp_path: Path,
) -> None:
    """Named after the command, with no parent; its duration is measured alike.

    ``run.start`` and ``run.end`` carry the ids of the root span.
    """
    collector = Collector()
    with collecting(collector) as endpoint:
        ran = guarded(tmp_path, port_of(endpoint), check(tmp_path, endpoint), {}, LIMIT_S)
    assert ran.status == 0
    (root,) = collector.spans()
    assert (root.name, root.parent_span_id) == ("check", b"")
    assert attributes(root.attributes) == {
        "kb_mcp.command": "check",
        "kb_mcp.dry_run": False,
        "kb_mcp.exit_status": 0,
    }
    for _, record in collector.records():
        assert (record.trace_id, record.span_id) == (root.trace_id, root.span_id)
    (duration,) = (metric for metric in collector.metrics() if metric.name == "kb_mcp.run.duration")
    assert duration.unit == "s"
    (point,) = duration.histogram.data_points
    assert attributes(point.attributes) == {"kb_mcp.command": "check", "kb_mcp.exit_status": 0}
    assert point.count == 1


@pytest.mark.parametrize(("dry", "options"), [(True, ["--dry-run"]), (False, [])])
def test_a_fetch_s_root_says_whether_it_is_a_dry_run(
    tmp_path: Path, *, dry: bool, options: list[str]
) -> None:
    """The flag's value, not whether the command takes it.

    With --until before --since, the run refuses before any request.
    """
    collector = Collector()
    with collecting(collector) as endpoint:
        arguments = [
            "fetch",
            "--yes",
            *options,
            *check(tmp_path, endpoint)[1:],
            "--site",
            SITE,
            "--space",
            "MFS",
            "--since",
            "2026-10-22",
            "--until",
            "2026-10-01",
        ]
        ran = guarded(tmp_path, port_of(endpoint), arguments, {}, LIMIT_S)
    assert ran.status == ExitStatus.REFUSED
    (root,) = collector.spans()
    assert attributes(root.attributes) == {
        "kb_mcp.command": "fetch",
        "kb_mcp.dry_run": dry,
        "kb_mcp.exit_status": ExitStatus.REFUSED,
    }


def test_serve_is_no_trace_of_its_own(tmp_path: Path) -> None:
    """Each of its requests is one: its records carry no span's ids, and no span is sent.

    Its duration is measured, as every run's. With stdin at its end, it serves nothing.
    """
    collector = Collector()
    with collecting(collector) as endpoint:
        arguments = ["serve", *check(tmp_path, endpoint)[1:]]
        ran = guarded(tmp_path, port_of(endpoint), arguments, {}, LIMIT_S)
    assert ran.status == 0
    assert collector.spans() == []
    records = [record for _, record in collector.records()]
    assert [plain(record.body) for record in records] == ["run.start", "run.end"]
    assert all(record.trace_id == b"" for record in records)
    (duration,) = (metric for metric in collector.metrics() if metric.name == "kb_mcp.run.duration")
    (point,) = duration.histogram.data_points
    assert attributes(point.attributes) == {"kb_mcp.command": "serve", "kb_mcp.exit_status": 0}


def test_an_endpoint_that_refuses_ends_check_in_bounded_time_with_one_warning(
    tmp_path: Path,
) -> None:
    """Nothing listens there: the run goes on without telemetry, and says so once.

    Before, as every run with an endpoint, it says that telemetry is on. It connects
    once, and its end waits for nothing: past the probe, each export would retry until
    the limit, or some 8 s by the SDK's own defaults.
    """
    with nothing_listening() as dead:
        endpoint = dead.removesuffix("/v1")
        ran = guarded(tmp_path, port_of(endpoint), check(tmp_path, endpoint), {}, LIMIT_S)
    assert ran.status == 0
    assert ending_s(tmp_path, ran) < REFUSING_S
    assert ran.connections == 1
    on, undelivered = ran.err.splitlines()
    assert on == f"telemetry: on, to {endpoint} (config.toml)"
    assert said(undelivered) == [("warning", "telemetry.undelivered")]
    assert ran.threads == []
    assert not any(provider.startswith("opentelemetry.sdk.") for provider in ran.providers)


def test_an_endpoint_that_never_answers_ends_check_in_bounded_time_with_one_warning(
    tmp_path: Path,
) -> None:
    """It takes the connection, and the exports, but never answers: the run drops them.

    Neither stderr nor the collector gets a record of the SDK's own: stderr says that
    telemetry is on, then that it went undelivered. Its end takes one limit, in all, then
    its exit: without it, each export would wait for its own 5 s, or 10 s by the SDK's
    own defaults, and with a limit for each signal in turn, three limits.
    """
    collector = Collector(silent=True)
    with collecting(collector) as endpoint:
        ran = guarded(tmp_path, port_of(endpoint), check(tmp_path, endpoint), {}, LIMIT_S)
    assert ran.status == 0
    assert ending_s(tmp_path, ran) < SILENT_S
    on, undelivered = ran.err.splitlines()
    assert on == f"telemetry: on, to {endpoint} (config.toml)"
    assert said(undelivered) == [("warning", "telemetry.undelivered")]
    assert not any(scope.partition(".")[0] == SDK for scope, _ in collector.records())


def test_ctrl_c_while_the_end_awaits_telemetry_ends_the_run_with_its_own_status(
    tmp_path: Path,
) -> None:
    """The run's work is done: it exits at once, saying once why telemetry went undelivered.

    The collector never answers, so the run waits at its end; Ctrl-C comes once every
    signal's export has reached the collector, while the run awaits their answers. No
    traceback follows.
    """
    collector = Collector(silent=True)
    with collecting(collector) as endpoint:
        given = {
            "ports": [port_of(endpoint)],
            "limit": AWAITED_S,
            "report": str(tmp_path / "report.json"),
            "arguments": check(tmp_path, endpoint),
        }
        began = time.monotonic()
        with subprocess.Popen(
            [sys.executable, "-m", "tests.guarded"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            env={"HOME": str(tmp_path)},
            cwd=ROOT,
        ) as child:
            assert child.stdin is not None
            child.stdin.write(json.dumps(given))
            child.stdin.close()
            while {path for path, _ in collector.sent} != {TRACES, METRICS, LOGS}:
                assert time.monotonic() - began < AWAITED_S
                time.sleep(0.05)
            child.send_signal(signal.SIGINT)
            _, err = child.communicate(timeout=AWAITED_S)
    assert time.monotonic() - began < AWAITED_S
    assert child.returncode == 0
    assert said(err) == [("warning", "telemetry.undelivered")]
    assert "reason=interrupted" in err

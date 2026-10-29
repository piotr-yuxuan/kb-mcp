# Telemetry

What a run records of itself: its log file, what it says on stderr, and, once an
endpoint is set, its traces, metrics and logs sent by OpenTelemetry. This page gives the
file, its fields, the levels, the settings and the variables, then what every command
records, but `completion`, which records nothing. Beside it, a page per command, named
after it, such as [download.md](download.md), lists what that command records besides;
a command added adds its page, and no list here.

A change to an event, a span or an instrument changes its page in the same commit: the
tests run each command on the scripted site and endpoint, and compare what it records
with its page and this one, finding the pages in this folder.

## The log file

Each run, once its settings are read, unless it is then refused or declined, writes one
file, `<logs.dir>/<command>-<start>-<pid>.jsonl`, the start in UTC as `%Y%m%dT%H%M%SZ`,
such as `download-20261022T210509Z-4242.jsonl`; a step's command names its file, as
`eval-agents` does for `eval-agents call`. `--help`, `--version`, a completion and
`completion`, which reads no settings, write none.

- **Where.** `logs.dir`, by default the user's log folder as platformdirs places it:
  `~/Library/Logs/kb-mcp` on macOS,
  `$XDG_STATE_HOME/kb-mcp/log` on Linux, `~/.local/state` without the
  variable. The folder passes the data directory's guard: under a synchronised folder
  or in a git working tree, the run exits 2, naming `logs.dir`.
- **Who reads it.** The folder, when the run makes it, is 0700, and each file 0600: it
  holds titles, ids, paths, queries and names of people: a name given to a filter, and
  those that a build of the index warns of, a name that it could not give one person
  and an alias that changed nothing ([index.md](index.md)). Those warnings show on
  stderr too, and reach telemetry's endpoint when one is set, as titles do; the alias
  file itself is no setting, and `run.start` does not log it.
- **What.** One JSON object a line, every event and record from DEBUG, from `run.start`
  to the run's end.
- **How long.** A run first removes the files of this pattern whose run started more
  than 30 days before, whichever of the program's commands is named, so that a folder
  shared with another program keeps that program's files; past 256 MiB, a line
  `log.capped` ends the file.
- **When it cannot be written,** from the start or later, as on a full disk, the run
  says `log.unwritable` once and goes on without.

## Fields

| Field | Holds |
|---|---|
| `timestamp` | When, in UTC, ISO 8601, as `2026-10-22T21:05:09.123456Z` |
| `level` | `debug`, `info`, `warning`, `error` or `critical` |
| `event` | The event, `<area>.<what>`; a library's record, its message |
| `logger` | The module that logged it |
| `run` | The run's id, 16 random hex digits, also its telemetry's `service.instance.id` |
| `command` | The command run |
| `trace_id`, `span_id` | Within a span, its trace's and its own ids, in hex, as Tempo shows them |
| `exception` | A traceback, structured, without any frame's locals |

The other fields are the event's own, in snake case, as the pages list them, none named
as an attribute of the standard library's log record, such as `name` or `filename`,
which an exported record could not hold. Before any sink, the value of a key whose
words, in lower case and split at `_`, `-` and `.`, hold `authorization`, `cookie`,
`token`, `password`, `secret`, or `api` then `key`, at any depth, reads `[redacted]`; no
header is logged, nor a query sent to another host than the site.

## Levels

| Option | Stderr shows, from | The file | Telemetry exports, from |
|---|---|---|---|
| none | WARNING | DEBUG | INFO |
| `-v` | INFO | DEBUG | INFO |
| `-vv` | DEBUG | DEBUG | INFO |
| `-q` | ERROR, and no result as text | DEBUG | INFO |

`--log-level` names the level instead. httpx, httpcore, urllib3 and requests reach every
sink from WARNING alone; the OpenTelemetry SDK's own records reach the file alone. Stderr
is coloured on a terminal, unless `NO_COLOR` is set, and shows text from the site or the
mirror inert, without control or bidirectional characters, cut to its width. Stdout
holds the result alone, or, for `serve`, the protocol.

A line on stderr gives the time, the level, the event and the logger, then the event's
fields as `key=value`, by name, a value with spaces in quotes; a traceback follows the
line of `run.failed`:

```
2026-10-22T21:05:09.123456Z [warning  ] search.fallback                [kb_mcp.mcp.app.tools] mode=hybrid reason=...
```

On a terminal, unless `-q`, the tasks of a run are bars, with what is done of how much,
the time spent, the time left and the item at hand; `serve` has none. Each task logs
`progress` every 10 seconds at most, and at its end, to the file, and to stderr from
`-v` when no bar is drawn.

## Settings and variables

| Setting | Variable | Rule |
|---|---|---|
| `logs.dir` | `KB_MCP_LOGS__DIR` | A folder, `~` the home directory; the data directory's guard; by default the user's log folder |
| `telemetry.endpoint` | `KB_MCP_TELEMETRY__ENDPOINT` | `http://<address>:<port>`, a literal address of this machine, no path, such as `http://127.0.0.1:4318`; else the run exits 2. Unset: telemetry off |

| Variable | Effect |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Telemetry's endpoint, in a layer below the settings file, shared with other programs; one that breaks the rule above is said to be ignored, and telemetry stays off |
| `OTEL_SDK_DISABLED` | `true` turns telemetry off, whatever gives the endpoint |
| `NO_COLOR` | Set, stderr has no colour |

Of OpenTelemetry's variables, a run reads these two alone. It takes every other `OTEL_`
variable out of its environment as it starts, before OpenTelemetry is imported, so that
none changes what is sent or where, nor ends the run: `OTEL_SERVICE_NAME`,
`OTEL_RESOURCE_ATTRIBUTES`, `OTEL_EXPORTER_OTLP_PROTOCOL`, each signal's own endpoint,
the headers, the sampler, the API's providers (`OTEL_PYTHON_TRACER_PROVIDER` and the
others) and its context among them. Nor do the proxy variables change anything:
telemetry goes to the endpoint itself. The file's level and how long files are kept are
not settings.

## Telemetry

Off unless an endpoint is set. Whatever layer sets it, every command says so on stderr
before it acts, `telemetry: on, to <endpoint> (<layer>)`, unless `-q`: in its summary
if it writes, else before the values it ignores. So `serve`, which an agent starts with
its own environment, says when `OTEL_EXPORTER_OTLP_ENDPOINT`, set there for another
program, turns it on. `run.start` names the endpoint and its layer too, at INFO.
Traces, metrics and the records from INFO go to the endpoint by OTLP over HTTP, in
protobuf, to `/v1/traces`, `/v1/metrics` and `/v1/logs`, under the resource
`service.name` `kb-mcp`, `service.version` the program's version and
`service.instance.id` the run's id. Spans go in batches, metrics every 15 seconds and at
the end. An exported record has the event as its body, the event's fields as its
attributes with `command`, and the ids of the span it was logged in. No trace context is
sent to the site or to the embedding endpoint.

A run first connects to the endpoint once, waiting 0.5 s at most; unreached, it goes on
without telemetry, saying `telemetry.undelivered`. At its end, what is not sent within
5 seconds, or before Ctrl-C, is dropped, with one `telemetry.undelivered`; the run's
status stays its own.

A run is one trace, whose root span is named after the command, but `serve`, each of
whose requests is a trace, and `completion`, which records nothing. Grafana's
dashboards, an overview and one each for `download`, `mirror`, `index`, `serve`, `eval`,
`eval-agents` and `sync`, are in `deploy/lgtm/dashboards/`.

## Events

What any command may log.

| Event | Level | Fields | When |
|---|---|---|---|
| `run.start` | info | `version`, `arguments`, `settings`, `log_file`, `telemetry`, `telemetry_layer` | A run starts: the program's version, the arguments given, those that its command keeps out of logs reading `[not logged]`, the settings as JSON, secrets masked, the log file, the endpoint, if any, and the layer that gave its value, `default` if none did |
| `run.end` | info | `status`, `seconds` | A run ends: its exit status, how long it took |
| `run.interrupted` | warning | `seconds` | Ctrl-C stopped the run, which exits 130 |
| `run.failed` | error | `seconds` | An exception stopped the run, which exits 1; the traceback follows |
| `run.refused` | error | `reason` | The command refuses its arguments or the settings, before the run: exit 2. On stderr alone |
| `settings.refused` | error | `reason` | The settings break a rule, before the run: exit 2. On stderr alone |
| `progress` | info | `task`, `done`, `total`, `remaining` | A task's heartbeat, every 10 s at most, and at its end; `remaining` in whole seconds |
| `log.unwritable` | warning | `folder`, `reason` | The log folder cannot be written: no file, or nothing more in it |
| `log.capped` | warning | | The file reached its cap: nothing more is written to it |
| `telemetry.undelivered` | warning | `endpoint`, `reason` | The endpoint cannot be reached, or did not take everything at the end |
| `telemetry.shutdown_failed` | debug | `provider` | A provider of the SDK failed to shut down at the end, what it raised following |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `<command>` | internal | `kb_mcp.command`, `kb_mcp.dry_run`, `kb_mcp.exit_status` | The root of a run's trace, named after its command, holding `run.start` and `run.end`; `serve` and `completion` have none |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `kb_mcp.run.duration` | histogram | `s` | `kb_mcp.command`, `kb_mcp.exit_status` | How long a run lasted, `serve`'s included, `completion`'s not |

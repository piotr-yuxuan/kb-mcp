# Observability

Why a run tells of itself as it does: why its logs may hold titles, why its telemetry is
off by default and goes to this machine alone, how a download's traces stay small
enough to be kept, how a run's end stays bounded when nothing receives its telemetry,
and how secrets are kept out of every sink.
[The reference](../reference/telemetry/README.md) lists what each command records;
[the how-to](../how-to/observe-with-grafana.md) shows it in Grafana. Plan 016 made it
so.

## One record, three sinks

Code logs with structlog, traces and measures with the OpenTelemetry API, and reports
progress through `observability.adapters.progress`, wherever it is: all three do nothing
until the command line installs them for a run, so a use case takes no parameter for
them, and a test that calls it directly runs it as it is. Each event, and each record
of a library, passes the same processors, the redaction last, then goes to three sinks:
the run's file, as JSON lines from DEBUG; stderr, at the level asked, its text inert;
and, once an endpoint is set, OpenTelemetry, from INFO. Stdout holds the result alone,
or `serve`'s protocol: logs and progress go to stderr, as Unix has it, so that a pipe of
results stays clean.

## Why the logs may hold titles

The logs are for the user, on the machine where the mirror is, to find what went wrong
in detail; they are not meant to leave it. So the file keeps DEBUG, and an event names
what it is about: a document's id and title, a path, a query. A failure in a download of
thousands of documents is then found by its document, not guessed from a count.

The file stays where the data stays, under the same rules: in the user's log folder, or
`logs.dir`, which passes the data directory's guard, never under a synchronised folder
nor in a git working tree; the folder 0700 when the run makes it, the file 0600; kept
30 days, and cut at 256 MiB a run. What is safe to carry off the machine is
`doctor --shareable`, which gives counts alone, never a log.

Metrics, unlike logs, carry bounded attributes alone: a command, an outcome, a mode, a
status. Ids, titles and queries go on spans and in logs, so that the number of series
does not grow with the documents, and a dashboard of metrics holds no content.

## Off by default, on this machine alone

Telemetry needs a collector, and its traces and records hold what the logs hold. So it
is off until an endpoint is set, and the endpoint is plain http to a literal address of
this machine: the rule of plan 018 for the embedding endpoint, by analogy, without the
flag that lets a run send text elsewhere. A name such as `localhost` is refused, since
it could resolve elsewhere. Neither TLS, a proxy nor authentication has any use on the
loopback address, so none is offered: the exporters ignore the proxy variables, which
would carry the data off the machine, and the resource ignores `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES`, so that dashboards find the runs under one name.
`OTEL_EXPORTER_OTLP_ENDPOINT`, which other programs share, is read below the settings
file, and ignored, with a word, when it breaks the rule; as it can turn telemetry on
unseen, every command says, before it acts, that telemetry is on, where to and by
which layer, `serve` too, which an agent starts with its own environment, and every run
names both in `run.start`. Every other `OTEL_` variable
but `OTEL_SDK_DISABLED` is taken out of the run's environment before OpenTelemetry is
imported: the API reads some on its own, and a provider named there would install the
SDK with telemetry off, or end the run if unknown. The SDK is imported only once
an endpoint is set: a run without telemetry opens no socket and starts no thread for
it. No trace context goes to the site or to the embedding endpoint, which have no use
for this machine's traces.

The container follows the same rule: its two ports on the loopback address alone,
Grafana's anonymous Admin kept from other host names against DNS rebinding, nothing that
calls home, and no volume, so that `down` discards what it received.

## A trace per document

Tempo drops a trace past 5 MB ([ingestion][tempo-limits]). A first download of thousands
of documents, each with its requests, would pass it, and the whole run's trace would be
lost, or kept cut short. So each document fetched is a trace of its own,
`download.document`, linked to the span of its space or project, while the run's trace
holds its phases and listings: its size does not grow with the documents, and scripted
downloads of 3 and 30 documents give run traces of the same number of spans. The files
that a document already stored lacks are fetched within the run's trace, which only the
failures of earlier runs make longer. `serve` has no trace of its own, as a server may
run for days: each message of its protocol is one.

`index` and `eval` stay one trace each, which grows with what they embed: a span
`embeddings <model>` and its `POST` for each batch of 32 pieces, about 520 bytes of OTLP
a batch, measured, a retry adding a `POST`. Tempo's limit is so passed near 300,000
pieces embedded in one run, some 50,000 documents at the sandbox's 5.5 pieces a
document; a first index of 20,000 documents sends about 2 MB. Past the limit, the
trace is lost or cut short: a trace per batch, linked to the run's, as for documents,
would then be the remedy.

## A bounded end

An exporter that cannot deliver retries until its own deadline, each signal in turn:
before plan 016 was built, a run's end was measured at 10.6 s when the endpoint refused
connections, and at 17 s when it accepted them and never answered. A command of a
second must not take seventeen more because Grafana is down. So:

- At its start, a run connects to the endpoint once, waiting 0.5 s at most; unreached,
  it goes on without telemetry, and says `telemetry.undelivered` once.
- At its end, the providers shut down in parallel threads, joined for 5 seconds in all,
  or until Ctrl-C; what is not sent by then is dropped, and one `telemetry.undelivered`
  says so. The run's work is done by then, so its status stays its own.
- The SDK's own records go to the file alone: on stderr they would break `-q`, and
  exported, an export that fails would export its own failure.

Measured with the 5-second limit: `check` against an endpoint that refuses exits after
0.40 to 0.57 s in all, against one that accepts and never answers after 5.38 to 5.52 s,
without telemetry after 0.32 to 0.52 s, and with a collector that answers after 0.39 to
0.42 s.

## Secrets out of every sink

Every sink receives an event once it is redacted. The value of a key whose words, in
lower case and split at `_`, `-` and `.`, hold `authorization`, `cookie`, `token`,
`password`, `secret`, or `api` then `key`, reads `[redacted]` at any depth: so
`Set-Cookie` and `x-api-key` are masked, and `max_tokens` is not. The rule reads words,
not values, and misses a key in camel case, such as `accessToken`; so the code never
logs a header, and shows a URL's query on the site's own host alone, since a media
redirect carries a signed token in its query. A traceback shows no frame's locals,
which structlog would show by default, and where a token could sit. A library's record
reaches OpenTelemetry with the fields given as its `extra`, which no processor sees: the
exporter redacts them by the same rule.

Text from the site or the mirror, a title or a query, is untrusted: a control character
in it could move the cursor of a terminal or rewrite what it shows, and a
bidirectional one reverse it. So on stderr, and in the progress bars, it is drawn as
plain text, never as markup, without control or bidirectional characters, and cut to
the terminal's width. The file keeps it as it came, escaped by JSON.

[tempo-limits]: https://grafana.com/docs/tempo/latest/operations/manage-trace-ingestion/

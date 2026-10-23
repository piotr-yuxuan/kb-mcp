# doctor

What `doctor` records, besides what every command does ([README](README.md)). A run is
one trace: its root `doctor`, and the requests that check the site's certificate and the
sign-in. The verdicts are the result, on stdout, not events.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `http.get` | debug | `url`, `status`, `error`, `seconds` | Each request, the query shown on the site alone |
| `http.retry` | debug | `path`, `attempt`, `failure`, `wait_s` | A request retried after a throttling, gateway or transport failure |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `GET` | client | `http.request.method`, `server.address`, `server.port`, `url.full`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions, until its answer's headers; an error from status 400 |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `http.client.request.duration` | histogram | `s` | `http.request.method`, `server.address`, `server.port`, `http.response.status_code`, `error.type` | Each request, by the HTTP conventions |

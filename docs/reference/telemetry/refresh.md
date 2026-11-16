# refresh

What `refresh` records, besides what every command does ([README](README.md)): nothing of
its own. A run is one trace, its root `refresh`, which holds its units in their order,
each recording what its stage's command records: [fetch](fetch.md), [prepare](prepare.md),
[index](index.md) and [embed](embed.md), their events, spans and instruments, each stage
per source with its `start`, `source` and `end` events. A resume, `refresh --resume <run
id>`, records the units that it runs alone, in a log file and a trace of its own, each line
and each record of it under the run's id, `run`, as the README says; a run of a stage
command that it resumes records as `refresh` does.

## Events

| Event | Level | Fields | When |
|---|---|---|---|

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|

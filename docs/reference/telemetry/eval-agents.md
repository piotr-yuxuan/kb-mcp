# eval-agents

What `eval-agents` records, besides what every command does ([README](README.md)). Each
step is a run of its own, named `eval-agents` in its log file, its root span and
`aom.command`; its `run.start` names the step among the arguments given, a call's JSON
included, but an answer's, which quotes the mirror: it reads `[not logged]`. The agents
run `call` and `answer`, once a call each, so each call is a trace of its own. The
server that `call` starts, as `prepare` starts each surface's to list its tools, is a
`serve` of its own, which records what [serve.md](serve.md) lists; the client passes the
trace's context in each request, so the server's spans join the call's trace when both
send telemetry. The step's own events hold ids, counts and seconds: the runs' directory
keeps the questions, the calls and the answers.

On a terminal, `grade` shows its task `runs`, each run judged by its id.

## Events

| Event | Level | Fields | When |
|---|---|---|---|
| `eval.agent.prepared` | info | `runs`, `model` | `prepare` wrote its runs: how many, and the agents' model, by its alias |
| `eval.agent.call` | info | `agent_run`, `tool`, `status`, `tokens`, `seconds` | A call through the bridge: the run's id, the tool, `answered`, `refused` by the tool, `timeout` or `failed`, the estimated tokens handed over, and the seconds, the server's start included |
| `eval.agent.answered` | info | `agent_run` | An answer is kept |
| `eval.agent.run` | debug | `agent_run`, `question_id`, `surface`, `model`, `outcome`, `reason`, `calls`, `tokens`, `model_tokens`, `seconds` | `grade` judged a run: its question's id, `A` or `B`, the model that the harness reported, `success`, `failure`, `no result` or `pending` and why, the calls by tool, the tokens handed over and the model's, the calls' seconds |
| `eval.agent.graded` | info | `counted`, `pairs`, `left_out`, `keeps_ask` | `grade` is done: the runs by outcome, the questions in the tests and those left out, whether `ask` stays among the default tools |
| `eval.agent.refused` | error | `reason` | A step refused what it was given, by the field at fault: a golden file, a sample, a directory, a call, an answer, or a file of the runs' directory; exit 2. The agent reads it on stderr |
| `eval.agent.not_prepared` | error | `reason` | A surface's server listed nothing in time: exit 1 |
| `eval.agent.past_estimates` | error | `times`, `handed`, `model_tokens`, `hint` | The runs graded spent past twice the estimates, in tokens handed over or the model's: stop them and set the estimates from these; exit 1 |

## Spans

| Span | Kind | Attributes | What |
|---|---|---|---|
| `eval.agent.call` | internal | `aom.surface`, `gen_ai.tool.name`, `aom.status` | A call through the bridge: the run's surface, the tool, the call's status as `eval.agent.call` says it; the server started, called and stopped within |
| `MCP send <method>` | client | `mcp.method.name`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The MCP SDK's: a request to the server, such as `server/discover` and `tools/list`; `error.type` the code of an error answered |
| `MCP send tools/call <tool>` | client | `mcp.method.name`, `jsonrpc.request.id`, `error.type`, `rpc.response.status_code` | The MCP SDK's: the call of a tool |

## Instruments

| Instrument | Kind | Unit | Attributes | What |
|---|---|---|---|---|
| `aom.eval.agent.calls` | counter | `{call}` | `aom.surface`, `gen_ai.tool.name`, `aom.status` | Each call through the bridge, by surface, tool and status |
| `aom.eval.agent.call.duration` | histogram | `s` | `aom.surface`, `gen_ai.tool.name` | How long each call took, its server's start included |
| `aom.eval.agent.tokens` | histogram | `{token}` | `aom.surface`, `gen_ai.tool.name` | The estimated tokens that each call handed over |
| `aom.eval.agent.runs` | counter | `{run}` | `aom.surface`, `aom.outcome` | The runs that `grade` judged, by surface and outcome; each `grade` counts every run again |

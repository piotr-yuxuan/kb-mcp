# Evaluate `ask` with agents

Whether `ask` helps agents, or confuses them, is measured by putting golden questions to
Claude Code subagents on two surfaces: A, the four tools of plan 006, and B, the five
with `ask`. [The MCP surface](../explanation/mcp-surface.md) says what this measures and
its limits. This guide is the procedure, for the session that orchestrates the
subagents; it spends that session's subscription, so the user says when it runs.

## What it needs

The index the server answers from, with vectors if `search_mode` searches by meaning,
and a golden file whose refs the mirror holds, as for `eval` ([golden
questions](golden-questions.md)). The server that the bridge starts reads the same
settings as the commands below: run them all from one shell.

## Prepare the runs

The pilot first, of six questions, twelve runs:

```bash
atlassian-offline-mcp eval-agents prepare golden.yaml --out pilot --model haiku --sample 6
```

`prepare` says the runs, their bound (12 calls of 60 seconds each, at most) and what
they are estimated to cost, then asks; `--dry-run` says it and writes nothing. It
refuses a directory that is not new or empty, or that is synchronised or inside a git
working tree. It writes `runs.json`, the runs in the order to run them, each question on
both surfaces, each surface first for every other question; and `prompts/<run>.md`,
each run's prompt: the rules, the question, the server's instructions and tools as
`serve --tools` lists them for the run's surface, the bridge's command and the answer's
schema. The same golden file and seed give the same runs.

## Run each one with a subagent

For each run of `runs.json`, in order, in batches of at most ten, start one subagent of
the model that `runs.json` names (`haiku` or `sonnet`), by the Agent tool or a
workflow's agent, allowed no tool but Bash, and told only:

> Read `<the run's prompt file>` and do exactly what it says.

The prompt tells the subagent to answer from the tools alone, through the bridge, at
most twelve calls, and to end with the answer command. The bridge,
`eval-agents call DIR RUN TOOL JSON`, starts the server that the run names, makes one
call, logs it in `calls/<run>.jsonl` and prints the answer alone; it refuses a call of a
tool that the run's surface lacks, arguments that are not one JSON object, and a call
past the twelfth, saying to answer now. `eval-agents answer DIR RUN JSON` keeps the
answer, read strictly; a refused answer names the field at fault and may be sent once
more, and a second refusal is kept as the agent's failure. Neither asks anything.

When the subagent ends, write `harness/<run>.json`, and nothing else:

```json
{"status": "returned", "model": "<the model id the harness reports>", "tokens": 70000}
```

`status` is `returned` when the subagent ended on its own, `failed` when the harness
failed it, and `invalid` when its transcript shows anything but reading its prompt file
and running the bridge and the answer command. `model` and `tokens` are the harness's,
when it reports them; leave them out otherwise. Three failures in a row stop the runs.

## Grade after each batch

```bash
atlassian-offline-mcp eval-agents grade pilot --yes
```

`grade` reads the call logs, the answers and the harness files, refuses one not as
written above (naming the run and the field), and grades each answer: citation recall
and precision, quotes grounded in the documents that their refs name, and evidence
quoted. A run succeeds when its answer says the base holds it, every quote is grounded,
and each expected document's evidence is within a quote. A run returned without an
answer kept is a failure; one `failed`, `invalid`, or whose call timed out or lost its
server gives no result, and its question leaves the tests, counted. It writes
`results.json`, of ids and numbers, the prompts' SHA-256 and the models reported, never
a question's text, and says B against A on success, calls and tokens handed over, each
with its interval, and whether `ask` stays among the default tools. `--summary
detailed` adds each run. It exits 1 when the runs spent past twice their estimates:
stop, and set the estimates from what was spent.

```bash
atlassian-offline-mcp eval-agents --format json grade pilot --yes
```

## After the pilot

Set the estimates of `cli/domain/eval_agents.py` once, from the pilot's calls, tokens
handed over and model tokens, then prepare the runs that decide, each model in its own
directory:

```bash
atlassian-offline-mcp eval-agents prepare golden.yaml --out haiku-runs --model haiku --sample 25
```

```bash
atlassian-offline-mcp eval-agents prepare golden.yaml --out sonnet-runs --model sonnet --sample 5
```

Haiku's 50 runs decide by the rule; Sonnet's 10 show the direction for a stronger agent,
and are reported only.

## The runs' directory

| Path | Written by | Holds |
|---|---|---|
| `runs.json` | `prepare` | the runs, their bound, the server's command, what grades each question |
| `prompts/<run>.md` | `prepare` | the run's prompt, with its question |
| `calls/<run>.jsonl` | `call` | each call: tool, arguments, estimated tokens answered, seconds, status |
| `answers/<run>.json` | `answer` | the answer kept |
| `harness/<run>.json` | the orchestrator | status, model and tokens as the harness reports them |
| `results.json` | `grade` | ids and numbers, never a question's text |

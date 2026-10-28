# Documentation

The pages of atlassian-offline-mcp, sorted as [Diataxis](https://diataxis.fr/) sorts
documentation: by what you need from a page at the moment you open it. A tutorial is a
lesson, followed step by step to learn by doing; a how-to guide leads you to a goal you
already have; reference gives the facts to look up as you work; explanation says why
things are as they are. Each kind has its folder here. A page serves both those who use
the command and those who change its code, unless it is marked for contributors.

## Tutorials

- [Your first mirror](tutorials/first-mirror.md): install the command, mirror one
  Confluence space, build its index, and ask Claude Code a question that it answers from
  the mirror.
- [Your first change](tutorials/first-change.md), for contributors: the checks, then a
  subcommand written test first, its rule kept apart from its effects, two checks that
  refuse a mistake, and the reference generated again.

## How-to guides

- [Mirror the site on a managed machine](how-to/sso-machine.md): the settings, the sign-in
  in your browser and a first download, on the user's machine.
- [Bring every source up to date](how-to/sync.md): `sync`, which downloads and mirrors
  each source that the settings name, then rebuilds the index, in one command.
- [Mirror the work log](how-to/work-log.md): a folder of org files mirrored as Markdown
  beside Confluence and Jira, read in place, indexed and served to agents.
- [Sign in with an API token kept by sops](how-to/api-token-with-sops.md): a token in
  place of the browser's session, encrypted at rest and given to the command in its
  environment alone.
- [Shell completions](how-to/shell-completions.md): subcommands, options and their
  values completed by bash or zsh.
- [Coding agents](how-to/agents.md): the MCP server and the mirror's files, for Claude
  Code and VS Code Copilot.
- [Serve the mirror to a local model](how-to/local-model.md): a model on this machine,
  offline, in Ollama or another OpenAI-compatible server, and a host that starts the
  MCP server for it: LM Studio, llama.cpp's web UI, Codex or Claude Code.
- [Embeddings](how-to/embeddings.md): search by meaning, with Ollama on this machine as
  the example of any OpenAI-compatible API; the model, the endpoint and the chunking; or
  words alone.
- [Rerank search with a local server](how-to/reranking.md): llama.cpp's `llama-server`
  on this machine reorders the first documents that `search` and `ask` find, once
  turned on; install it, check it, turn it on, and measure whether it helps.
- [Golden questions](how-to/golden-questions.md): questions about your own content, to
  measure with `eval` which search mode, model and chunking suit it.
- [Observe runs with Grafana](how-to/observe-with-grafana.md): traces, metrics and logs
  in Grafana's LGTM container on this machine, with Podman or Docker.
- [Evaluate `ask` with agents](how-to/evaluate-with-agents.md), for contributors: golden
  questions put to Claude Code subagents, with `ask` and without it.

## Reference

- [Commands](reference/commands.md): what the command and each subcommand say with
  `--help`, and the exit statuses; generated from the parser.
- [Settings](reference/settings.md): each setting's key, variable, type, default and
  meaning, which layer wins, and the variables read besides; generated from the
  settings' model.
- [Data layout](reference/data-layout.md): what each part of the program writes and
  reads under the data directory and in the log folder.
- [The MCP server's tools and prompts](reference/mcp-tools.md): what `serve` offers
  agents, with each tool's and each prompt's parameters.
- [Telemetry](reference/telemetry/README.md): the log file, its fields and levels, the
  settings and variables, and what every command records. Then a page per command for
  what it records besides: [`check`](reference/telemetry/check.md),
  [`completion`](reference/telemetry/completion.md),
  [`doctor`](reference/telemetry/doctor.md),
  [`download`](reference/telemetry/download.md), [`eval`](reference/telemetry/eval.md),
  [`eval-agents`](reference/telemetry/eval-agents.md),
  [`eval-rerank`](reference/telemetry/eval-rerank.md),
  [`index`](reference/telemetry/index.md), [`login`](reference/telemetry/login.md),
  [`mirror`](reference/telemetry/mirror.md), [`model`](reference/telemetry/model.md),
  [`reranker`](reference/telemetry/reranker.md), [`serve`](reference/telemetry/serve.md)
  and [`sync`](reference/telemetry/sync.md).

## Explanation

- [Internals](explanation/internals.md): how the site becomes answers, stage by stage,
  and how a page edited on the site reaches the index, its vectors and the server.
- [Trade-offs](explanation/trade-offs.md): each decision of the design, why it was
  taken, what it costs, the alternative rejected and the plan that settled it.
- [The code's layout](explanation/code-layout.md), for contributors: the contexts, the
  layers within each, the contracts that keep them, and where a new module goes.
- [A walkthrough of the code](explanation/code-walkthrough.md), for contributors: one
  `sync` of a Confluence space, then one `search` by an agent, followed through the
  functions and classes of `src/` that take each step.
- [Sources](explanation/sources.md): why Confluence, Jira and the work log are put
  together as they are, and why the work log is read in place.
- [Credentials](explanation/credentials.md): the browser session, the API token and the
  embedding endpoint's key: where each is kept and sent, what agents get, what is never
  logged, and what none of it guards against.
- [Observability](explanation/observability.md): why the logs may hold titles, why
  telemetry is off by default and stays on this machine, and how secrets stay out of
  every sink.
- [The MCP surface](explanation/mcp-surface.md): what the server says to agents, which
  practice each choice follows, and whether `ask` helps them.
- [Local models](explanation/local-models.md): which model a laptop can run as an agent
  over the mirror, and why: what it must do, what fits in memory, what makes it fast or
  slow, and what the published measures say.
- [Chunking](explanation/chunking.md): how documents are cut into pieces for search by
  meaning, and how the four chunkings were compared.
- [Evaluating search](explanation/search-evaluation.md): how the embedding model was
  chosen, and how ranking by words, by meaning or by both is measured.
- [Reranking](explanation/reranking.md): how a server on this machine reorders the first
  documents found, why only those, what a search does when it fails, why it is off by
  default, and the bar that says whether to turn it on.

## Elsewhere in the repository

- [The README](../README.md): what the command does and needs, and its first command.
- [The roadmap](work/README.md), for contributors: the programme of plans, each plan's
  record in [`plans/`](work/plans/) while it is built, then in
  [`changelog/`](work/changelog/).
- [Instructions for coding agents](../AGENTS.md), for contributors: the workflow, the
  checks and the sandbox's credentials.
- [The sandbox corpus](../sandbox/README.md), for contributors: the fictional company
  seeded into the sandbox site to evaluate search, and the facts its pages share.
- [The proof test](../spikes/README.md), for contributors: plan 001's probe of reading
  Atlassian Cloud through a browser session.

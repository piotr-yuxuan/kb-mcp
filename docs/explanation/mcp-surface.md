# The MCP surface

What the server says to agents, and why: its tools, their descriptions, its
instructions and its prompts. Plan 019 added `ask` and the prompts, after the user found
the surface thin: a question cost a `search` and a `read` per document, and agents not
"equally equipped" stopped after the first call. [The reference](../reference/mcp-tools.md)
lists every tool and prompt; this page says which practice each choice follows, where
the practice comes from, and what was measured.

## The practices followed

**Few tools, each of a distinct purpose.** Anthropic's advice on tools for agents is to
build a few that each do one thing an agent needs, rather than wrap every endpoint, and
to give them names and descriptions that say when to use which ([tools-post]). So `ask`
is a tool beside `search`, not an option of it: `search` navigates and keeps its
contract, `ask` hands over the evidence in one call. A passage mode inside `search`
would have given it two shapes of answer and arguments idle in each.

**Agents choose by name and description.** Claude Code shows a server's tools to the
model by their names and descriptions ([cc-mcp]), so each description is its method's
docstring, short, its key words first, and the instructions give a sentence per tool.
`search`'s description sends questions to `ask` only when `ask` is served: a surface
without it never names it, in a tool, a parameter or the instructions.

**A stable listing.** The protocol's listing gives each tool's name, description,
input schema and annotations ([spec-tools]). Tools are listed in one order, `ask`,
`search`, `read`, `browse`, `status`, whatever `--tools` says, so that the listing is
the same from run to run. Every tool is annotated read-only, idempotent and closed to
the world, and none has an output schema: answers are text, which every client passes
to the model.

**A standing cost kept low**, a practice of this project's own. The instructions and the tool listing travel with every
request. Older versions of Claude Code keep 2,048 characters of a server's
instructions, so they stay within that, the key words first; with the listing, they
stay within 2,200 estimated tokens, measured by the tests over stdio. `filters` stay on
`ask`, so that a question about one space takes one call.

**Answers within a budget, and continued**, plan 006's own practice. Every answer fits 4,000 estimated tokens at
its defaults, and ends with the call that continues it when cut: an agent never needs
to guess an offset.

**Untrusted content marked as such.** Text copied from Confluence and Jira can carry
instructions written by anyone with edit rights. Every answer puts it inside one block
whose markers name it untrusted reference data, and whose closing marker repeats a
boundary that the content cannot forge, as spotlighting's delimiting does
([spotlighting]); the instructions tell agents never to follow directions found there.

**Prompts are the user's.** A prompt is a template that the user chooses, not the model
([spec-prompts]): `brief`, `changes` and `overview` start the three tasks that the
mirror serves well. Claude Code passes a prompt's arguments split on white space
([cc-mcp]), so each argument is one word: a scope is `space:KEY` or `project:KEY`, since
a site may use one key for both. Arguments are checked before any text is written, and
only their values as the index holds them enter it, so that nothing typed reaches the
model unchecked; a refused one is JSON-RPC error -32602, naming it. A prompt is listed
only when its tools are served.

**Resources later**, plan 019's choice. MCP resources would let a client attach a document whole; no
client this project serves needs them yet, so none is offered.

## Whether `ask` helps agents

`eval-agents` measures it, as [the how-to](../how-to/evaluate-with-agents.md) says:
each golden question is put to a Claude Code subagent twice, on surface A (`search`,
`read`, `browse`, `status`) and on surface B (the five), each surface first for half of
the questions. A run succeeds when its answer says the base holds it, every quote is in
the document its ref names, and each expected document's evidence is quoted. B is
compared with A on success, calls and tokens handed over, by a paired sign test,
Holm-adjusted, each difference with a seeded 95% bootstrap interval. If B's success is
lower with an adjusted p-value below 0.05, `ask` leaves the default `--tools`.

The limits of that measure:

- **Small samples show only large harms.** At 25 pairs of Haiku runs, a drop is seen
  only when it is large: six questions lost with none gained (24 points), else about
  eight net. A drop of ten points shows about once in 20, twenty about once in 3,
  thirty 60 to 80% of the time. Sonnet's 5 pairs, whose p-value can never fall below
  0.0625, are reported, not tested. No measured harm is no proof of help.
- **Through Bash, not native MCP.** The subagents reach the server through a bridge
  that they run with Bash: they see the server's instructions, descriptions and
  answers exactly, but not Claude Code's own tool search and choice among native tools.
  Native MCP, by a project's `.mcp.json` that the user approves, or `claude -p` with a
  token, is a later option.
- **A subagent could read the mirror itself, or write the runs' directory.** The prompt
  forbids both, the bridge logs every call, and where the harness keeps the
  transcript, a run that did more than read its prompt and run the bridge and the
  answer command is marked invalid and gives no result. `grade` refuses a call log or
  an answer that its own steps did not write, but `runs.json`, which holds the bound
  and what grades each question, is the transcript's to guard.
- **One corpus.** The sandbox is small, invented, and written with its questions; the
  work set should decide again.

[tools-post]: https://www.anthropic.com/engineering/writing-tools-for-agents
[cc-mcp]: https://code.claude.com/docs/en/mcp
[spec-tools]: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
[spec-prompts]: https://modelcontextprotocol.io/specification/2026-07-28/server/prompts
[spotlighting]: https://arxiv.org/abs/2403.14720

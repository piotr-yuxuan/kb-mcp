# kb-mcp

Knowledge base MCP: an offline mirror of Confluence and Jira Cloud, and of your work log, kept on your own
machine and served to coding agents (Claude Code, VS Code Copilot) through a local MCP
server. It reads what you can already see on the site, through the REST APIs and your
own signed-in browser session or an API token, and never writes to the site; the work
log, a folder of org files, it reads in place.

Work in progress: [the roadmap](docs/work/README.md) says what each plan to come delivers;
[the changelog](docs/work/changelog/) keeps the record of each plan done.

## What it needs

- macOS or Linux, with git and [uv](https://docs.astral.sh/uv/), which installs the
  command and its Python.
- [pandoc](https://pandoc.org/installing.html), which turns what is mirrored into
  Markdown.
- Google Chrome, in which you sign in to the site once; an API token needs no browser.
- An embedding model served on this machine, for search by meaning:
  [Ollama](https://ollama.com) is the example taken, and any OpenAI-compatible API
  works, as [embeddings](docs/how-to/embeddings.md) says. Search by words alone,
  `search_mode = "lexical"`, needs none.

## The command

From a clone of this repository, uv runs it without installing it:

```bash
uv run kb-mcp --help
```

Settings live in `~/.config/kb-mcp/config.toml`, and each can also come
from a variable `KB_MCP_…` or, for some, a flag, the flag winning;
`kb-mcp check --summary detailed` shows each one, where it came from, and
validates them and the data directory. A command that writes under the data directory
says what it will do and asks first, unless given `--yes`.

## Documentation

- [Your first mirror](docs/tutorials/first-mirror.md), a tutorial: install the command,
  mirror one Confluence space, and ask Claude Code a question that it answers from the
  mirror.
- [Your first change](docs/tutorials/first-change.md), a tutorial for contributors: the
  checks, then a subcommand written test first.
- [Move to kb-mcp](docs/how-to/move-to-kb-mcp.md), for a machine set up under the
  program's former name: what a run finds of it, and the steps to move it.
- [The map](docs/README.md) of every page, sorted by what you need from it: the
  tutorials, how-to guides, reference and explanation.

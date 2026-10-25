# atlassian-offline-mcp

An offline mirror of Confluence and Jira Cloud, kept on your own machine and served
to coding agents (Claude Code, VS Code Copilot) through a local MCP server. It reads
what you can already see, through the REST APIs and your own signed-in browser session
or an API token, and never writes to the site.

Work in progress: see the roadmap in [docs/work/README.md](docs/work/README.md) and the
shared data layout in [docs/reference/data-layout.md](docs/reference/data-layout.md).

```bash
uv run atlassian-offline-mcp --help
```

Settings live in `~/.config/atlassian-offline-mcp/config.toml`, and each can also come
from a variable `ATLASSIAN_OFFLINE_MCP_…` or, for some, a flag, the flag winning;
`atlassian-offline-mcp check --summary detailed` shows each one, where it came from, and
validates them and the data directory. A command that writes under the data directory
says what it will do and asks first, unless given `--yes`.

Guides:

- [Mirror the site on a managed machine](docs/how-to/sso-machine.md): settings, sign-in,
  download.
- [Sign in with an API token kept by sops](docs/how-to/api-token-with-sops.md).
- [Shell completions](docs/how-to/shell-completions.md) in bash and zsh.
- [Coding agents](docs/how-to/agents.md): the MCP server, search by meaning, and the
  mirror's files, for Claude Code and VS Code Copilot.

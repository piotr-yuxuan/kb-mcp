# atlassian-offline-mcp

An offline mirror of Confluence and Jira Cloud, kept on your own machine and served
to coding agents (Claude Code, VS Code Copilot) through a local MCP server. It reads
what you can already see, through the REST APIs and your own signed-in browser session,
and never writes to the site.

Work in progress: see the roadmap in [docs/work/README.md](docs/work/README.md) and the
shared data layout in [docs/reference/data-layout.md](docs/reference/data-layout.md).

```bash
uv run atlassian-offline-mcp --help
```

Settings live in `~/.config/atlassian-offline-mcp/config.toml`; `atlassian-offline-mcp
check` validates them and the data directory.

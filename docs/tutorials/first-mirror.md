# Your first mirror

In this tutorial we mirror one Confluence space on your machine, build its search index,
and ask Claude Code a question that it answers from the mirror, citing the page and the
date it was mirrored. Follow the steps in order: each shows what you should see. Where
your output shows other numbers, dates or paths, that is your site, not a fault.

## What you need

- macOS or Linux, with git, [uv](https://docs.astral.sh/uv/),
  [pandoc](https://pandoc.org/installing.html) and Google Chrome.
- [Ollama](https://ollama.com), installed and running, as the example of the embedding
  APIs that work: any OpenAI-compatible one does, as
  [embeddings](../how-to/embeddings.md) says, but this tutorial takes Ollama.
- [Claude Code](https://code.claude.com/docs/en/overview).
- An account on an Atlassian Cloud site, free or paid, that can read a small space: tens
  of pages, so that the first run is short. Its key is in its address, after
  `/wiki/spaces/`; we write it `<KEY>` below, and your site `<your-site>`.

## 1. Install the command

Clone the repository, then install the command from it:

```bash
git clone https://github.com/piotr-yuxuan/atlassian-offline-mcp.git ~/src/atlassian-offline-mcp
```

```bash
uv tool install ~/src/atlassian-offline-mcp
```

uv lists the packages it installs, and ends with:

```text
Installed 1 executable: atlassian-offline-mcp
```

If uv warns that the folder of its executables is not on your `PATH`, run `uv tool
update-shell` and open a new terminal. Then check that your shell finds the command:

```bash
atlassian-offline-mcp --version
```

You should see:

```text
atlassian-offline-mcp 0.1.0
```

## 2. Pull the embedding model

Search ranks pages by their words and by their meaning. Meaning comes from an embedding
model, which Ollama serves on this machine. Pull the model that the command uses by
default, 639 MB, once:

```bash
ollama pull qwen3-embedding:0.6b
```

It shows its progress, and ends with:

```text
success
```

Check that the command reaches it:

```bash
atlassian-offline-mcp model check
```

You should see the model's dimensions, its endpoint and its digest, which names the
version that you pulled, written `<digest>` here:

```text
qwen3-embedding:0.6b: 1024 dimensions, from http://127.0.0.1:11434/v1; digest <digest>; its prefixes known
```

## 3. Name the site and the space

The settings live in one file. Make its folder:

```bash
mkdir -p ~/.config/atlassian-offline-mcp
```

Then create `~/.config/atlassian-offline-mcp/config.toml` in your editor, with your site
and your space:

```toml
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["<KEY>"]
```

Check the settings:

```bash
atlassian-offline-mcp check
```

You should see the two settings that the file gives:

```text
site: https://<your-site>.atlassian.net
sources.confluence.spaces: <KEY>
```

Every other setting keeps its default. The data, the mirror included, go to
`~/atlassian-offline-mcp`.

## 4. Sign in

The command reads the site as you, with a session that you open once in Chrome:

```bash
atlassian-offline-mcp login
```

Before it acts, it says what it will do, and asks:

```text
login, with these settings:
  site: https://<your-site>.atlassian.net
```

It ends with `Proceed? [y/N]`: answer `y`. Chrome opens on your site, in a window of
its own. Sign in as you usually do; the window closes once the site knows you, and the
command says:

```text
Signed in; the session is saved.
```

## 5. Look before you sync

`sync` downloads the space, mirrors it as Markdown, then builds the search index. A
space that no run has covered yet needs a date to start from: `--since` an early date
takes the whole space. First, a dry run, which reads the site, says what it would fetch,
and writes nothing:

```bash
atlassian-offline-mcp sync --dry-run --since 2000-01-01
```

It starts with each setting that it reads, defaults included (the model, the search
mode, the endpoint), then says which sources it takes or leaves out, and gives the same
command in full, one option per line, to copy. Its first lines:

```text
sync, with these settings:
  site: https://<your-site>.atlassian.net
```

After a progress bar, it ends with what it would fetch:

```text
download: done
  confluence pages: to fetch: 13
  failures: 0
mirror: not run
index: not run
```

## 6. Sync

Now the run itself:

```bash
atlassian-offline-mcp sync --since 2000-01-01
```

It starts as the dry run did:

```text
sync, with these settings:
  site: https://<your-site>.atlassian.net
```

and ends its summary with `Proceed? [y/N]`: answer `y`. A space of tens of pages takes a
minute or so. It ends with a row per step, and that step's counts:

```text
download: done
  confluence pages: fetched: 13
  files: downloaded: 10
  failures: 0
mirror: done
  documents: 13
  files written: 24
  files unchanged: 0
  files removed: 0
  problems: 0
index: done
  documents: 13
  sections: 67
  pieces: 45
  embedded now: 45
```

On macOS, `sync` may not exit once its download is done: a known issue, which plan 013
is to fix ([the roadmap](../work/README.md) lists the plans).

Look at what it wrote:

```bash
ls ~/atlassian-offline-mcp/docs/confluence/<KEY>
```

A Markdown file per page, named by the page's id and its title, and `_tree.md`, the
space's tree of pages. The id is the page's ref, by which agents cite it. Each file
begins with front matter, where `fetched_at` is the page's mirror date: the time `sync`
fetched it.

## 7. Give the mirror to Claude Code

Register the command as an MCP server, for every project:

```bash
claude mcp add --scope user --transport stdio atlassian-offline-mcp -- atlassian-offline-mcp
```

Claude Code starts it when a session starts. Then, so that no prompt interrupts a
search, allow its five tools by name in `~/.claude/settings.json`, merged into what the
file holds, if it exists:

```json
{
  "permissions": {
    "allow": [
      "mcp__atlassian-offline-mcp__ask",
      "mcp__atlassian-offline-mcp__search",
      "mcp__atlassian-offline-mcp__read",
      "mcp__atlassian-offline-mcp__browse",
      "mcp__atlassian-offline-mcp__status"
    ]
  }
}
```

## 8. Ask a question

Start `claude` in any folder, and ask, with your space's key:

> What does the home page of the space `<KEY>` say? Cite it by its ref, with its mirror
> date.

Claude calls the server's tools, such as `ask`, then answers from the page. Its answer
should name the page's ref, the id that begins its file's name, and its mirror date,
today's: the content is as of that date, not live. Keep Ollama running: without it, the
server ranks by words alone, and says so.

## What you have done

You have a mirror of one space on your machine, an index that ranks it by words and by
meaning, and an agent that answers from it and says how old its evidence is. From here:

- [Bring every source up to date](../how-to/sync.md): `sync` again, without `--since`,
  catches up from the start of what earlier runs covered, fetching only the revisions
  not yet stored, so that a run that failed leaves no hole
  ([refresh by hand](../explanation/trade-offs.md#refresh-by-hand)); more spaces, and
  Jira projects.
- [Mirror the site on a managed machine](../how-to/sso-machine.md): single sign-on, the
  data directory off synchronised folders, and ending the session.
- [Sign in with an API token kept by sops](../how-to/api-token-with-sops.md), where
  Chrome cannot sign in.
- [VS Code Copilot](../how-to/agents.md#vs-code-copilot), and the mirror's files for
  agents that read files.
- [Mirror the work log](../how-to/work-log.md) beside Confluence and Jira.
- [Observe runs with Grafana](../how-to/observe-with-grafana.md), and what each command
  records, in [telemetry](../reference/telemetry/README.md).
- [Internals](../explanation/internals.md): what each step of `sync` did, and why.

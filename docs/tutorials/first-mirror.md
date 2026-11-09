# Your first mirror

In this tutorial we mirror one Confluence space on your machine, build its search index,
and ask Claude Code a question that it answers from the mirror, citing the page and the
date it was fetched. Follow the steps in order: each shows what you should see. Where
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
git clone https://github.com/piotr-yuxuan/kb-mcp.git ~/src/kb-mcp
```

```bash
uv tool install ~/src/kb-mcp
```

uv lists the packages it installs, and ends with:

```text
Installed 1 executable: kb-mcp
```

If uv warns that the folder of its executables is not on your `PATH`, run `uv tool
update-shell` and open a new terminal. Then check that your shell finds the command:

```bash
kb-mcp --version
```

You should see:

```text
kb-mcp 0.1.0
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
kb-mcp model check
```

You should see the model's dimensions, its endpoint and its digest, which names the
version that you pulled, written `<digest>` here:

```text
qwen3-embedding:0.6b: 1024 dimensions, from http://127.0.0.1:11434/v1; digest <digest>; its prefixes known
```

## 3. Name the site and the space

The settings live in one file. Make its folder:

```bash
mkdir -p ~/.config/kb-mcp
```

Then create `~/.config/kb-mcp/config.toml` in your editor, with your site
and your space:

```toml
[accounts.atlassian]
site = "https://<your-site>.atlassian.net"

[sources.confluence]
spaces = ["<KEY>"]
```

Check the settings:

```bash
kb-mcp check
```

You should see the two settings that the file gives:

```text
accounts.atlassian.site: https://<your-site>.atlassian.net
sources.confluence.spaces: <KEY>
```

Every other setting keeps its default. The data, the mirror included, go to
`~/kb-mcp`.

## 4. Sign in

The command reads the site as you, with a session that you open once in Chrome:

```bash
kb-mcp login atlassian
```

Before it acts, it says what it will do: each setting that it reads, then the same
command in full, to copy. Its first lines:

```text
login, with these settings:
  accounts.atlassian.site: https://<your-site>.atlassian.net
```

It ends with `Proceed? [y/N]`: answer `y`. Chrome opens on your site, in a window of
its own. Sign in as you usually do; the window closes once the site knows you, and the
command says:

```text
Signed in; the session is saved.
```

## 5. Look before you fetch

Four commands, each one stage, make the mirror and its index: `fetch` brings the space
into a store, `prepare` turns what the store holds into Markdown, `index` builds the search
index of its words, and `embed` gives the index's pieces their vectors. A space that no
run has fetched yet takes its last 7 days without `--since`; `--since all` takes the
whole space. First, a dry run, which reads the site, says what it would fetch, and writes
nothing:

```bash
kb-mcp fetch --dry-run --since all
```

It starts with each setting that it reads, defaults included (the data directory), then
says which sources it takes or leaves out, and gives the same command in full, one option
per line, to copy. Its first lines:

```text
fetch, with these settings:
  accounts.atlassian.site: https://<your-site>.atlassian.net
```

After a progress bar, it ends with Confluence's row: the window of the space, from the
start of 2000 to now, and what it would fetch:

```text
confluence: done
  space <KEY>: from 2000-01-01T00:00:00+00:00 to <now>, given
  confluence pages: to fetch: 13
  failures: 0
```

## 6. Run the chain

Now the run itself, each command going on from what the one before it wrote:

```bash
kb-mcp fetch --since all && kb-mcp prepare && kb-mcp index && kb-mcp embed
```

Each command starts as the dry run did, under its own name:

```text
fetch, with these settings:
  accounts.atlassian.site: https://<your-site>.atlassian.net
```

and ends its summary with `Proceed? [y/N]`: answer `y`, four times. A space of tens of
pages takes a minute or so. `fetch` ends with Confluence's row, and its counts:

```text
confluence: done
  confluence pages: fetched: 13
  files: downloaded: 10
  failures: 0
```

`prepare` ends with a row for each source that keeps a store, Jira holding nothing yet:

```text
confluence: done
  documents: 13
  converted by pandoc: 14
  reused from the cache: 0
  files written: 24
  files unchanged: 0
  files removed: 0
  problems: 0
jira: done
  documents: 0
  converted by pandoc: 0
  reused from the cache: 0
  files written: 0
  files unchanged: 0
  files removed: 0
  problems: 0
```

`index` ends with what the index holds, then what it did: there was no index, so it
built one whole, every document added:

```text
documents: 13
sections: 67
copied: 0
added: 13
replaced: 0
removed: 0
skipped: 0
rebuilt whole: unavailable
```

and `embed` with the pieces that the index holds, those it added and removed, the texts
that the model embedded, and the vector store:

```text
pieces: 45
added: 45
removed: 0
embedded now: 45
vectors pruned: 0
vector store: 0.2 MB
```

Run again, `index` reads only the files whose bytes changed, and `embed` embeds only the
texts that changed; with nothing changed, each says `nothing written`.

On macOS, `fetch` may not exit once its fetch is done: a known issue, which plan 013
is to diagnose and fix, parked for now
([the roadmap](../work/README.md#plans) lists it).

Look at what `prepare` wrote:

```bash
ls ~/kb-mcp/docs/confluence/<KEY>
```

A Markdown file per page, named by the page's id and its title, and `_tree.md`, the
space's tree of pages. The id is the page's ref, by which agents cite it. Each file
begins with front matter, where `fetched_at` is the page's mirror date: the time `fetch`
fetched it.

## 7. Give the mirror to Claude Code

Register the command as an MCP server, for every project:

```bash
claude mcp add --scope user --transport stdio kb-mcp -- kb-mcp
```

Claude Code starts it when a session starts. Then, so that no prompt interrupts a
search, allow its five tools by name in `~/.claude/settings.json`, merged into what the
file holds, if it exists:

```json
{
  "permissions": {
    "allow": [
      "mcp__kb-mcp__ask",
      "mcp__kb-mcp__search",
      "mcp__kb-mcp__read",
      "mcp__kb-mcp__browse",
      "mcp__kb-mcp__status"
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

- [Bring every source up to date](../how-to/refresh.md): `fetch` again, without `--since`,
  fetches what changed since the last fetch, only the revisions not yet stored, and asks
  again for what failed, so that a run that failed leaves no hole
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
- [Internals](../explanation/internals.md): what each of these commands did, and why.

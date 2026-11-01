# Mirror the site on a managed machine

How to mirror Confluence and Jira on the user's machine, where you sign in through your
company and the data must stay on the machine: the settings, a check of the machine, the
sign-in in Chrome, a first download of last week's pages and issues with their pictures,
then ending the session, and what may come back to the personal laptop. It needs uv and
Google Chrome, and pandoc for the mirror.
[Your first mirror](../tutorials/first-mirror.md) is the lesson of it all on any site,
with `sync`, the index and an agent.

## 1. Install the command

From a checkout of the repository on the user's machine (the checkout may live
anywhere; only the data directory must stay out of synchronised folders):

```bash
uv tool install --force .
```

Or run it from the checkout with `uv run kb-mcp …` instead. To complete
its subcommands and options with Tab, see [shell completions](shell-completions.md).

## 2. Settings

Create `~/.config/kb-mcp/config.toml`:

```toml
[accounts.atlassian]
site = "https://<your-site>.atlassian.net"

# Optional: what to download when no --space or --project is given.
[sources.confluence]
spaces = ["ENG", "OPS"]

[sources.jira]
projects = ["PLAT"]
```

`site` belongs to the Atlassian account's table, `spaces` and `projects` to their
sources': at the top of the file, where they were before, they are refused, and the
message names their table.

Each setting can also come from a variable, `KB_MCP_` then its path in
capitals joined by `__`, a list or a table in JSON
(`KB_MCP_ACCOUNTS__ATLASSIAN__SITE`,
`KB_MCP_SOURCES__JIRA__PROJECTS='["PLAT"]'`), and some from a flag
(`--site`, `--data-dir`, `--space`, `--project`). A flag wins over a variable, which
wins over the file, and a list replaces a weaker one whole. Each command says on stderr
which values it ignores: one replaced, a variable that names no setting, or one the
command does not use.

The data goes to `~/kb-mcp` unless `data_dir` says otherwise; the command
refuses a folder under iCloud, `~/Library/CloudStorage`, Dropbox, OneDrive, Google Drive,
`~/Desktop`, `~/Documents`, or inside a git working tree. Check it all with:

```bash
kb-mcp check --summary detailed
```

It shows every setting, its value and where it came from: the file, a variable, a flag,
or its default. Without `--summary detailed`, only those that the file, a variable or a
flag gave.

## 3. Doctor

```bash
kb-mcp doctor
```

It says where pandoc is (needed later by the mirror), whether the public CAs verify the
site (if not, TLS is inspected, and the operating system's trust store is used, as it
always is), and whether the sign-in works: the session that `login` saves, or an API
token.

## 4. Sign in

```bash
kb-mcp login atlassian
```

Like every command that writes under the data directory, it first says what it will do,
then asks `Proceed? [y/N]`: answer `y`.

Chrome opens on the site with a profile of its own (under
`~/kb-mcp/session/`). Sign in as usual; the window closes once Jira or
Confluence answers with your account. The session's cookies are kept in
`~/kb-mcp/session/cookies.json`, readable by you alone. If the sign-in
needs a browser extension, add `--keep-extensions`; if Playwright does not find Chrome,
add `--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`.

Where Chrome cannot sign in, an API token can: see [sign in with an API token kept by
sops](api-token-with-sops.md).

## 5. Download

```bash
kb-mcp fetch --space ENG --space OPS --project PLAT --since 7d
```

`--since` takes a length before now (`12h`, `7d`, `2w`, `6mo`, `1y`), an ISO date
(`2026-10-15`) or time, or `all`; `--until` the same but `all`, excluded. Each space is
listed whole (cheap: a few requests per thousand pages), and the pages, blog posts and
issues updated in the period are fetched with their attachments; video, audio, archives
and files over `--max-file-mb` (50) keep their metadata only. Expect about half a second
per document. Without `--since`, a space or a project never fetched takes its last 7
days. Once `--max-file-mb` is raised, a space's next run downloads the files it skipped,
as it reads its whole covered period; a project's issues get theirs only from a run
whose `--since` reaches them, such as `--since all`, since a project catches up from
its last fetch.

Before it starts, the download writes on stderr what it will do: each setting it reads
and its value, how it signs in, the values it ignores, and the same command written in
full, one option per line, to copy and run again. Then it asks `Proceed? [y/N]`: `y`
runs it, anything else does nothing and exits 1. `--yes` runs it without the question,
as a script needs: where no terminal can answer, the command is refused without it.
`--dry-run` lists and decides as a run would, then says what it would fetch, and
fetches nothing; it does not ask.

The counts are printed, a row per source, and saved in `~/kb-mcp/runs/`, a report per
source. The exit status is
0 when all went well, 1 when something failed (a space key that finds nothing is named
on stderr) or you answered no, 2 for refused settings or options, or no terminal to ask
on, 3 when you must sign in again, 130 when stopped by Ctrl-C. `kb-mcp
--help` lists them. Running the same command again without `--since` fetches only what
changed since each target's last fetch, and asks again for what failed; the counts then
say how many documents are new or changed, apart from how many are listed.

## End the session

The session that `login` saved signs in as you, from this machine or from any copy of
`~/kb-mcp/session/`, until it expires. End it when you leave the machine,
or as soon as that folder may have been copied:

1. On [your Atlassian account's security page][security], view and manage your recent
   devices, then log out of all devices but the browser you are using, as
   [Atlassian's guide][devices] describes. The sign-in window's Chrome is one of them:
   Atlassian ends its session on its side, wherever the cookies were copied. Your other
   browsers are signed out too.
2. Remove the folder, which holds the cookies and the sign-in window's own browser
   profile:

   ```bash
   rm -r ~/kb-mcp/session
   ```

A run signed in by the session then stops at once with exit status 3, and says to run
`login` again. Running `login` again replaces the saved cookies, but does not end the
session that they held: only the first step does.
[Credentials](../explanation/credentials.md) explains what the folder holds and why.

[security]: https://id.atlassian.com/manage-profile/security
[devices]: https://support.atlassian.com/atlassian-account/docs/manage-recently-used-devices-for-your-atlassian-account/

## What can come back to the personal laptop

The run reports in `~/kb-mcp/runs/` hold counts and the paths of fields
that a response no longer had, never titles, keys, names or content. They are what to
bring back if something needs fixing. Nothing under `raw/` or `session/` ever leaves
the user's machine.

# First download behind single sign-on

What to do on the user's machine to download last week's Confluence pages and Jira
issues, with their pictures. It needs the code of plan 004 (the branch `004-download`,
or `main` once it is merged), uv, and Google Chrome.

## 1. Install the command

From a checkout of the repository on the user's machine (the checkout may live
anywhere; only the data directory must stay out of synchronised folders):

```bash
uv tool install --force .
```

Or run it from the checkout with `uv run atlassian-offline-mcp …` instead.

## 2. Settings

Create `~/.config/atlassian-offline-mcp/config.toml`:

```toml
site = "https://<your-site>.atlassian.net"

# Optional: what to download when no --space or --project is given.
[sources.confluence]
spaces = ["ENG", "OPS"]

[sources.jira]
projects = ["PLAT"]
```

`spaces` and `projects` belong to their sources' tables: at the top of the file, where
they were before, they are refused, and the message names their table.

The data goes to `~/atlassian-offline-mcp` unless `data_dir` says otherwise; the command
refuses a folder under iCloud, `~/Library/CloudStorage`, Dropbox, OneDrive, Google Drive,
`~/Desktop`, `~/Documents`, or inside a git working tree. Check it all with:

```bash
atlassian-offline-mcp check
```

## 3. Doctor

```bash
atlassian-offline-mcp doctor
```

It says where pandoc is (needed later by the mirror), whether the public CAs verify the
site (if not, TLS is inspected, and the operating system's trust store is used, as it
always is), and whether a saved session signs in.

## 4. Sign in

```bash
atlassian-offline-mcp login
```

Chrome opens on the site with a profile of its own (under
`~/atlassian-offline-mcp/session/`). Sign in as usual; the window closes once Jira or
Confluence answers with your account. The session's cookies are kept in
`~/atlassian-offline-mcp/session/cookies.json`, readable by you alone. If the sign-in
needs a browser extension, add `--keep-extensions`; if Playwright does not find Chrome,
add `--chrome "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"`.

## 5. Download

```bash
atlassian-offline-mcp download --space ENG --space OPS --project PLAT --since 7d
```

`--since` takes `7d`, `2w`, or an ISO date (`2026-10-15`); `--until` an ISO date,
excluded. Each space is listed whole (cheap: a few requests per thousand pages), and
the pages, blog posts and issues updated in the period are fetched with their
attachments; video, audio, archives and files over `--max-file-mb` (50) keep their
metadata only. Expect about half a second per document.

The counts are printed and saved in `~/atlassian-offline-mcp/runs/`. The exit status is
0 when all went well, 1 when something failed (a space key that finds nothing is named
on stderr), 2 for refused settings or options, 3 when you must sign in again. Running
the same command again fetches only what changed since.

## What can come back to the personal laptop

The run reports in `~/atlassian-offline-mcp/runs/` hold counts and the paths of fields
that a response no longer had, never titles, keys, names or content. They are what to
bring back if something needs fixing. Nothing under `raw/` or `session/` ever leaves
the user's machine.

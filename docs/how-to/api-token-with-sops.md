# Sign in with an API token kept by sops

How to let `download` and `doctor` sign in with an Atlassian API token, rather than the
browser session that `login` saves, with the token encrypted at rest by
[sops](https://getsops.io) and given to the command in its environment alone. It suits a
machine where Chrome cannot open, or a test site with an account of its own.

## How the command takes a token

- Three settings of the Atlassian account sign in by token: `site`, `email` and
  `api_token`, under `[accounts.atlassian]`. The token is a secret, read from the
  variable `KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN` alone: the settings file refuses it
  and no flag takes it, so that it never reaches the file, your shell's history or a
  command line. The email comes from `KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL` or the settings
  file, the site from `KB_MCP_ACCOUNTS__ATLASSIAN__SITE`, the settings file or `--site`.
- With a token set, `download`, its dry run and `doctor` sign in with it, as Basic auth
  with the email, sent to the site's host alone, never to another host that a redirect
  leads to. Nothing under `<data>/session/` is read or written. The summary before a
  download says `sign-in: an API token`; `check` says `accounts.atlassian.api_token: set`,
  never the value.
- A token without its email is refused before anything is asked (exit 2); a token that
  the site refuses stops the run (exit 3), naming the two variables to check. `login`
  always signs in in the browser, and reports a token and an email as ignored.
- Generic names such as `ATLASSIAN_API_TOKEN` are never read, so that a token exported
  for another tool does not change how the command signs in.

## 1. Create the token

On [your account's API tokens][tokens], choose "Create API token", the one without
scopes: a token with scopes works only through `api.atlassian.com`, while the command
asks the site at its own address, `https://<name>.atlassian.net` ([Atlassian's
guide][guide]). Give it an expiry, a year at most, and copy it at once: it is not shown
again. It can read what its account reads; the command only reads.

[tokens]: https://id.atlassian.com/manage-profile/security/api-tokens
[guide]: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/

## 2. Keep it in a sops file

Create an encrypted file with your own sops keys (age or PGP, as your `.sops.yaml`
says), for instance with `sops edit ~/secrets/atlassian.sops.json`, holding:

```json
{
  "ATLASSIAN_SITE": "https://<name>.atlassian.net",
  "ATLASSIAN_EMAIL": "<you>@<company>",
  "ATLASSIAN_API_TOKEN": "<the token>"
}
```

`sops exec-env` decrypts the file in memory and puts each top-level key into the
environment of the command it runs. These generic names, which other tools may read
too, are mapped to the command's own in the next step; a file whose keys are already
`KB_MCP_ACCOUNTS__ATLASSIAN__SITE`, `KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL` and
`KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN` needs no mapping. A site already in the settings
file, under `[accounts.atlassian]`, needs no key at all.

## 3. Run the command through sops

Check the sign-in first:

```bash
sops exec-env ~/secrets/atlassian.sops.json 'KB_MCP_ACCOUNTS__ATLASSIAN__SITE="$ATLASSIAN_SITE" \
  KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL="$ATLASSIAN_EMAIL" \
  KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN="$ATLASSIAN_API_TOKEN" \
  kb-mcp doctor --summary detailed'
```

It says `sign-in: an API token`, then `confluence: signed in` and `jira: signed in`.
Then download:

```bash
sops exec-env ~/secrets/atlassian.sops.json 'KB_MCP_ACCOUNTS__ATLASSIAN__SITE="$ATLASSIAN_SITE" \
  KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL="$ATLASSIAN_EMAIL" \
  KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN="$ATLASSIAN_API_TOKEN" \
  kb-mcp download --yes --space ENG --project PLAT --since 7d'
```

The single quotes keep your shell from expanding anything: sops runs the quoted text
with `/bin/sh -c`, whose `NAME="$VALUE"` words set the command's environment. So only
the variables' names appear on a command line or in your history, never their values.

sops gives the command your terminal, so without `--yes` the download shows its summary
and asks, as it does outside sops. `--yes` runs it without the question, as a script
needs: where no terminal can answer, a command that writes is refused without it
(exit 2). `--dry-run` says what the download would fetch, and fetches nothing.

`mirror` and `index` read only the data directory, and need no token.

## Revoke the token

Revoke it once you no longer need it, or as soon as it may have leaked: a copy of the
token signs in as you, wherever it is, until it expires.

1. On [your account's API tokens][tokens], choose "Revoke" beside the token. Atlassian
   refuses it from then on, wherever a copy of it is.
2. Take it out of the sops file with `sops edit ~/secrets/atlassian.sops.json`, or put
   a new token in its place. The command keeps nothing of a token, in no file and in no
   log, so there is nothing else of it to remove.

A run given the revoked token stops at its first request with exit status 3, and says
`check KB_MCP_ACCOUNTS__ATLASSIAN__EMAIL and KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN`.
Without a token in its environment, a run signs in by the session that `login` saved, if
any.
[Credentials](../explanation/credentials.md) explains where each secret goes.

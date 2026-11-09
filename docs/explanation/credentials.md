# Credentials

How the program holds the three secrets that it may be given: the session that `login`
saves from a browser, an Atlassian API token with its account's email, and the embedding
endpoint's API key. For each, where it comes from, where it is kept and why, and where
it may travel; then what agents get, what is never logged, and what none of it guards
against. How to sign in is in
[fetch through SSO on a managed machine](../how-to/sso-machine.md) and
[the API token's how-to](../how-to/api-token-with-sops.md); why the program signs in so,
in [the trade-offs](trade-offs.md#cookies-and-api-tokens).

| Secret | Given by | Kept by the program | Sent to |
|---|---|---|---|
| the session's cookies | `login`, in a Chrome window | `<data>/session/cookies.json`, beside the window's own profile | the site's host alone |
| the API token, with its email | `KB_MCP_ACCOUNTS__ATLASSIAN__API_TOKEN`, in one run's environment | nowhere | the site's host alone, as Basic auth |
| the embedding key | `KB_MCP_EMBEDDING_API_KEY`, in one run's environment | nowhere | the embedding endpoint alone, as a bearer token |

A run signs in by the token when one is set, else by the saved session
([`choose_sign_in`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py)).
Either opens what the account may read; the program only reads it, as
[the wire](#on-the-wire) shows.

## The browser session

`login` opens Chrome on the site; you sign in as you always do, single sign-on
included; the site's cookies are then saved for the runs that follow. Each step limits
what the window sees and what it keeps:

- **A profile of its own.** Playwright starts the installed Chrome, or the executable
  that `--chrome` names where that fails, on a profile under `<data>/session/browser/`,
  never your everyday one, so that your other sign-ins, saved passwords and extensions
  stay out of it
  ([`login`](../../src/kb_mcp/sources/atlassian/fetch/app/login.py),
  [`open_sign_in_window`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py)).
  Extensions stay off unless `--keep-extensions` lets them load, for a sign-in that
  needs one.
- **Nothing remembered for you.** Password saving and autofill are turned off in that
  profile before the window opens
  ([`disable_password_saving`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py)):
  Playwright starts Chrome with a mock keychain, so the key that would protect a saved
  password is a fixed, public one, and whoever reads the profile would read the
  password.
- **No script on the identity provider's pages.** The window is watched from outside
  until it is back on the site; only there does a script ask the site for the current
  account, to see that the sign-in has ended
  ([`SIGNED_IN_JS`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py),
  held by
  [`test_a_sign_in_through_an_identity_provider_is_seen_to_end`](../../tests/test_browser.py)).
  It gives up after
  [`SIGN_IN_TIMEOUT_S`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py),
  five minutes, or as soon as you close the window
  ([`test_closing_the_window_on_the_identity_provider_is_seen`](../../tests/test_browser.py)).
- **The site's cookies alone.** Of the cookies that the window holds at the end, only
  those whose domain the site's host is within are saved; the identity provider's and
  Atlassian's own stay in the profile
  ([`for_site`](../../src/kb_mcp/sources/atlassian/fetch/adapters/session_file.py),
  [`test_only_the_site_cookies_of_the_browser_are_saved`](../../tests/test_login.py)).
- **Readable by you alone.** The folder is made with mode 0700, and the file is written
  with mode 0600 from its first byte, into a hidden file then renamed into place: a
  failure keeps the cookies saved before, and a looser mode from before never survives
  ([`write_cookies`](../../src/kb_mcp/sources/atlassian/fetch/adapters/session_file.py),
  [`test_a_file_already_open_to_others_is_replaced_by_one_that_is_not`](../../tests/test_session_file.py)).
- **Renewed as it is used.** The site renews the cookies as it answers, and a run
  signed in by the session writes them back
  ([`SavedSession.keep`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py)).
  Once they no longer hold, the next run stops with exit status 3, and you run
  `login atlassian` again.

Why a file: the session must outlive the run that made it, and no browser stays open
between runs to hold it. The profile stays too, since the next `login` opens it again,
and it holds the identity provider's and Atlassian's cookies. So the whole folder is a
sign-in: whoever reads it can act as you on the site until the session ends. That is
why the data directory may lie neither under a synchronised folder nor in a git working
tree, where it would be copied off the machine or committed
([`unsafe_location`](../../src/kb_mcp/config/domain/settings.py)), and
why agents never get it. To end it, see
[end the session](../how-to/sso-machine.md#end-the-session).

## The API token

A token suits a machine where Chrome cannot open, and the sandbox, against which agents
test. It reads whatever its account reads, for up to a year, so it is kept out of every
place where it would outlive a run:

- **From the environment alone.** The settings file refuses a token, naming the
  variable to use instead
  ([`file_entries`](../../src/kb_mcp/config/domain/settings.py),
  [`test_check_refuses_a_secret_in_the_settings_file`](../../tests/test_cli.py)), and no
  flag takes one, as [the commands](../reference/commands.md) show: it never sits in a
  file that other tools read, in your shell's history or on a command line. Generic
  names such as `ATLASSIAN_API_TOKEN` are not read, so that a token exported for another
  tool never changes how the command signs in
  ([`test_the_generic_atlassian_names_are_not_read`](../../tests/test_settings.py)).
- **Encrypted at rest, by sops.** The how-to keeps it in a sops file, which
  `sops exec-env` decrypts in memory into the environment of the one command it runs;
  the program itself never writes it
  ([`test_no_run_at_debug_says_or_leaves_a_secret`](../../tests/test_secrets.py)).
- **With its email, as one header.** A token without its email is refused before the
  run begins, with exit status 2
  ([`token_without_email`](../../src/kb_mcp/sources/atlassian/declared.py)).
  With it, it becomes the header of Basic auth, held by
  [`ApiToken`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  whose representation leaves the header out.
- **To the site's host alone.** The header is put on each request to the site's host,
  and taken off any other, such as one to the media host that an attached file
  redirects to, which httpx's own `auth` would follow
  ([`ApiToken.authorise`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`test_the_token_goes_to_the_site_s_host_alone`](../../tests/test_api_token.py)).
- **Nothing kept.** A run signed in by a token neither reads nor writes the saved
  session
  ([`ApiToken.keep`](../../src/kb_mcp/sources/atlassian/fetch/adapters/sign_in.py),
  [`test_a_run_with_the_token_leaves_a_saved_session_as_it_was`](../../tests/test_api_token.py)).
  A token that the site refuses stops the run with exit status 3, naming the two
  variables to check
  ([`test_a_fetch_refused_by_the_site_exits_3_naming_the_variables`](../../tests/test_api_token.py)).

To revoke it, see [revoke the token](../how-to/api-token-with-sops.md#revoke-the-token).

## The embedding endpoint's key

Ollama on this machine, the example of any OpenAI-compatible API, needs no key; a hosted
endpoint may. The key follows the token's rules: it comes from
`KB_MCP_EMBEDDING_API_KEY` alone, the settings file refuses it
([`test_a_secret_in_the_file_is_refused_by_name_never_by_value`](../../tests/test_settings.py)),
and no representation of the settings shows it
([`test_secrets_come_from_the_environment_and_are_never_shown`](../../tests/test_settings.py)).
It is sent as `Authorization: Bearer`, to the endpoint alone and only when set
([`open_endpoint`](../../src/kb_mcp/cli/commands/_embedding.py),
[`endpoint`](../../src/kb_mcp/search/adapters/model_api.py),
[`test_the_key_is_sent_only_when_set_and_never_said`](../../tests/test_embedding.py)).

The key travels with the mirror's text, so the rule that keeps the text keeps the key:
the endpoint must be a literal address of this machine, unless the run's own command
line says `--allow-remote-embeddings`, and one elsewhere is reached over https alone
([`refused_endpoint`](../../src/kb_mcp/kernel/endpoint.py),
[`test_a_remote_endpoint_needs_the_flag_and_https`](../../tests/test_embedding.py)). No
run hands its word to a later one: `eval-agents prepare` writes it into none of the
runs' files, and each `eval-agents call` of runs that need it is given it or refused
([`test_a_call_of_runs_off_this_machine_needs_its_own_consent`](../../tests/test_agents_eval.py)).
On this machine the environment's proxies are ignored, since one would carry both away
([`test_proxies_are_ignored_on_this_machine`](../../tests/test_embedding.py)), and a
redirect is never followed
([`test_a_redirect_is_not_followed`](../../tests/test_embedding.py)).
[Embeddings](../how-to/embeddings.md) says how to set an endpoint up.

## On the wire

Every request that the program makes with the saved session or the token goes through
one port, [`SiteClient`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py),
with the same rules whichever way the run signs in; the one other request that it makes
to the site, `doctor`'s, carries neither, as the end of this section says:

- **GET alone.** The port makes no other request, so the program changes nothing on the
  site, whatever its account may do
  ([`SiteClient.once`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py),
  [`test_a_run_sends_the_site_nothing_but_gets`](../../tests/test_fetching.py)).
- **https alone.** A request over plain http is refused before it is sent, so that
  neither cookie nor header travels in clear
  ([`refuse_plain_http`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py),
  [`test_a_request_over_plain_http_is_refused_before_it_is_sent`](../../tests/test_http.py)).
  TLS is verified by the operating system's trust store
  ([`client`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)).
- **Redirects to the site and Atlassian's media hosts alone.** A redirect within the
  site is followed, and one to
  [`MEDIA_HOSTS`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)
  for an attached file; one elsewhere, such as to a sign-in page, means the session no
  longer holds
  ([`SiteClient.once`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py),
  [`test_a_redirect_to_the_media_host_is_followed`](../../tests/test_http.py),
  [`test_a_redirect_to_the_identity_provider_means_sign_in_is_needed`](../../tests/test_http.py)).
  The cookies kept are the site's alone, so the media host gets none, and the token's
  header is taken off, as above.
- **A 401 means sign in again.** It stops the run, rather than failing one document
  ([`SignInNeededError`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py),
  [`test_a_401_means_sign_in_is_needed`](../../tests/test_http.py)), with exit status 3.
- **Through the environment's proxy.** The site's requests go through the proxy that
  `HTTPS_PROXY`, `HTTP_PROXY` or `ALL_PROXY` names, unless `NO_PROXY` names the site,
  and on macOS, with none set, through the system's proxy settings, as httpx reads them
  ([`client`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py) leaves
  them on). Over https, such a proxy sees the site's host and the times of the requests,
  not what they carry.

The trust store is the wire's one opening onto what requests carry. Where a company
inspects TLS, the operating system trusts its proxy's certificate, and the proxy reads
every request, the cookies and the token's header included. `doctor` says whether the
public certificate authorities verify the site, which they do not where TLS is inspected
([`verified_by_public_cas`](../../src/kb_mcp/sources/atlassian/fetch/adapters/http.py)),
by a GET of its own, outside `SiteClient`: on a client that trusts certifi's bundle of those
authorities alone, and that carries no cookie and no token.

## What agents get

An agent gets the mirror, never a sign-in.

- Of the settings, the server uses the index, the mirror, the search mode and the
  embedding endpoint with its key: never the site, the session nor the token
  ([`run`](../../src/kb_mcp/cli/commands/serve.py)). Its tools
  answer from the index and the mirror alone
  ([`Library`](../../src/kb_mcp/mcp/app/tools.py)); none reaches the
  site.
- An agent that reads files gets `<data>/docs/` alone, read-only, as
  [coding agents](../how-to/agents.md) sets it up: never `<data>/session/`, which is the
  sign-in, nor `<data>/raw/`.
- An agent starts the server with its own environment, which needs no token, and the
  key only where the endpoint asks for one, as the server's tests start it with a home
  alone
  ([`test_a_client_calls_every_tool_over_stdio`](../../tests/test_serve.py)).

## What is never logged

What a run logs is for you, on this machine, and may hold titles and queries
([observability](observability.md#why-the-logs-may-hold-titles)); it holds no secret:

- Every event is redacted before any sink: what a key naming a secret holds reads
  `[redacted]`
  ([`redacted`](../../src/kb_mcp/observability/domain/redaction.py)).
  The rule reads keys, not values, so the code never logs a header, and shows a URL's
  query on the site's host alone, as a media redirect carries a signed token in its
  query
  ([`ObservedTransport`](../../src/kb_mcp/observability/adapters/http.py)).
- A secret setting is never shown: the echo before a run and `check` say whether it
  is set
  ([`setting_line`](../../src/kb_mcp/cli/domain/echo.py),
  [`test_check_shows_no_secret_in_any_format_or_summary`](../../tests/test_api_token.py)),
  and `run.start` masks it.
- A refused setting is named with the layer that gave it, never with its value, since
  a secret pasted in the wrong place would be echoed
  ([`settings_of`](../../src/kb_mcp/config/domain/settings.py),
  [`test_a_setting_refused_with_a_secret_as_its_value_does_not_echo_it`](../../tests/test_secrets.py)).
- A traceback shows no frame's locals, where a token could sit
  ([`log_file`](../../src/kb_mcp/observability/adapters/logs.py)).

End to end,
[`test_no_run_at_debug_says_or_leaves_a_secret`](../../tests/test_secrets.py) runs
`fetch` by the token, then by the session, `prepare`, `index`, `embed`, and a `serve`
that answers one search, all at debug, each secret a sentinel that is really sent: the
token, its Basic form and the key are in no file of the home or the data directory, nor
on stdout or stderr, and the cookie is in `cookies.json` alone.
[`test_no_secret_reaches_the_files_stderr_or_telemetry_at_debug`](../../tests/test_telemetry.py)
holds the same of telemetry, and [observability](observability.md#secrets-out-of-every-sink)
says why each sink is so.

## What none of it guards against

The modes keep other users out; the rest keeps secrets from being sent or written by
mistake. None of it stops someone who is already on the machine as you:

- **Another process of yours.** A file of mode 0600 is yours, so every program you run
  can read it: the cookies, the profile, the mirror. So can it read the token or the key
  while a run holds them, in its environment and its memory.
- **A copied disk, or a backup.** The program encrypts nothing under the data
  directory: the cookies are in clear
  ([`write_cookies`](../../src/kb_mcp/sources/atlassian/fetch/adapters/session_file.py)),
  the profile's key is public
  ([`disable_password_saving`](../../src/kb_mcp/sources/atlassian/fetch/adapters/browser.py)),
  the mirror is plain Markdown. A backup of your home copies the data directory as
  it copies any folder: the guard refuses synchronised folders and git working trees,
  nothing else
  ([`unsafe_location`](../../src/kb_mcp/config/domain/settings.py)). The
  disk's own encryption, such as FileVault or LUKS, is what keeps a lost machine's data.
- **A tunnel.** The services' rules, of the embedding endpoint, the reranking server and
  telemetry's, trust that a loopback address is this machine
  ([`refused_endpoint`](../../src/kb_mcp/kernel/endpoint.py)). A port of this
  machine forwarded elsewhere, by an SSH tunnel say, carries what is sent to it there:
  the mirror's text and the key, or telemetry's records. The rule cannot see it.
- **A copy made before the end.** A session or a token copied elsewhere signs in as you
  until it expires, or until you
  [end the session](../how-to/sso-machine.md#end-the-session) or
  [revoke the token](../how-to/api-token-with-sops.md#revoke-the-token).

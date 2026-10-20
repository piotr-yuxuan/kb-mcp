# Proof test: Atlassian Cloud REST through a browser session

This folder holds the probe of plan 001 (`docs/work/plans/001-proof-test.md`). It
answers one question: can a script that uses your own signed-in browser session read,
through Atlassian Cloud's REST APIs, everything you see on a page? That means its
text, nested includes, dynamic tables, and images at full resolution. Run it on the
sandbox first, then on a real site.

## 1. Prepare the sandbox

**Jira.** The sandbox site has no Jira yet. Add Jira (Free plan) to the site, then
create a project with the key `PRB` and three issues. In the first issue, paste an
image into the description.

**Confluence.** `spikes/seed_sandbox.py` creates these pages through the REST API,
all but the Jira issues macro, which needs Jira on the site first. Run it through sops,
so the token reaches that one process:

```bash
sops exec-env <credentials file> 'uv run spikes/seed_sandbox.py --space MFS --issue PRB-1'
```

`--issue` gives that issue an image in its description. Insert the Jira issues table by
hand: `/jira` in the editor now adds a Smart Link table, which the probe reads as well
as the classic Jira issues macro. Publish the page afterwards.

The pages, to create by hand otherwise, in any space:
1. **Probe innermost**: an Excerpt macro around one sentence, then an uploaded image
   wider than 200 pixels.
2. **Probe middle**: an Include page macro showing *Probe innermost*, then a sentence of
   its own.
3. **Probe complex**, with:
   - an Include page macro showing *Probe middle*, which nests two levels deep;
   - an Excerpt include macro showing *Probe innermost*;
   - a Jira issues macro in table mode, with the JQL `project = PRB ORDER BY key`;
   - a Page properties report on the label `probe-props`;
   - a Children display macro;
   - an Info panel, a Code block, an Expand with text inside, and a table of three rows
     and three columns;
   - an uploaded image.
4. **Probe properties 1** and **Probe properties 2**, outside *Probe complex*, each
   with a Page properties macro (a table of two rows) and the label `probe-props`.
5. **Probe child**, a child of *Probe complex*, so that children display lists a page
   that the report does not.
6. **Probe long**: about 3,000 words of public-domain text, with headings.

A page's id is the number after `/pages/` in its address.

## 2. Level 0, by hand

In your usual Chrome, signed in, open these addresses on the site, with `<id>` the id
of the most complex page:
1. `/wiki/api/v2/spaces?limit=1` and `/rest/api/3/myself` show JSON.
2. `/wiki/api/v2/pages/<id>?body-format=view`: in `body.view.value`, Cmd-F finds a
   sentence from the innermost include. A Jira table is not there: the browser draws
   it, and steps 3 and 4 read it instead.
3. `/wiki/api/v2/pages/<id>?body-format=storage` holds the Jira table's JQL: in the
   `jql` of a `data-datasource` attribute for a table inserted with `/jira`, or in the
   `jqlQuery` parameter of an older Jira issues macro.
4. `/rest/api/3/search/jql?jql=<that JQL, URL-encoded>&fields=summary` lists the
   issues that the page's table shows.
5. `/wiki/api/v2/pages/<id>/attachments` lists an image. Then
   `/wiki/rest/api/content/<id>/child/attachment/<its id>/download` opens it at its
   original size.

If any step fails, stop and record it: the REST route is then dead whatever the
script does.

## 3. Level 1, the script

On the Mac:

```bash
uv run spikes/session_probe.py --site https://<site>.atlassian.net --page <complex id> --page <long id> --issue PRB-1
```

On NixOS, Playwright cannot find Chrome by itself. Add
`--chrome "$(command -v google-chrome-stable)"`.

A Chrome window opens on a dedicated profile. Sign in; the probe waits up to five
minutes, then continues by itself and opens each page in that window. Add
`--keep-extensions` if your sign-in needs a Chrome extension. Pass up to three
pages; the carriers are probed on the first.

The next day, check that the saved session still works without a browser:

```bash
uv run spikes/session_probe.py --site https://<site>.atlassian.net --page <complex id> --no-sign-in
```

The profile lives in `~/Library/Application Support/atlassian-offline-mcp/probe-browser`
on macOS and in `~/.local/state/atlassian-offline-mcp/probe-browser` on Linux. It holds
your session's cookies, and also the titles and addresses of the pages the probe opened
and cached copies of what they loaded, protected by no secret key. The probe turns off
Chrome's offer to save passwords in this profile; if Chrome asks anyway, decline.
Delete the profile when you are done.

The probe's own REST reads are GET requests only. Opening a page in its Chrome window,
though, is an ordinary visit: Confluence records your view, and the app makes its own
requests.

## 4. Reading the report

Each line starts with PASS or FAIL, then the check's name, then numbers. The last line
counts both.

| Check | What it shows |
|---|---|
| `sign-in` | Seconds until REST answered from inside the signed-in page |
| `<carrier>: <read>` | Status, media type, bytes and milliseconds of one read through one carrier: `httpx` (no browser), `request context` (Playwright) or `in-page fetch` |
| `page-N: macro <name>` | How many of the page's macros of that kind have output in the REST `view` body; a third-party macro shows as `custom-N` |
| `page-N: words` | The share of the words shown in the browser that the `view` body holds; the target is 98% |
| `page-N: tables`, `page-N: images` | Tables and images in each; attachment images are compared at full size, external images are counted apart |
| `page-N: jql N`, `cql N`, `key N` | A dynamic table's query run over REST (a JQL search, a CQL search, or the one issue read): how many of its results the browser shows, and how many the macro's own output in the `view` body holds. No result over REST is a FAIL, since nothing is compared |
| `page-N: timing` | REST reads against a full render in the browser |
| `issue: …` | The issue over REST, the images of its rendered description, and its first image downloaded |
| `tls: public CA bundle` | A FAIL means TLS inspection; the probe verifies with your system's certificates anyway |

The report holds no title, text, address, id or cookie, so it can leave the machine.
Read it before copying it anyway. Plan 001's outcome table says what each result
decides.

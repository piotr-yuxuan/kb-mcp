# Commands

What the command says with `--help`, then each of its subcommands, and each step of one,
as the parser declares them; then the exit statuses. This page is generated from the
code by `uv run python -m tests.reference_pages`, and `tests/test_reference.py` fails
while it differs: change a subcommand's declaration in
[`cli/options/`](../../src/kb_mcp/cli/options/), then run that command;
never edit the page.

With no arguments, the command serves MCP on stdio, as `serve` does: that is how agents
start it ([`main`](../../src/kb_mcp/cli/main.py)). A flag that overrides
a setting does so for its run alone, the strongest of the layers that
[the settings](settings.md) describe. Help is shown here 88 columns wide and without
colour; `~` stands for the home directory, and `<log directory>` for the platform's
folder of logs.

## `kb-mcp`

```text
usage: kb-mcp [-h] [--version] command ...

Knowledge base MCP: an offline mirror of Confluence and Jira Cloud, served over MCP.

positional arguments:
  command
    check        validate the settings and the data directory
    completion   print the code that completes the command in bash and zsh
    doctor       check the machine and the sign-in
    embed        build the search index again with vectors, then prune the vector
                 store
    eval         measure search and ask on golden questions, by mode, model and
                 chunking
    eval-agents  evaluate ask through agents: prepare their runs, bridge their calls,
                 grade
    eval-rerank  measure search reranked at each depth on golden questions, against
                 the bar
    fetch        bring what changed in each source into its store
    index        build the search index of the mirror's words
    login        sign in once, in a Chrome window
    model        check the embedding model and its endpoint
    prepare      turn what each source holds into the Markdown mirror
    reranker     check the reranking server and its model
    serve        serve the mirror over MCP on stdio
    sync         bring the configured sources up to date: fetch each, prepare each,
                 then the index

options:
  -h, --help     show this help message and exit
  --version      show the version

The commands that write under the data directory (embed, eval, eval-agents, eval-
rerank, fetch, index, login, prepare, sync) first say what they will do, with the
command to copy, then ask; --yes, or --dry-run where taken, runs them without asking,
and with no terminal to ask on, they are refused. Exit statuses: 0 done; 1 something
failed (a document, a file, a check, the endpoint), or the question was declined; 2
refused before acting: settings, options or input, or no terminal to ask on; 3 sign in
again: no session saved, it no longer holds, or the site refused the API token; 130
stopped by Ctrl-C.
```

## `check`

```text
usage: kb-mcp check [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it

With --format json: settings, secrets masked; layers, the layer of each setting that
one gave; ignored, each value ignored, with its setting, layer and why.
```

## `completion`

```text
usage: kb-mcp completion [-h] [-q | -v | --log-level {debug,info,warning,error}]

Print the code that completes the command in bash and zsh. Add eval "$(kb-mcp
completion)" to ~/.bashrc, or to ~/.zshrc after compinit.

options:
  -h, --help            show this help message and exit
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
```

## `doctor`

```text
usage: kb-mcp doctor [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                     -v | --log-level {debug,info,warning,error}]
                     [--format {text,json}] [--summary {short,detailed}]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it

With --format json: a list of verdicts, each a check's name, what it found, and its
state: well, failed, or sign in.
```

## `embed`

```text
usage: kb-mcp embed [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}] [-y]
                    [--allow-remote-embeddings]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine

With --format json: report, the documents by type, the sections, the files skipped,
the pieces by meaning, the texts embedded now and the files with a piece refused;
index, its path; model, the one that embedded; pruned, what the prune of the vector
store kept and deleted, or why it did not prune.
```

## `eval`

```text
usage: kb-mcp eval [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                   -v | --log-level {debug,info,warning,error}] [--format {text,json}]
                   [--summary {short,detailed}] [-y] [--allow-remote-embeddings]
                   [--model MODEL]
                   [--chunking {sections,windows,section-paths,small-to-big}]
                   golden

positional arguments:
  golden                a YAML file of golden questions

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine
  --model MODEL         a model to evaluate, as the endpoint names it; by default, the
                        setting
  --chunking {sections,windows,section-paths,small-to-big}
                        a chunking to evaluate; by default, every one

With --format json: runs, each model's and chunking's measures of search and ask by
mode and group, with its ranks, times, costs and tests; choices, each model's default
chunking by the rule; results, the file that keeps them.
```

## `eval-agents`

```text
usage: kb-mcp eval-agents [-h] [-q | -v | --log-level {debug,info,warning,error}]
                          [--format {text,json}] [--summary {short,detailed}]
                          step ...

positional arguments:
  step
    prepare             write each run's prompt, and runs.json
    call                call a tool for a run, and print its answer
    answer              keep a run's answer, once
    grade               grade the runs, and judge ask; keep the results

options:
  -h, --help            show this help message and exit
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it

Its options of output come before the step. With --format json: prepare, the runs
written; call, the answer; answer, the answer kept; grade, each run's outcome, the
verdict on ask and the runs counted.
```

## `eval-agents prepare`

```text
usage: kb-mcp eval-agents prepare [-h] [--config CONFIG] [--data-dir DATA_DIR]
                                  [--site SITE] [-y] [--allow-remote-embeddings]
                                  --out OUT --model {haiku,sonnet} [--sample SAMPLE]
                                  [--seed SEED] [--dry-run]
                                  golden

positional arguments:
  golden                a YAML file of golden questions

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -y, --yes             run without asking first, as a script does
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine
  --out OUT             the runs' directory, new or empty
  --model {haiku,sonnet}
                        the agents' model, by its alias
  --sample SAMPLE       this many questions, chosen by the seed; else all
  --seed SEED           the sample's seed
  --dry-run             say what would be prepared, and write nothing
```

## `eval-agents call`

```text
usage: kb-mcp eval-agents call [-h] [--config CONFIG] [--data-dir DATA_DIR]
                               [--site SITE]
                               directory run tool arguments

positional arguments:
  directory            the runs' directory
  run                  the run's id
  tool                 the tool's name
  arguments            the tool's arguments, as one JSON object

options:
  -h, --help           show this help message and exit
  --config CONFIG      the settings file
  --data-dir DATA_DIR  the data directory, overriding the settings
  --site SITE          the site, as https://<name>.atlassian.net
```

## `eval-agents answer`

```text
usage: kb-mcp eval-agents answer [-h] [--config CONFIG] [--data-dir DATA_DIR]
                                 [--site SITE]
                                 directory run answer

positional arguments:
  directory            the runs' directory
  run                  the run's id
  answer               the answer, as one JSON object

options:
  -h, --help           show this help message and exit
  --config CONFIG      the settings file
  --data-dir DATA_DIR  the data directory, overriding the settings
  --site SITE          the site, as https://<name>.atlassian.net
```

## `eval-agents grade`

```text
usage: kb-mcp eval-agents grade [-h] [--config CONFIG] [--data-dir DATA_DIR]
                                [--site SITE] [-y]
                                directory

positional arguments:
  directory            the runs' directory

options:
  -h, --help           show this help message and exit
  --config CONFIG      the settings file
  --data-dir DATA_DIR  the data directory, overriding the settings
  --site SITE          the site, as https://<name>.atlassian.net
  -y, --yes            run without asking first, as a script does
```

## `eval-rerank`

```text
usage: kb-mcp eval-rerank [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE]
                          [-q | -v | --log-level {debug,info,warning,error}]
                          [--format {text,json}] [--summary {short,detailed}] [-y]
                          [--allow-remote-embeddings] [--depth DEPTH]
                          [--sample SAMPLE] [--seed SEED]
                          golden

positional arguments:
  golden                a YAML file of golden questions

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine
  --depth DEPTH         documents reranked, as one arm; by default 10, 20, 30, 50, the
                        bar's
  --sample SAMPLE       this many questions, chosen by the seed; else all
  --seed SEED           the sample's seed

With --format json: arms, each depth's measures of search and ask by group, with its
ranks, times, tokens and Recall@N, depth 0 the order not reranked; decision, the bar's
verdicts and default depth; results, the file that keeps them.
```

## `fetch`

```text
usage: kb-mcp fetch [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}] [-y]
                    [--dry-run] [--space SPACE] [--since SINCE] [--until UNTIL]
                    [--max-file-mb MAX_FILE_MB] [--project PROJECT]
                    [{confluence,jira} ...]

positional arguments:
  {confluence,jira}     the sources to fetch, given together; by default each one
                        configured

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --dry-run             say what a run would fetch, and fetch nothing

confluence:
  Confluence, on the Atlassian site: the pages and blog posts of its spaces: pages,
  listed whole; blogposts, listed whole.

  --space SPACE         a space key, in place of the setting's; repeat for more

jira:
  Jira, on the Atlassian site: the issues of its projects: issues, searched by
  update time.

  --project PROJECT     a project key, in place of the setting's; repeat for more

several sources:
  The options of confluence, jira.

  --since SINCE         12h, 7d, 6mo, an ISO date or time, or all; by default, each
                        target's last fetch
  --until UNTIL         12h, 7d, or an ISO date or time, excluded; by default, now
  --max-file-mb MAX_FILE_MB
                        the largest file kept, in MB; 50 by default

With --format json: exit_status, the run's; sources, a row per source taken, in the
registry's order, each with its source, its outcome (done, failed, sign in,
interrupted, not run) and its result, null when it gave none: its outcome, and under
downloaded, null when the fetch could not start: report, the counts of what the fetch
did, or with --dry-run would do; failed_targets, the targets that failed; status, its
exit status; windows, each target's: its start, end and reason, and its coverage,
extended, capped at a failure, held, or null when not written; dry_run, whether the
fetch only planned.
```

## `index`

```text
usage: kb-mcp index [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}] [-y]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does

With --format json: report, the documents by type, the sections and the files skipped;
index, its path; model and pruned, null.
```

## `login`

```text
usage: kb-mcp login [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}] [-y]
                    [--chrome CHROME] [--keep-extensions]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --chrome CHROME       Chrome's executable, where the chrome channel fails
  --keep-extensions     let Chrome load extensions, for SSO

With --format json: site, the site signed in to; session, the folder that keeps the
session.
```

## `model`

```text
usage: kb-mcp model [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--format {text,json}] [--summary {short,detailed}]
                    [--allow-remote-embeddings]
                    {check} [name]

positional arguments:
  {check}
  name                  the model to check; by default, the setting

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine

With --format json: name and dimensions, the model's; url, the endpoint; digest, the
model's, empty when the endpoint reports none.
```

## `prepare`

```text
usage: kb-mcp prepare [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                      -v | --log-level {debug,info,warning,error}]
                      [--format {text,json}] [--summary {short,detailed}] [-y]
                      [--dry-run]
                      [{confluence,jira,worklog} ...]

positional arguments:
  {confluence,jira,worklog}
                        the sources to prepare, given together; by default those that
                        keep a store, and each one read in place that is configured

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --dry-run             count what a run would convert and remove, where a source can
                        tell; write nothing

confluence:
  Confluence, on the Atlassian site: the pages and blog posts of its spaces: pages,
  listed whole; blogposts, listed whole.

jira:
  Jira, on the Atlassian site: the issues of its projects: issues, searched by
  update time.

worklog:
  The user's work log: org files read in place, never written: entries, in place;
  days, in place; meetings, in place; transcripts, in place.

With --format json: exit_status, the run's; sources, a row per source taken, in the
registry's order, each with its source, its outcome (done, failed, interrupted, not
run) and its result, null when it gave none: its outcome, and under mirrored what the
source's documents became, null when it did not run: documents, how many are mirrored;
for Confluence and Jira, converted, the conversions pandoc ran, and reused, those the
cache gave, a document's file and a space's tree being one each; changes, the files
written, unchanged and removed; unsupported, what the mirror does not show, by name;
problems, each by its place and why; elsewhere, those that it found reading the other
source's, by that source, which fail nothing of its own.
```

## `reranker`

```text
usage: kb-mcp reranker [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE]
                       [-q | -v | --log-level {debug,info,warning,error}]
                       [--format {text,json}] [--summary {short,detailed}]
                       {check} [name]

positional arguments:
  {check}
  name                  the model to check; by default, the setting

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it

With --format json: model, the one checked; url, the server; served, the models that
it lists; answering and unrelated, the probe's scores; depth and seconds, a request of
rerank.depth texts as long as a search sends, timed.
```

## `serve`

```text
usage: kb-mcp serve [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                    -v | --log-level {debug,info,warning,error}]
                    [--allow-remote-embeddings]
                    [--tools ask,search,read,browse,status] [--rerank | --no-rerank]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine
  --tools ask,search,read,browse,status
                        the tools to serve, comma-separated; by default, every one
  --rerank              rerank through the reranking server, whatever the settings say
  --no-rerank           search without the reranking server, whatever the settings say
```

## `sync`

```text
usage: kb-mcp sync [-h] [--config CONFIG] [--data-dir DATA_DIR] [--site SITE] [-q |
                   -v | --log-level {debug,info,warning,error}] [--format {text,json}]
                   [--summary {short,detailed}] [-y]
                   [--include {confluence,jira,worklog} |
                   --exclude {confluence,jira,worklog}] [--space SPACE]
                   [--since SINCE] [--until UNTIL] [--max-file-mb MAX_FILE_MB]
                   [--project PROJECT] [--allow-remote-embeddings] [--dry-run]

options:
  -h, --help            show this help message and exit
  --config CONFIG       the settings file
  --data-dir DATA_DIR   the data directory, overriding the settings
  --site SITE           the site, as https://<name>.atlassian.net
  -q                    say errors alone, and write no result as text
  -v                    the level info, or debug with -vv
  --log-level {debug,info,warning,error}
                        say what is of this level or above; warning by default
  --format {text,json}  write the result as text, or as one JSON document
  --summary {short,detailed}
                        write what matters of the result, or all of it
  -y, --yes             run without asking first, as a script does
  --include {confluence,jira,worklog}
                        sync this source alone, if configured; repeat for more
  --exclude {confluence,jira,worklog}
                        sync every configured source but this one; repeat for more
  --space SPACE         a space key, in place of the setting's; repeat for more
  --since SINCE         12h, 7d, 6mo, an ISO date or time, or all; by default, each
                        target's last fetch
  --until UNTIL         12h, 7d, or an ISO date or time, excluded; by default, now
  --max-file-mb MAX_FILE_MB
                        the largest file kept, in MB; 50 by default
  --project PROJECT     a project key, in place of the setting's; repeat for more
  --allow-remote-embeddings
                        let this run send the mirror's text to an embedding endpoint
                        off this machine
  --dry-run             say what the run would fetch, and change where a source can
                        tell; write nothing

With --format json: exit_status, the run's; steps, a row per step and source, the
fetch of each source that has a fetcher, then the prepare of each, then the index,
each with its step (fetch, prepare, index), its source, null for the index, its
outcome (done, failed, sign in, interrupted, not run) and its result, null when it
gave none: a fetch's or a prepare's outcome, and what the source's own command gives,
under downloaded or mirrored; the index's, as index gives it.
```

## Exit statuses

Every command ends with one of these statuses, which
[`MEANINGS`](../../src/kb_mcp/kernel/exit_status.py) defines once, for
`--help` and for this page.

| Status | Meaning |
|---|---|
| 0 | done |
| 1 | something failed (a document, a file, a check, the endpoint), or the question was declined |
| 2 | refused before acting: settings, options or input, or no terminal to ask on |
| 3 | sign in again: no session saved, it no longer holds, or the site refused the API token |
| 130 | stopped by Ctrl-C |

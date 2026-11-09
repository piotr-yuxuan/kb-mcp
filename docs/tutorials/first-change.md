# Your first change

For contributors. In this tutorial we add a subcommand, `count`, which prints how many
documents the mirror holds of each source. On the way we run the checks that every
change passes, watch two of them refuse a change, and set it right. `count` is for
learning: the repository has no such command, and we put it aside at the end. Follow the
steps in order: each shows what you should see. Counts that grow with the code, of files
and of tests, are written `<n>`, and the time a run takes `<time>`; where your output
shows other numbers, that is your clone's state, not a fault.

## What you need

- macOS or Linux, with git, [uv](https://docs.astral.sh/uv/) and
  [pandoc](https://pandoc.org/installing.html), with which the tests convert pages.
- No site and no sign-in: everything here runs offline. If you followed
  [your first mirror](first-mirror.md), `count` counts that mirror.

## 1. Clone and install

Clone the repository, unless your first mirror cloned it already, and go into it:

```bash
git clone https://github.com/piotr-yuxuan/kb-mcp.git ~/src/kb-mcp
```

```bash
cd ~/src/kb-mcp
```

Every command from here on runs in that folder. Install the command and the tools that
check it, Ruff, Import Linter and pytest, into the clone's own environment:

```bash
uv sync
```

uv makes the environment, with Python 3.14, which it downloads if you have none, then
lists what it installs. Its first lines:

```text
Using CPython 3.14.8
Creating virtual environment at: .venv
```

## 2. See the checks pass

[`AGENTS.md`](../../AGENTS.md) names five checks, which every commit passes. Run each
once now, so that you know what passing looks like. Ruff lints the code:

```bash
uv run ruff check
```

```text
All checks passed!
```

Ruff also formats it, and this says whether any file would change:

```bash
uv run ruff format --check
```

```text
<n> files already formatted
```

Import Linter keeps the code's layout: which part may import which, as
[the code's layout](../explanation/code-layout.md#the-contracts) explains.

```bash
uv run lint-imports
```

It ends with:

```text
Contracts: 11 kept, 0 broken.
```

pytest runs the tests, spread over every core by `-n auto` (pytest-xdist), in a minute or
two:

```bash
uv run pytest -n auto
```

It ends with:

```text
<n> passed, <n> skipped in <time>
```

The last check runs the tests of the sandbox's corpus, with its own requirements:

```bash
uv run --with-requirements sandbox/seed_corpus.py --with pytest pytest sandbox
```

It ends with:

```text
<n> passed in <time>
```

## 3. Write the test first

`count` rests on one rule: given the paths of the mirror's documents and the names of
the sources, how many each source has. A rule decides without effects, with no file,
clock or network, so it lives in a layer named `domain`, here the mirror's:
`src/kb_mcp/mirror/domain/`. A rule is the easiest code to test, so we
write its test first, from what `count` must do. Create `tests/test_count.py`:

```python
"""``count``: how many documents the mirror holds of each source."""

from pathlib import PurePosixPath

from kb_mcp.mirror.domain.count import per_source


def test_each_source_counts_its_documents_and_one_without_any_counts_zero() -> None:
    """A document's source is the first folder of its path in the mirror."""
    documents = [
        PurePosixPath("confluence/ENG/196609-home.md"),
        PurePosixPath("confluence/OPS/blog/196700-release-notes.md"),
        PurePosixPath("jira/PLAT/PLAT-1.md"),
    ]
    sources = ["confluence", "jira", "worklog"]
    assert per_source(documents, sources) == {"confluence": 2, "jira": 1, "worklog": 0}
```

Run it alone:

```bash
uv run pytest tests/test_count.py
```

It fails, as it should, since the rule does not exist yet. Among its lines:

```text
E   ModuleNotFoundError: No module named 'kb_mcp.mirror.domain.count'
```

## 4. Write the rule

Create `src/kb_mcp/mirror/domain/count.py`:

```python
"""How many documents the mirror holds of each source: a rule, without effects."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import PurePath


def per_source(documents: Iterable[PurePath], sources: Iterable[str]) -> dict[str, int]:
    """Count the documents of each source, as their paths in the mirror name it.

    Each source named is counted, one without documents as 0.
    """
    found = Counter(document.parts[0] for document in documents)
    return {source: found[source] for source in sources}
```

The rule takes the sources' names rather than knowing them: each source is declared in
its own package, and the registry lists them
([`SOURCES`](../../src/kb_mcp/sources/registry.py)), which the command, step 5,
hands to the rule, so that `count` names each source as `prepare` does. Run the test
again:

```bash
uv run pytest tests/test_count.py
```

It ends with:

```text
1 passed in 1.03s
```

## 5. Declare the subcommand, and run it

A subcommand is two modules. Its declaration, in `cli/options/`, is light: the parser
imports every declaration for `--help`, finds each by itself, and gives each the
registry, which `count`'s does not need ([`parser`](../../src/kb_mcp/cli/main.py)). Its
run, in `cli/commands/`, is imported only once it is chosen. Create
`src/kb_mcp/cli/options/count.py`:

```python
"""``count``'s declaration; ``cli.commands.count`` runs it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.cli.domain.command import Command
from kb_mcp.cli.options._common import add_output_options, add_settings_options

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from kb_mcp.sources.declaration import Source


def register(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    _sources: Sequence[Source],
) -> None:
    """Add ``count`` to the command."""
    parser = subparsers.add_parser(
        "count",
        help="count the mirror's documents per source",
        epilog="With --format json: each source, and how many documents it has.",
    )
    actions, flags = add_settings_options(parser)
    add_output_options(parser)
    parser.set_defaults(
        command=Command(
            "count",
            "kb_mcp.cli.commands.count",
            reads=("data_dir",),
            flags=flags,
            actions=actions,
        )
    )
```

The [`Command`](../../src/kb_mcp/cli/domain/command.py) names the module
that runs it and the one setting that it reads, the data directory, which `--data-dir`
may give ([`add_settings_options`](../../src/kb_mcp/cli/options/_common.py)).
The epilog says what `--format json` writes, as a test of `tests/test_cli.py` asks of
every subcommand. Then create `src/kb_mcp/cli/commands/count.py`:

```python
"""``count``: how many documents the mirror holds of each source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kb_mcp.kernel.exit_status import ExitStatus
from kb_mcp.mirror.adapters.markdown import documents
from kb_mcp.mirror.domain.count import per_source
from kb_mcp.sources.registry import SOURCES

if TYPE_CHECKING:
    import argparse

    from kb_mcp.config.domain.settings import Loaded
    from kb_mcp.kernel.output import Summary


def run(_arguments: argparse.Namespace, loaded: Loaded) -> tuple[ExitStatus, dict[str, int]]:
    """Count the documents that the mirror holds, under the data directory, by source."""
    docs = loaded.settings.docs
    found = (path.relative_to(docs) for path in documents(docs))
    return ExitStatus.OK, per_source(found, (declared.name for declared in SOURCES))


def text(counts: dict[str, int], _summary: Summary) -> str:
    """Write a line per source: its name, then how many documents it has."""
    return "".join(f"{source}: {count}\n" for source, count in counts.items())
```

Finding the files is an effect, so it stays out of the rule: the run takes the mirror's
folder from the settings
([`Settings.docs`](../../src/kb_mcp/config/domain/settings.py)), lets
[`documents`](../../src/kb_mcp/mirror/adapters/markdown.py), in the
mirror's `adapters` layer, find the files there, and hands their paths to the rule,
with the names of the registry's sources: the command, in `cli`, may import the
sources, which the mirror, below them, may not.
What the run returns, the entry of every subcommand writes, as text or as JSON
([`enter`](../../src/kb_mcp/cli/commands/_shared.py)). Run it:

```console
$ uv run kb-mcp count
confluence: 13
jira: 0
worklog: 0
```

These are the counts of your first mirror; without a mirror, each is 0. And as JSON:

```console
$ uv run kb-mcp count --format json
{
  "confluence": 13,
  "jira": 0,
  "worklog": 0
}
```

## 6. Break a contract

Why keep the reading out of the rule? Try the other way: let the rule find the files
itself. Replace `src/kb_mcp/mirror/domain/count.py` with:

```python
"""How many documents the mirror holds of each source: a rule, without effects."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from kb_mcp.mirror.adapters.markdown import documents

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def per_source(docs: Path, sources: Iterable[str]) -> dict[str, int]:
    """Count the documents of each source, as their paths in the mirror name it.

    Each source named is counted, one without documents as 0.
    """
    found = Counter(path.relative_to(docs).parts[0] for path in documents(docs))
    return {source: found[source] for source in sources}
```

Then check the layout:

```bash
uv run lint-imports
```

It refuses the change, and names the import at fault, in each contract that it breaks:

```text
Contracts: 9 kept, 2 broken.
```

```text
kb_mcp.mirror.domain is not allowed to import kb_mcp.mirror.adapters:

- kb_mcp.mirror.domain.count -> kb_mcp.mirror.adapters.markdown (l.8)
```

A rule that reads files can be tested only with files, and changes whenever their
layout does. So the layers of a context may import only those below them, and a rule,
in any context, no effect. Put the rule back as step 4 wrote it, and run
`uv run lint-imports` again: `Contracts: 11 kept, 0 broken.`

## 7. Bring the reference up to date

Now the whole suite:

```bash
uv run pytest -n auto
```

One test fails, and its message says what to do:

```text
E       AssertionError: docs/reference/commands.md is not what the code generates: run uv run python -m tests.reference_pages
```

The run ends with:

```text
1 failed, <n> passed, <n> skipped in <time>
```

[The reference of commands](../reference/commands.md) is generated from the parser, and
`count` is not on it yet. Generate it again, as the message says:

```bash
uv run python -m tests.reference_pages
```

It says nothing, and rewrites the page. See what changed:

```bash
git diff --stat
```

```text
 docs/reference/commands.md | 24 ++++++++++++++++++++++++
 1 file changed, 24 insertions(+)
```

The page now lists `count` among the commands, with its help. Run the five checks of
step 2 again: each passes, the tests of `count` among them.

## 8. Put the change aside

```bash
git stash --include-untracked
```

The clone is as it was, and `git stash pop` brings `count` back.

## What you have done

You have written a test first, a rule without effects, a subcommand that reads through
an adapter, and seen Import Linter and the reference test each refuse what the code's
layout and its pages do not allow. From here:

- [Instructions for coding agents](../../AGENTS.md), which bind every change: the
  workflow, from a plan in `docs/work/plans/` to a merge, the checks, and the sandbox.
  A new subcommand also has its page under
  [telemetry](../reference/telemetry/README.md), changed with the code.
- [The roadmap](../work/README.md): the plans to come; those done are in
  [`changelog/`](../work/changelog/).
- [The code's layout](../explanation/code-layout.md), and
  [a walkthrough of the code](../explanation/code-walkthrough.md) of one refresh and one
  search.
- [Internals](../explanation/internals.md) and
  [trade-offs](../explanation/trade-offs.md): how the program works, and why so.

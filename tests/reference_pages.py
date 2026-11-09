"""The reference pages that the code generates: its commands, and its settings.

``uv run python -m tests.reference_pages`` writes ``docs/reference/commands.md`` and
``docs/reference/settings.md`` whole, the first from the command's parser, the second
from the settings' model; ``tests/test_reference.py`` fails while either page differs
from what this module gives. Reference "can be generated automatically by the software
it describes" (https://diataxis.fr/reference/): the code is then its one source, and a
page cannot fall behind it unseen.

Each page is the same, byte for byte, on every machine: help is formatted 88 columns
wide, without colour, in a scratch home, which is then written ``~``, and the
platform's folder of logs ``<log directory>``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, override
from unittest.mock import patch

from kb_mcp.cli.main import parser
from kb_mcp.config.adapters.settings_file import SETTINGS_PATH
from kb_mcp.config.domain.settings import NESTING, PREFIX, setting_paths, variable
from kb_mcp.kernel.exit_status import MEANINGS
from kb_mcp.kernel.names import PROGRAM
from kb_mcp.observability.adapters.logs import default_log_folder
from tests.composed import MODEL

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).parents[1]
REFERENCE = ROOT / "docs" / "reference"
REGENERATE = "uv run python -m tests.reference_pages"
# How help is formatted for the pages: its width, and no colour, as argparse and Rich
# read these variables.
HELP_ENVIRONMENT = {"COLUMNS": "88", "PYTHON_COLORS": "0", "NO_COLOR": "1"}
# What Markdown would read as markup in a cell of a table, escaped so that it shows as
# written: a code span, emphasis, a tag, a link, a cell's end.
MARKUP = re.compile(r"([\\`*<\[\]|])")
# A type of a setting's JSON schema, by its format or its type, in the page's words.
TYPE_WORDS = {"string": "text", "password": "secret", "object": "table"}
# The variables that a run reads besides the settings' own, and what each does: written
# here, as no model holds them. ``tests/test_reference.py`` finds any other in ``src/``.
OTHER_VARIABLES = {
    "NO_COLOR": "Set, stderr and `--help` have no colour",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "`telemetry.endpoint`, in a layer below the settings"
    " file, shared with other programs; a value that the setting would refuse is ignored,"
    " and said to be",
    "OTEL_SDK_DISABLED": "`true` leaves `telemetry.endpoint` unset, above every layer:"
    " telemetry off",
}


class Walked(argparse.ArgumentParser):
    """A parser that keeps the action declaring its subcommands, if any.

    argparse holds the action privately, and gives each subcommand's parser the class of
    its parent, so that every parser of the command keeps its own.
    """

    subcommands: argparse._SubParsersAction[Walked] | None = None

    @override
    def add_subparsers(self, **keywords: Any) -> argparse._SubParsersAction[Walked]:
        """Declare subcommands as argparse does, and keep the action that declares them."""
        self.subcommands = super().add_subparsers(**keywords)
        return self.subcommands


def cell(text: str) -> str:
    """Write a text in a cell of a Markdown table, so that it shows as written."""
    return MARKUP.sub(r"\\\1", text)


def commands() -> str:
    """Give the page of the commands: the help of each, depth first, then the exit statuses.

    The parser declares every subcommand, as ``main`` builds it; each section is a
    parser's ``format_help()``, in the order of declaration.
    """
    with (
        tempfile.TemporaryDirectory() as home,
        patch.dict(os.environ, {**HELP_ENVIRONMENT, "HOME": home}),
    ):
        logs = str(default_log_folder())
        waiting: list[Walked] = [parser(Walked)]
        sections = []
        while waiting:
            command = waiting.pop(0)
            name = command.prog.removeprefix(f"{PROGRAM} ")
            sections.append(f"## `{name}`\n\n```text\n{command.format_help()}```\n")
            if command.subcommands is not None:
                waiting[:0] = command.subcommands.choices.values()
    statuses = "".join(
        f"| {status.value} | {cell(meaning)} |\n" for status, meaning in MEANINGS.items()
    )
    page = f"""# Commands

What the command says with `--help`, then each of its subcommands, and each step of one,
as the parser declares them; then the exit statuses. This page is generated from the
code by `{REGENERATE}`, and `tests/test_reference.py` fails
while it differs: change a subcommand's declaration in
[`cli/options/`](../../src/kb_mcp/cli/options/), then run that command;
never edit the page.

With no arguments, the command serves MCP on stdio, as `serve` does: that is how agents
start it ([`main`](../../src/kb_mcp/cli/main.py)). A flag that overrides
a setting does so for its run alone, the strongest of the layers that
[the settings](settings.md) describe. Help is shown here 88 columns wide and without
colour; `~` stands for the home directory, and `<log directory>` for the platform's
folder of logs.

{"\n".join(sections)}
## Exit statuses

Every command ends with one of these statuses, which
[`MEANINGS`](../../src/kb_mcp/kernel/exit_status.py) defines once, for
`--help` and for this page.

| Status | Meaning |
|---|---|
{statuses}"""
    return page.replace(logs, "<log directory>").replace(home, "~")


def typed(schema: dict[str, Any], definitions: dict[str, Any]) -> str:
    """Name the type that a setting's JSON schema gives, in words, unset aside."""
    if "$ref" in schema:
        return typed(definitions[schema["$ref"].rpartition("/")[2]], definitions)
    if "anyOf" in schema:
        branches = [branch for branch in schema["anyOf"] if branch != {"type": "null"}]
        return " or ".join(typed(branch, definitions) for branch in branches)
    if "enum" in schema:
        return "one of " + ", ".join(f"`{value}`" for value in schema["enum"])
    if schema["type"] == "array":
        return f"list of {typed(schema['items'], definitions)}"
    word = schema.get("format", schema["type"])
    return TYPE_WORDS.get(word, word)


def settings() -> str:
    """Give the page of the settings: how they are named and layered, then one row each.

    A row is a setting that holds a value, nested tables flattened, in the order of the
    model that the entry composes from the registry: its key, its variable, then its
    type, default and description as the model's JSON schema gives them, so that no
    Python representation shows. A default that a factory computes shows as computed.
    Raises ValueError naming a setting without a description.
    """
    schema = MODEL.model_json_schema()
    definitions = schema.get("$defs", {})
    rows = []
    for path, kind in setting_paths(MODEL).items():
        if kind == "table":
            continue
        model = schema
        for name in path[:-1]:
            model = definitions[model["properties"][name]["$ref"].rpartition("/")[2]]
        field = model["properties"][path[-1]]
        key = ".".join(path)
        if not field.get("description"):
            message = f"{key}: no description; give its Field one, then run {REGENERATE}"
            raise ValueError(message)
        if "default" not in field:
            default = "computed"
        elif field["default"] is None:
            default = "unset"
        else:
            default = f"`{json.dumps(field['default']).replace('|', r'\|')}`"
        rows.append(
            f"| `{key}` | `{variable(path)}` | {typed(field, definitions)} | {default}"
            f" | {cell(field['description'])} |\n"
        )
    return f"""# Settings

Every setting of the command: how each is named, which layer wins, then a row per
setting; then the variables that a run reads besides. This page is generated from the
settings' model,
[`Settings`](../../src/kb_mcp/config/domain/settings.py),
by `{REGENERATE}`, and `tests/test_reference.py` fails while
it differs: change a setting's `Field` and its description, then run that command;
never edit the page.

## Precedence and naming

A run takes each setting from the strongest layer that gives it. From the weakest: its
default; the settings file; the environment; the flags of the run. A stronger layer's
value replaces a weaker one's whole, a list included, as
[`settings_of`](../../src/kb_mcp/config/domain/settings.py) merges them;
`check --summary detailed` names the layer that gave each setting.

- **The settings file** is TOML: `{SETTINGS_PATH}`, unless
  `--config` names another; a missing file holds no settings. A key with dots, such as
  `sources.confluence.spaces`, is the key `spaces` of the table `[sources.confluence]`.
  The file may not hold a key that names no setting, nor a secret.
- **The environment** names each setting by a variable: `{PREFIX}`, then
  the setting's key in capitals, each dot written `{NESTING}`. A list is a JSON array, and
  a table, which a variable of its own may give whole, a JSON object. An empty variable
  is ignored, as is one of the prefix that names no setting; two that set one setting,
  such as a table's and one of its settings', are refused. A secret is read from its
  variable alone.
- **A flag**, such as `--data-dir`, overrides its setting for its run alone;
  [the commands](commands.md) list each command's flags.

A path that starts with `~` starts in the home directory.

## Settings

| Key | Variable | Type | Default | Description |
|---|---|---|---|---|
{"".join(rows)}
## Variables read besides the settings

| Variable | Effect |
|---|---|
{"".join(f"| `{name}` | {effect} |\n" for name, effect in OTHER_VARIABLES.items())}
A run takes every other `OTEL_` variable out of its environment as it starts, before
OpenTelemetry reads any
([`READ`](../../src/kb_mcp/observability/__init__.py)); the reference of
[telemetry](telemetry/README.md#settings-and-variables) says why.

The libraries that a run uses read variables of their own, which no test finds; these
change what a run does:

- `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY`, unless `NO_PROXY` names the host, as
  httpx reads them: the site's requests go through that proxy, and so do those to an
  embedding endpoint off this machine; one on it, and telemetry, ignore them. On macOS,
  with none set, Python reads the system's proxy settings instead.
  [Credentials](../explanation/credentials.md#on-the-wire) says what a proxy sees.
- `XDG_STATE_HOME`, on Linux: the log folder is under it, as platformdirs places it.
- `COLUMNS`, `FORCE_COLOR`, `PYTHON_COLORS` and `TERM`, among others: the width and the
  colours of `--help`, as argparse reads them, and of stderr, as Rich does.
"""


# Each page by its file's name in docs/reference/, and what gives it.
PAGES: dict[str, Callable[[], str]] = {"commands.md": commands, "settings.md": settings}

if __name__ == "__main__":
    for name, page in PAGES.items():
        (REFERENCE / name).write_text(page(), encoding="utf-8")

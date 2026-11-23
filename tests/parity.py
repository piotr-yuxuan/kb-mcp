"""What the program offers, which ``tests/fixtures/parity.json`` holds so that none is lost.

``uv run python -m tests.parity`` writes the manifest whole, an object of five sorted
lists: ``commands``, each as its help names it; ``options``, each option string,
positional, as ``<dest>``, and choice of each command, from the parser as
``tests.reference_pages`` walks it; ``settings``, each setting's key and its variable,
from the model as the settings page is made; ``mcp``, each tool with its parameters, an
object's keys among them, one level down, and each prompt with its arguments, as a
server started as agents start it lists them; and
``telemetry``, each event, span and instrument that the hand-written pages of
``docs/reference/telemetry/`` list. ``tests/test_parity.py`` fails when the code offers
less than the manifest holds; an entry leaves it only by a decision that the user
approves.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.client.stdio import StdioServerParameters

from kb_mcp.cli.main import parser
from kb_mcp.config.settings import setting_paths, variable
from kb_mcp.kernel.names import PROGRAM
from tests.composed import MODEL
from tests.reference import README, documented, operations
from tests.reference_pages import Walked
from tests.test_serve import talk

if TYPE_CHECKING:
    import argparse

MANIFEST = Path(__file__).parent / "fixtures" / "parity.json"


class Listed(Walked):
    """A parser walked as the reference's is, which gives the actions declared on it."""

    def declared(self) -> list[argparse.Action]:
        """Give each option and positional declared on it, its groups' included, in order."""
        return self._actions


def offered(home: Path) -> dict[str, list[str]]:
    """Give what the program offers now, by kind, each list sorted.

    The server starts in ``home``, a scratch folder that holds no settings.
    """
    commands, options = [], []
    waiting: list[Listed] = [parser(Listed)]
    while waiting:
        command = waiting.pop()
        name = command.prog.removeprefix(f"{PROGRAM} ")
        commands.append(name)
        for action in command.declared():
            if action is command.subcommands:
                continue  # its choices are the subcommands, each a command of its own
            labels = action.option_strings or [f"<{action.dest}>"]
            options += [f"{name} {label}" for label in labels]
            options += [f"{name} {labels[-1]} {choice}" for choice in action.choices or ()]
        if command.subcommands is not None:
            waiting += command.subcommands.choices.values()
    server = StdioServerParameters(
        command=sys.executable, args=["-m", "kb_mcp"], env={"HOME": str(home)}
    )
    _, listed, _ = talk(server, [])
    tools = []
    for tool in listed["tools"]:
        schema = tool["inputSchema"]
        definitions = schema.get("$defs", {})
        tools.append(f"tool {tool['name']}")
        for key, parameter in schema.get("properties", {}).items():
            tools.append(f"tool {tool['name']} {key}")
            # An object's keys, one level down, its schema in a union or behind a $ref.
            shapes = [
                definitions[shape["$ref"].rpartition("/")[2]] if "$ref" in shape else shape
                for shape in [parameter, *parameter.get("anyOf", [])]
            ]
            tools += [
                f"tool {tool['name']} {key} {field}"
                for shape in shapes
                for field in shape.get("properties", {})
            ]
    pages = documented(README, *operations())
    found = {
        "commands": commands,
        "options": options,
        "settings": [
            f"{'.'.join(path)} {variable(path)}"
            for path, kind in setting_paths(MODEL).items()
            if kind != "table"
        ],
        "mcp": [
            *tools,
            *(
                f"prompt {prompt['name']}{named}"
                for prompt in listed["prompts"]
                for named in ["", *(f" {each['name']}" for each in prompt.get("arguments", []))]
            ),
        ],
        "telemetry": [
            *(f"event {name}" for name in pages.events),
            *(f"span {name}" for name in pages.spans),
            *(f"instrument {name}" for name in pages.instruments),
        ],
    }
    return {kind: sorted(set(entries)) for kind, entries in found.items()}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as scratch:
        text = json.dumps(offered(Path(scratch)), indent=1)
    MANIFEST.write_text(f"{text}\n", encoding="utf-8")

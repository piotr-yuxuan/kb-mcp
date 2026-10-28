"""What the server says, as a client over stdio sees it: tools, instructions, prompts (019).

The default serves five tools; ``--tools`` serves some of them, and what the server
says then names none that it does not serve.
"""

from __future__ import annotations

import json
import re
import sys
from typing import TYPE_CHECKING

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp_types import TextContent

from atlassian_offline_mcp.cli.main import main
from atlassian_offline_mcp.mcp.app.tools import Library
from atlassian_offline_mcp.search.app.indexing import build_index
from tests.answers import estimate
from tests.mirrors import MOMENT, fillers, issue, page, write

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture
    from mcp_types import GetPromptResult, ListPromptsResult, ListToolsResult

ORDER = ["ask", "search", "read", "browse", "status"]
WITHOUT_ASK = "search,read,browse,status"
INSTRUCTIONS = 2048  # characters that older Claude Code keeps
STANDING = 2400  # estimated tokens of the instructions and the tool listing together
ASK_DESCRIPTION = 600  # characters of ask's description
ASK_SENTENCES = 240  # characters that name ask in the instructions and search's description
INVALID_PARAMS = -32602
REFUSED = 2
NAMES_ASK = re.compile(r"\bask\b")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Make a scratch home whose settings name a data directory with an index by words."""
    home, data = tmp_path / "home", tmp_path / "data"
    (home / ".config" / "atlassian-offline-mcp").mkdir(parents=True)
    settings = home / ".config" / "atlassian-offline-mcp" / "config.toml"
    settings.write_text(f"data_dir = {json.dumps(str(data))}\n", encoding="utf-8")
    fillers(data / "docs")
    write(data / "docs", page("196845", "Kafka retention", space="ENG"))
    write(data / "docs", issue("PROJ-7", "Kafka upgrade"))
    build_index(data / "docs", data / "index.sqlite", MOMENT)
    return home


type Seen = tuple[str, ListToolsResult, ListPromptsResult]


def seen(home: Path, *options: str) -> Seen:
    """Start ``serve`` with these options as an agent would; give what it lists."""
    found: list[Seen] = []

    async def session() -> None:
        command = StdioServerParameters(
            command=sys.executable,
            args=["-m", "atlassian_offline_mcp", "serve", *options],
            env={"HOME": str(home)},
        )
        async with Client(command) as client:
            found.append(
                (client.instructions or "", await client.list_tools(), await client.list_prompts())
            )

    anyio.run(session)
    return found[0]


def prompted(home: Path, name: str, arguments: dict[str, str]) -> GetPromptResult | MCPError:
    """Get a prompt from the default server; give its result, or the error it answered."""
    found: list[GetPromptResult | MCPError] = []

    async def session() -> None:
        command = StdioServerParameters(
            command=sys.executable, args=["-m", "atlassian_offline_mcp"], env={"HOME": str(home)}
        )
        async with Client(command) as client:
            try:
                found.append(await client.get_prompt(name, arguments))
            except MCPError as error:
                found.append(error)

    anyio.run(session)
    return found[0]


def test_five_tools_in_order_within_the_standing_budget(home: Path) -> None:
    """Read-only, no output schema; instructions and listing within their budgets."""
    instructions, tools, _ = seen(home)
    listed = tools.tools
    assert [tool.name for tool in listed] == ORDER
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in listed)
    assert [tool.name for tool in listed if tool.output_schema is not None] == []
    assert len(instructions) <= INSTRUCTIONS
    sent = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in listed]
    assert estimate(instructions + json.dumps(sent)) <= STANDING
    descriptions = {tool.name: tool.description or "" for tool in listed}
    assert len(descriptions["ask"]) <= ASK_DESCRIPTION
    about_ask = [s for s in re.split(r"(?<=[.;:])\s", instructions) if NAMES_ASK.search(s)]
    about_ask += [s for s in descriptions["search"].split("\n") if NAMES_ASK.search(s)]
    assert 0 < len(" ".join(about_ask)) <= ASK_SENTENCES


def test_the_filters_of_search_and_ask_have_no_titles(home: Path) -> None:
    """Each filter by its name alone: a title would repeat it in every request."""
    _, tools, _ = seen(home)
    listed = {tool.name: tool.input_schema["$defs"]["SearchFilters"] for tool in tools.tools[:2]}
    assert list(listed) == ["ask", "search"]
    names = [
        *("source", "space", "project", "status", "label", "issue_type"),
        *("author", "creator", "assignee", "commenter"),
        *("updated_after", "updated_before", "created_after", "created_before"),
        *("commented_after", "commented_before"),
    ]
    for filters in listed.values():
        assert list(filters["properties"]) == names
        assert [name for name, each in filters["properties"].items() if "title" in each] == []


def test_without_ask_nothing_names_it_and_descriptions_are_the_docstrings(home: Path) -> None:
    """Four tools whose descriptions are their methods' docstrings, as the SDK takes them."""
    instructions, tools, _ = seen(home, "--tools", WITHOUT_ASK)
    listed = tools.tools
    assert [tool.name for tool in listed] == ORDER[1:]
    assert {tool.name: tool.description for tool in listed} == {
        name: getattr(Library, name).__doc__ for name in ORDER[1:]
    }
    sent = json.dumps([tool.model_dump(mode="json", by_alias=True) for tool in listed])
    assert not NAMES_ASK.search(instructions)
    assert not NAMES_ASK.search(sent)


def test_tools_named_in_any_order_are_served_in_the_server_s(home: Path) -> None:
    """``status,read`` serves read, then status; the instructions name those two alone."""
    instructions, tools, _ = seen(home, "--tools", "status,read")
    assert [tool.name for tool in tools.tools] == ["read", "status"]
    assert "status says what is mirrored" in instructions
    assert "search finds" not in instructions


def test_an_unknown_tool_exits_2_offering_the_names(capsys: CaptureFixture[str]) -> None:
    """The parser refuses it before anything runs, naming every tool."""
    with pytest.raises(SystemExit) as stopped:
        main(["serve", "--tools", "search,grep"])
    assert stopped.value.code == REFUSED
    assert "ask, search, read, browse, status" in capsys.readouterr().err


def test_a_prompt_is_listed_only_when_its_tools_are_served(home: Path) -> None:
    """Three prompts with every tool; without read, brief and overview go."""
    _, _, prompts = seen(home)
    assert [prompt.name for prompt in prompts.prompts] == ["brief", "changes", "overview"]
    assert all(
        argument.required and " " not in argument.name
        for prompt in prompts.prompts
        for argument in prompt.arguments or []
    )
    _, _, fewer = seen(home, "--tools", "search,browse,status")
    assert [prompt.name for prompt in fewer.prompts] == ["changes"]


@pytest.mark.parametrize(
    ("name", "arguments", "canonical", "given"),
    [
        ("brief", {"ref": "proj-7"}, ['read(ref="jira/PROJ/PROJ-7.md")'], ["proj-7"]),
        (
            "changes",
            {"scope": "space:eng", "since": "2026-10-01"},
            ["the space ENG", '"updated_after": "2026-10-01T00:00:00+00:00"'],
            ["space:eng", "eng"],
        ),
        ("overview", {"scope": "project:proj"}, ['browse(project="PROJ")'], ["proj"]),
    ],
)
def test_a_prompt_is_one_user_message_of_canonical_values(
    home: Path, name: str, arguments: dict[str, str], canonical: list[str], given: list[str]
) -> None:
    """What the index holds enters the text; what was typed, otherwise spelt, does not."""
    result = prompted(home, name, arguments)
    assert not isinstance(result, MCPError)
    (message,) = result.messages
    assert message.role == "user"
    assert isinstance(message.content, TextContent)
    text = message.content.text
    assert all(each in text for each in canonical)
    assert not any(re.search(rf"(?<![\w/-]){re.escape(each)}(?![\w-])", text) for each in given)


@pytest.mark.parametrize(
    ("name", "arguments", "named"),
    [
        ("brief", {"ref": "999999"}, "ref: not mirrored"),
        ("overview", {"scope": "space:NOPE"}, "scope: space: no document has"),
        ("overview", {"scope": "ENG"}, "scope: space:ENG or project:ENG"),
        ("changes", {"scope": "space:ENG", "since": "last week"}, "since: an ISO 8601 date"),
    ],
)
def test_a_refused_argument_is_invalid_params_naming_it(
    home: Path, name: str, arguments: dict[str, str], named: str
) -> None:
    """JSON-RPC error -32602, its message naming the argument at fault."""
    result = prompted(home, name, arguments)
    assert isinstance(result, MCPError)
    assert result.code == INVALID_PARAMS
    assert result.message.startswith(named)

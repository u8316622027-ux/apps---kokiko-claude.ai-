"""Keep the public connector examples executable against the MCP contract."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.interfaces.mcp import server as mcp_server
from app.interfaces.mcp.tool_registry import create_tool_registry


@pytest.mark.parametrize("language", ["ru", "ro"])
def test_readme_search_example_uses_supported_read_only_tool(language: str) -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    examples = [json.loads(block) for block in re.findall(r"```json\s*(.*?)```", readme, re.S)]
    request = next(
        example for example in examples if example["params"]["arguments"]["language"] == language
    )
    tool = create_tool_registry()[request["params"]["name"]]
    arguments = request["params"]["arguments"]

    assert request["jsonrpc"] == "2.0"
    assert request["method"] == "tools/call"
    assert set(tool.input_schema["required"]) <= arguments.keys()
    assert arguments.keys() <= tool.input_schema["properties"].keys()
    assert isinstance(arguments["query"], str) and arguments["query"].strip()
    assert isinstance(arguments["limit"], int) and arguments["limit"] >= 1
    assert tool.annotations["readOnlyHint"] is True
    assert tool.annotations["destructiveHint"] is False

    def search_fixture(supplied: dict[str, Any]) -> dict[str, Any]:
        assert supplied == arguments
        return {"query": supplied["query"], "language": supplied["language"], "products": []}

    response = mcp_server.handle_rpc_request(
        request, registry={tool.name: replace(tool, handler=search_fixture)}
    )
    assert not response["result"].get("isError", False)
    assert response["result"]["structuredContent"]["query"] == arguments["query"]
    assert response["result"]["structuredContent"]["language"] == language

"""Tests for tool descriptor metadata."""

from __future__ import annotations

import pytest

from app.interfaces.mcp import server as mcp_server
from app.interfaces.mcp import tool_registry


def test_tool_descriptor_includes_ui_meta_for_widget() -> None:
    registry = tool_registry.create_tool_registry()
    payload = tool_registry.serialize_tool_definition(registry["search_products"])

    assert payload["outputTemplate"] == "ui://widget/products.html"
    assert payload["_meta"]["openai/outputTemplate"] == "ui://widget/products.html"
    assert payload["_meta"]["ui"]["resourceUri"] == "ui://widget/products.html"
    assert payload["_meta"]["ui"]["visibility"] == ["model", "app"]
    assert payload["_meta"]["openai/widgetDomain"]
    assert payload["_meta"]["openai/widgetCSP"]["connect_domains"]
    assert payload["_meta"]["openai/widgetCSP"]["resource_domains"]


def test_tool_descriptor_includes_invocation_messages() -> None:
    registry = tool_registry.create_tool_registry()
    payload = tool_registry.serialize_tool_definition(registry["search_products"])

    assert payload["_meta"]["openai/toolInvocation/invoking"]
    assert payload["_meta"]["openai/toolInvocation/invoked"]


def test_tool_descriptor_annotations() -> None:
    registry = tool_registry.create_tool_registry()
    payload = tool_registry.serialize_tool_definition(registry["search_products"])
    assert payload["annotations"]["readOnlyHint"] is True
    assert payload["annotations"]["openWorldHint"] is True
    assert payload["annotations"]["destructiveHint"] is False


def test_theme_tool_is_removed() -> None:
    registry = tool_registry.create_tool_registry()
    assert "set_widget_theme" not in registry


def test_widget_ui_config_includes_resource_and_connect_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_WIDGET_DOMAIN", "https://widgets.example")
    mcp_server._reset_server_caches_for_tests()

    registry = tool_registry.create_tool_registry()
    ui_config = registry["search_products"].ui
    csp = ui_config["csp"]

    assert "https://widgets.example" in csp["resourceDomains"]
    assert "https://api.apteka.md" in csp["connectDomains"]
    assert "https://cdn.jsdelivr.net" not in csp["resourceDomains"]


def test_resources_list_uses_snakecase_csp_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_WIDGET_DOMAIN", "https://widgets.example")
    mcp_server._reset_server_caches_for_tests()

    response = mcp_server.handle_rpc_request(
        {"jsonrpc": "2.0", "id": "1", "method": "resources/list"}
    )

    resource_meta = response["result"]["resources"][0]["_meta"]
    widget_csp = resource_meta["openai/widgetCSP"]

    assert "connect_domains" in widget_csp
    assert "resource_domains" in widget_csp


def test_resources_list_includes_mcp_ui_meta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_WIDGET_DOMAIN", "https://widgets.example")
    mcp_server._reset_server_caches_for_tests()

    response = mcp_server.handle_rpc_request(
        {"jsonrpc": "2.0", "id": "1", "method": "resources/list"}
    )

    resource_meta = response["result"]["resources"][0]["_meta"]
    ui_meta = resource_meta["ui"]

    assert ui_meta["domain"] == "https://widgets.example"
    assert ui_meta["prefersBorder"] is True
    assert "https://api.apteka.md" in ui_meta["csp"]["connectDomains"]
    assert "https://widgets.example" in ui_meta["csp"]["resourceDomains"]


def test_initialize_advertises_mcp_ui_extension() -> None:
    response = mcp_server.handle_rpc_request({"jsonrpc": "2.0", "id": "1", "method": "initialize"})

    capabilities = response["result"]["capabilities"]
    assert capabilities["extensions"]["io.modelcontextprotocol/ui"]["mimeTypes"] == [
        "text/html;profile=mcp-app"
    ]

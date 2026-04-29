"""Tests for MCP server helpers and request handling."""

from __future__ import annotations

import http.client
import json
import threading
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

import pytest

from app.interfaces.mcp import server as mcp_server
from app.interfaces.mcp import tool_registry


def test_create_tool_registry_uses_base_handlers() -> None:
    base_registry = tool_registry.create_tool_registry()
    server_registry = mcp_server.create_tool_registry()

    for name in ("search_products",):
        assert server_registry[name].handler is base_registry[name].handler


def test_resolve_widget_page_varies_by_tool() -> None:
    assert tool_registry._resolve_widget_page("search_products") == "search"
    assert tool_registry._resolve_widget_page("unknown_tool") == "default"


def test_inline_local_widget_assets_inlines_local_files() -> None:
    base_temp = Path(__file__).resolve().parent / ".tmp"
    base_temp.mkdir(parents=True, exist_ok=True)
    widget_dir = base_temp / f"widget-{uuid4().hex}"
    styles_dir = widget_dir / "styles"
    scripts_dir = widget_dir / "scripts"
    styles_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)

    css_text = ".hello{color:red;}"
    js_text = "console.log('hello');"
    (styles_dir / "widget.css").write_text(css_text, encoding="utf-8")
    (scripts_dir / "widget.js").write_text(js_text, encoding="utf-8")

    html = (
        '<link rel="stylesheet" href="./styles/widget.css" />\n'
        '<script src="./scripts/widget.js"></script>\n'
        '<link rel="stylesheet" href="../secrets.css" />\n'
    )

    result = mcp_server._inline_local_widget_assets(html, widget_dir=widget_dir)

    assert css_text in result
    assert js_text in result
    assert "../secrets.css" in result


def test_build_widget_html_escapes_script_tag() -> None:
    payload = {"name": "Тест</script><script>alert(1)//", "price": 99}
    result = mcp_server._build_widget_html_with_data("ui://widget/products.html", payload)
    # When the widget HTML exists the injected JSON must not contain raw </script>
    if result is not None:
        assert (
            "</script>" not in result.split("window.__MCP_TOOL_RESULT__=")[1].split(";</script>")[0]
        )


def test_handle_rpc_request_tool_error_omits_http_request_id() -> None:
    def _boom(_: dict[str, object]) -> dict[str, object]:
        raise ValueError("boom")

    registry = {
        "demo": tool_registry.ToolDefinition(
            name="demo",
            description="demo",
            input_schema={"type": "object", "properties": {}},
            handler=_boom,
            output_template="",
            ui={},
        )
    }

    response = mcp_server.handle_rpc_request(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "demo", "arguments": {}},
        },
        registry=registry,
        http_request_id="req-123",
    )

    error_payload = response["result"]["structuredContent"]["error"]
    assert "http_request_id" not in error_payload


def test_handle_jsonrpc_payload_notification_returns_none() -> None:
    response = mcp_server.handle_jsonrpc_payload({"jsonrpc": "2.0", "method": "initialize"})

    assert response is None


def test_tools_list_cache_refreshes_after_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_WIDGET_DOMAIN", "https://example-a.test")
    mcp_server._reset_server_caches_for_tests()
    first = mcp_server._get_default_tools_list_payload()

    monkeypatch.setenv("MCP_WIDGET_DOMAIN", "https://example-b.test")
    mcp_server._reset_server_caches_for_tests()
    second = mcp_server._get_default_tools_list_payload()

    assert first != second
    assert second["tools"][0]["ui"]["domain"] == "https://example-b.test"


def test_build_access_log_message_sanitizes_user_agent() -> None:
    user_agent = "Test/1.0\r\nWith-Newline " + ("x" * 200)
    message = mcp_server._build_access_log_message(
        method="POST",
        path="/mcp",
        status_code=200,
        latency_ms=3.5,
        client_ip="127.0.0.1",
        user_agent=user_agent,
        request_id="req-1",
    )

    assert "\n" not in message
    assert "\r" not in message
    assert "..." in message


def test_parse_content_length_rejects_missing() -> None:
    headers = {"Content-Type": "application/json"}

    with pytest.raises(ValueError, match="Content-Length"):
        mcp_server._parse_content_length(headers)


def _start_mcp_server() -> tuple[mcp_server.ThreadingHTTPServer, threading.Thread, str, int]:
    server = mcp_server.ThreadingHTTPServer(("127.0.0.1", 0), mcp_server.MCPHttpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, thread, str(host), int(port)


def _stop_mcp_server(server: mcp_server.ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=1.0)
    server.server_close()


def _http_request(
    *, host: str, port: int, method: str, path: str
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection(host, port, timeout=2.0)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        return response.status, headers, body
    finally:
        connection.close()


def test_handle_jsonrpc_payload_logs_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[object, object]] = []

    def _capture(request_payload: object, response_payload: object) -> None:
        captured.append((request_payload, response_payload))

    monkeypatch.setattr(mcp_server, "_log_mcp_request_safe", _capture)
    registry = {
        "search_products": tool_registry.ToolDefinition(
            name="search_products",
            description="demo",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda _: {"products": []},
            output_template="",
            ui={},
        )
    }
    request_payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "tools/call",
        "params": {"name": "search_products", "arguments": {"query": "aspirin"}},
    }

    response = mcp_server.handle_jsonrpc_payload(request_payload, registry=registry)

    assert captured == [(request_payload, response)]


def test_get_mcp_returns_method_not_allowed() -> None:
    server, thread, host, port = _start_mcp_server()
    try:
        status, headers, body = _http_request(host=host, port=port, method="GET", path="/mcp")
    finally:
        _stop_mcp_server(server, thread)

    assert status == HTTPStatus.METHOD_NOT_ALLOWED
    assert headers.get("Allow") == "POST"
    payload = json.loads(body.decode("utf-8"))
    assert payload["error"]["code"] == -32600
    assert "stateless" in payload["error"]["message"].lower()


def test_delete_mcp_returns_method_not_allowed() -> None:
    server, thread, host, port = _start_mcp_server()
    try:
        status, headers, body = _http_request(host=host, port=port, method="DELETE", path="/mcp")
    finally:
        _stop_mcp_server(server, thread)

    assert status == HTTPStatus.METHOD_NOT_ALLOWED
    assert headers.get("Allow") == "POST"
    payload = json.loads(body.decode("utf-8"))
    assert payload["error"]["code"] == -32600


def test_get_health_still_returns_ok() -> None:
    server, thread, host, port = _start_mcp_server()
    try:
        status, _headers, body = _http_request(host=host, port=port, method="GET", path="/health")
    finally:
        _stop_mcp_server(server, thread)

    assert status == HTTPStatus.OK
    payload = json.loads(body.decode("utf-8"))
    assert payload == {"status": "ok"}


def test_log_mcp_request_safe_includes_error_message(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _boom(*_: object, **__: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(mcp_server, "log_mcp_request", _boom)
    caplog.set_level("WARNING")

    mcp_server._log_mcp_request_safe({"jsonrpc": "2.0"}, {"ok": True})

    assert "mcp_request_log_failed" in caplog.text
    assert "boom" in caplog.text


@pytest.mark.parametrize(
    ("request_payload", "should_log"),
    [
        ({"jsonrpc": "2.0", "id": "1", "method": "initialize"}, False),
        (
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {"name": "search_products", "arguments": {"query": ""}},
            },
            False,
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {"name": "search_products", "arguments": {"query": "help"}},
            },
            True,
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {"name": "unknown_tool", "arguments": {"query": "abc"}},
            },
            False,
        ),
    ],
)
def test_should_log_mcp_request_filters_tools(
    request_payload: dict[str, object], should_log: bool
) -> None:
    assert mcp_server._should_log_mcp_request(request_payload) is should_log

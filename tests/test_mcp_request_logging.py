"""Tests for MCP request logging."""

from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from app.interfaces.mcp.request_logging import SupabaseMcpRequestLogger


def test_supabase_mcp_request_logger_posts_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["data"] = request.data
        captured["headers"] = dict(request.header_items())

        class _Response:
            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                return False

            def read(self):  # type: ignore[no-untyped-def]
                return b"{}"

        return _Response()

    logger = SupabaseMcpRequestLogger(
        base_url="https://supabase.example",
        api_key="test-key",
        urlopen=_fake_urlopen,
    )

    logger.log_request({"method": "tools/list"}, {"result": {"tools": []}})

    assert captured["url"] == "https://supabase.example/rest/v1/mcp_request_logs2"
    assert captured["method"] == "POST"
    payload = json.loads(captured["data"])
    assert payload == [
        {
            "request_payload": {"method": "tools/list"},
            "response_payload": {"result": {"tools": []}},
        }
    ]
    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["apikey"] == "test-key"
    assert headers["authorization"] == "Bearer test-key"
    assert headers["content-type"] == "application/json"
    assert headers["prefer"] == "return=minimal"
    assert headers["user-agent"] == "Mozilla/5.0"


def test_supabase_mcp_request_logger_surfaces_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"message":"invalid token"}'),
        )

    logger = SupabaseMcpRequestLogger(
        base_url="https://supabase.example",
        api_key="bad-key",
        urlopen=_fake_urlopen,
    )

    with pytest.raises(RuntimeError, match="Supabase log failed: 401 Unauthorized"):
        logger.log_request({"method": "tools/list"}, {"result": {"tools": []}})

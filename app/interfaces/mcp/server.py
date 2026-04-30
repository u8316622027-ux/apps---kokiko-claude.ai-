"""Minimal MCP HTTP server with tool registration."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic as _monotonic
from time import perf_counter as _perf_counter
from typing import Any, Mapping
from uuid import uuid4

from app.core.config import get_settings
from app.interfaces.mcp.request_logging import log_mcp_request
from app.interfaces.mcp.tool_registry import (
    ToolDefinition,
    decorate_tool_result,
    serialize_tool_definition,
)
from app.interfaces.mcp.tool_registry import (
    create_tool_registry as _create_tool_registry_base,
)

MAX_REQUEST_BODY_BYTES = 1024 * 1024
MIN_GZIP_BYTES = 512
TOOL_RESPONSE_CACHE_TTL_SECONDS = 30.0
TOOL_RESPONSE_CACHE_MAX_ENTRIES = 256
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())
_WIDGET_CSS_LINK_PATTERN = re.compile(
    r"""<link\s+[^>]*?href=(["'])(\./[^"']+?\.css)\1[^>]*?>""",
    flags=re.IGNORECASE,
)
_WIDGET_SCRIPT_SRC_PATTERN = re.compile(
    r"""<script\s+[^>]*?src=(["'])(\./[^"']+?\.js)\1[^>]*?>\s*</script>""",
    flags=re.IGNORECASE,
)
_TOOL_RESPONSE_CACHE_LOCK = threading.Lock()
_TOOL_RESPONSE_CACHE: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_RUNTIME_METRICS_LOCK = threading.Lock()
_RUNTIME_METRICS: dict[str, Any] = {
    "rpc_requests_total": 0,
    "tool_calls_total": 0,
    "tool_errors_total": 0,
    "cache_hits_total": 0,
    "cache_misses_total": 0,
    "tools": {},
}


def create_tool_registry() -> dict[str, ToolDefinition]:
    return _create_tool_registry_base()


@lru_cache(maxsize=1)
def _get_default_tool_registry() -> dict[str, ToolDefinition]:
    return create_tool_registry()


@lru_cache(maxsize=1)
def _get_default_tools_list_payload() -> dict[str, Any]:
    registry = _get_default_tool_registry()
    return {"tools": [serialize_tool_definition(tool) for tool in registry.values()]}


def _reset_server_caches_for_tests() -> None:
    get_settings.cache_clear()
    _get_default_tool_registry.cache_clear()
    _get_default_tools_list_payload.cache_clear()
    _widget_resource_index.cache_clear()
    _get_tool_cache_config.cache_clear()
    with _TOOL_RESPONSE_CACHE_LOCK:
        _TOOL_RESPONSE_CACHE.clear()


def _reset_runtime_metrics_for_tests() -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS["rpc_requests_total"] = 0
        _RUNTIME_METRICS["tool_calls_total"] = 0
        _RUNTIME_METRICS["tool_errors_total"] = 0
        _RUNTIME_METRICS["cache_hits_total"] = 0
        _RUNTIME_METRICS["cache_misses_total"] = 0
        _RUNTIME_METRICS["tools"] = {}


def get_runtime_metrics() -> dict[str, Any]:
    with _RUNTIME_METRICS_LOCK:
        tools_snapshot: dict[str, dict[str, Any]] = {}
        tools = _RUNTIME_METRICS.get("tools", {})
        for tool_name, payload in tools.items():
            calls = int(payload.get("calls", 0))
            latency_total_ms = float(payload.get("latency_total_ms", 0.0))
            avg_latency_ms = (latency_total_ms / calls) if calls > 0 else 0.0
            tools_snapshot[tool_name] = {
                "calls": calls,
                "errors": int(payload.get("errors", 0)),
                "avg_latency_ms": round(avg_latency_ms, 3),
            }
        return {
            "rpc_requests_total": int(_RUNTIME_METRICS["rpc_requests_total"]),
            "tool_calls_total": int(_RUNTIME_METRICS["tool_calls_total"]),
            "tool_errors_total": int(_RUNTIME_METRICS["tool_errors_total"]),
            "cache_hits_total": int(_RUNTIME_METRICS["cache_hits_total"]),
            "cache_misses_total": int(_RUNTIME_METRICS["cache_misses_total"]),
            "tools": tools_snapshot,
        }


def _record_rpc_request() -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS["rpc_requests_total"] = int(_RUNTIME_METRICS["rpc_requests_total"]) + 1


def _record_tool_result(
    tool_name: str, *, latency_ms: float, errored: bool, cache_hit: bool | None = None
) -> None:
    with _RUNTIME_METRICS_LOCK:
        _RUNTIME_METRICS["tool_calls_total"] = int(_RUNTIME_METRICS["tool_calls_total"]) + 1
        if errored:
            _RUNTIME_METRICS["tool_errors_total"] = int(_RUNTIME_METRICS["tool_errors_total"]) + 1
        if cache_hit is True:
            _RUNTIME_METRICS["cache_hits_total"] = int(_RUNTIME_METRICS["cache_hits_total"]) + 1
        if cache_hit is False:
            _RUNTIME_METRICS["cache_misses_total"] = int(_RUNTIME_METRICS["cache_misses_total"]) + 1

        tools = _RUNTIME_METRICS.setdefault("tools", {})
        tool_payload = tools.setdefault(
            tool_name,
            {"calls": 0, "errors": 0, "latency_total_ms": 0.0},
        )
        tool_payload["calls"] = int(tool_payload.get("calls", 0)) + 1
        if errored:
            tool_payload["errors"] = int(tool_payload.get("errors", 0)) + 1
        tool_payload["latency_total_ms"] = (
            float(tool_payload.get("latency_total_ms", 0.0)) + latency_ms
        )


def handle_rpc_request(
    request_payload: dict[str, Any],
    *,
    registry: dict[str, ToolDefinition] | None = None,
    http_request_id: str | None = None,
) -> dict[str, Any]:
    """Handle a single JSON-RPC request."""

    if not isinstance(request_payload, dict):
        return _rpc_error(None, -32600, "Invalid Request")
    _record_rpc_request()

    active_registry = registry or _get_default_tool_registry()
    request_id = request_payload.get("id")
    method = request_payload.get("method")
    raw_params = request_payload.get("params")
    if raw_params is None:
        params: dict[str, Any] = {}
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        return _rpc_error(request_id, -32602, "Invalid params: params must be an object")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "extensions": {
                        "io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}
                    },
                },
                "serverInfo": {"name": "apteka-mcp", "version": "0.1.0"},
            },
        }

    if method == "resources/list":
        resources = []
        for uri, resource_data in _widget_resource_index().items():
            relative_path = str(resource_data["path"])
            description = str(resource_data["description"])
            ui_domain = str(resource_data["domain"])
            resource_domains = list(resource_data["resource_domains"])
            connect_domains = list(resource_data["connect_domains"])
            resources.append(
                {
                    "uri": uri,
                    "name": relative_path,
                    "mimeType": "text/html;profile=mcp-app",
                    "description": description,
                    "_meta": {
                        "ui": {
                            "csp": {
                                "connectDomains": connect_domains,
                                "resourceDomains": resource_domains,
                            },
                            **(
                                {
                                    "domain": ui_domain,
                                }
                                if ui_domain
                                else {}
                            ),
                            "prefersBorder": bool(resource_data["prefers_border"]),
                        },
                        "openai/widgetDescription": description,
                        "openai/widgetDomain": ui_domain,
                        "openai/widgetCSP": {
                            "connect_domains": connect_domains,
                            "resource_domains": resource_domains,
                        },
                    },
                }
            )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"resources": resources},
        }

    if method == "resources/read":
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            return _rpc_error(request_id, -32602, "Invalid params: uri must be a non-empty string")

        resource_index = _widget_resource_index()
        normalized_uri = uri.strip()
        resource_data = resource_index.get(normalized_uri)
        if resource_data is None:
            return _rpc_error(request_id, -32602, f"Resource not found: {normalized_uri}")

        relative_path = str(resource_data["path"])
        file_path = Path(__file__).resolve().parents[2] / "widgets" / relative_path
        try:
            html_text = file_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _rpc_error(request_id, -32602, f"Resource not found: {normalized_uri}")
        html_text = _inline_local_widget_assets(html_text, widget_dir=file_path.parent)

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [
                    {
                        "uri": normalized_uri,
                        "mimeType": "text/html;profile=mcp-app",
                        "text": html_text,
                        "_meta": {
                            "ui": {
                                "csp": {
                                    "connectDomains": list(resource_data["connect_domains"]),
                                    "resourceDomains": list(resource_data["resource_domains"]),
                                },
                                **(
                                    {
                                        "domain": str(resource_data["domain"]),
                                    }
                                    if resource_data.get("domain")
                                    else {}
                                ),
                                "prefersBorder": bool(resource_data["prefers_border"]),
                            },
                            "openai/widgetDescription": str(resource_data["description"]),
                            "openai/widgetDomain": str(resource_data["domain"]),
                            "openai/widgetCSP": {
                                "connect_domains": list(resource_data["connect_domains"]),
                                "resource_domains": list(resource_data["resource_domains"]),
                            },
                        },
                    }
                ]
            },
        }

    if method == "tools/list":
        if registry is None:
            tools_result = _get_default_tools_list_payload()
        else:
            tools_result = {
                "tools": [serialize_tool_definition(tool) for tool in active_registry.values()]
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": tools_result,
        }

    if method == "tools/call":
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name.strip():
            return _rpc_error(request_id, -32602, "Invalid params: name must be a non-empty string")

        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _rpc_error(request_id, -32602, "Invalid params: arguments must be an object")

        tool = active_registry.get(tool_name)
        if tool is None:
            return _rpc_error(request_id, -32601, f"Tool not found: {tool_name}")

        resolved_arguments = arguments

        validation_error = _validate_input_schema(resolved_arguments, tool.input_schema)
        if validation_error is not None:
            return _rpc_error(request_id, -32602, f"Invalid params: {validation_error}")

        cache_ttl_seconds = _get_tool_cache_ttl_seconds(tool_name)
        cache_key = _build_tool_cache_key(tool_name, resolved_arguments)
        started_at = _perf_counter()
        if cache_ttl_seconds is not None and cache_key is not None:
            cached_payload = _get_cached_tool_payload(cache_key)
            if cached_payload is not None:
                structured_payload = decorate_tool_result(tool_name, tool, cached_payload)
                _record_tool_result(
                    tool_name,
                    latency_ms=(_perf_counter() - started_at) * 1000.0,
                    errored=False,
                    cache_hit=True,
                )
                return _build_tool_result_response(request_id, tool_name, tool, structured_payload)

        try:
            result_payload = tool.handler(resolved_arguments)
            structured_payload = decorate_tool_result(tool_name, tool, result_payload)
            if cache_ttl_seconds is not None and cache_key is not None:
                _set_cached_tool_payload(
                    cache_key,
                    structured_payload,
                    ttl_seconds=cache_ttl_seconds,
                )
            _record_tool_result(
                tool_name,
                latency_ms=(_perf_counter() - started_at) * 1000.0,
                errored=False,
                cache_hit=False if cache_key is not None else None,
            )
            return _build_tool_result_response(request_id, tool_name, tool, structured_payload)
        except Exception as exc:  # noqa: BLE001
            _record_tool_result(
                tool_name,
                latency_ms=(_perf_counter() - started_at) * 1000.0,
                errored=True,
                cache_hit=False if cache_key is not None else None,
            )
            error_payload = _classify_tool_error(exc)
            logger.error(
                "mcp_tool_call_failed",
                extra={
                    "http_request_id": http_request_id,
                    "rpc_request_id": request_id,
                    "tool_name": tool_name,
                    "error_type": error_payload["type"],
                    "retriable": error_payload["retriable"],
                },
                exc_info=False,
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "structuredContent": {
                        "error": {
                            "type": error_payload["type"],
                            "message": error_payload["message"],
                            "retriable": error_payload["retriable"],
                            "request_id": request_id,
                        }
                    },
                    "isError": True,
                },
            }

    return _rpc_error(request_id, -32601, f"Method not found: {method}")


def handle_jsonrpc_payload(
    request_payload: Any,
    *,
    registry: dict[str, ToolDefinition] | None = None,
    http_request_id: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Handle single or batch JSON-RPC payload and support notifications."""

    if isinstance(request_payload, list):
        if not request_payload:
            return _rpc_error(None, -32600, "Invalid Request")

        responses: list[dict[str, Any]] = []
        for item in request_payload:
            if isinstance(item, dict) and "id" not in item:
                handle_rpc_request(item, registry=registry, http_request_id=http_request_id)
                if _should_log_mcp_request(item):
                    _log_mcp_request_safe(item, None)
                continue

            response_payload = handle_rpc_request(
                item, registry=registry, http_request_id=http_request_id
            )
            if _should_log_mcp_request(item):
                _log_mcp_request_safe(item, response_payload)
            responses.append(response_payload)

        return responses or None

    if isinstance(request_payload, dict) and "id" not in request_payload:
        handle_rpc_request(request_payload, registry=registry, http_request_id=http_request_id)
        if _should_log_mcp_request(request_payload):
            _log_mcp_request_safe(request_payload, None)
        return None

    response = handle_rpc_request(
        request_payload, registry=registry, http_request_id=http_request_id
    )
    if _should_log_mcp_request(request_payload):
        _log_mcp_request_safe(request_payload, response)
    return response


def _should_log_mcp_request(request_payload: Any) -> bool:
    if not isinstance(request_payload, dict):
        return False
    if request_payload.get("method") != "tools/call":
        return False
    params = request_payload.get("params")
    if not isinstance(params, dict):
        return False
    tool_name = params.get("name")
    if tool_name != "search_products":
        return False
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        return False
    query = arguments.get("query")
    if not isinstance(query, str):
        return False
    return bool(query.strip())


def _log_mcp_request_safe(request_payload: Any, response_payload: Any) -> None:
    try:
        log_mcp_request(request_payload, response_payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_request_log_failed: %s", exc, exc_info=False)


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@lru_cache(maxsize=1)
def _widget_resource_index() -> dict[str, dict[str, Any]]:
    registry = _get_default_tool_registry()
    mapping: dict[str, dict[str, Any]] = {}
    for tool in registry.values():
        uri = tool.output_template.strip()
        if not uri.startswith("ui://widget/"):
            continue
        relative_path = uri.removeprefix("ui://widget/").strip()
        if not relative_path:
            continue
        ui_domain = str(tool.ui.get("domain") or "").strip()
        csp = tool.ui.get("csp") if isinstance(tool.ui.get("csp"), dict) else {}
        resource_domains = csp.get("resourceDomains")
        if not isinstance(resource_domains, list):
            resource_domains = []
        connect_domains = csp.get("connectDomains")
        if not isinstance(connect_domains, list):
            connect_domains = []
        normalized_resource_domains = [
            str(domain).strip() for domain in resource_domains if str(domain).strip()
        ]
        normalized_connect_domains = [
            str(domain).strip() for domain in connect_domains if str(domain).strip()
        ]
        mapping.setdefault(
            uri,
            {
                "path": relative_path,
                "description": tool.description,
                "domain": ui_domain,
                "prefers_border": bool(tool.ui.get("prefersBorder", True)),
                "resource_domains": normalized_resource_domains,
                "connect_domains": normalized_connect_domains,
            },
        )
    return mapping


def _validate_input_schema(arguments: dict[str, Any], schema: dict[str, Any]) -> str | None:
    return _validate_value(arguments, schema, path="arguments")


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> str | None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"

        required = schema.get("required")
        if isinstance(required, list):
            for field_name in required:
                if isinstance(field_name, str) and field_name not in value:
                    return f"{path}.{field_name} is required"

        properties = schema.get("properties")
        if isinstance(properties, dict):
            for field_name, field_schema in properties.items():
                if field_name not in value or not isinstance(field_schema, dict):
                    continue
                nested_error = _validate_value(
                    value[field_name],
                    field_schema,
                    path=f"{path}.{field_name}",
                )
                if nested_error is not None:
                    return nested_error

        any_of = schema.get("anyOf")
        if isinstance(any_of, list) and any_of:
            if not any(_matches_schema_variant(value, item) for item in any_of):
                return f"{path} must satisfy at least one anyOf schema"
        return None

    if expected_type == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                nested_error = _validate_value(item, item_schema, path=f"{path}[{index}]")
                if nested_error is not None:
                    return nested_error
        return None

    if expected_type == "string":
        if not isinstance(value, str):
            return f"{path} must be a string"

    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{path} must be an integer"
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            return f"{path} must be greater than or equal to {minimum}"

    if expected_type == "boolean":
        if not isinstance(value, bool):
            return f"{path} must be a boolean"

    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return f"{path} must be one of {enum}"

    return None


def _matches_schema_variant(value: dict[str, Any], schema_variant: Any) -> bool:
    if not isinstance(schema_variant, dict):
        return False
    required = schema_variant.get("required")
    if isinstance(required, list):
        for field_name in required:
            if isinstance(field_name, str) and field_name not in value:
                return False
    return True


def _is_json_content_type(content_type: str | None) -> bool:
    if content_type is None:
        return False
    mime_type = content_type.split(";", 1)[0].strip().lower()
    return mime_type == "application/json"


def _classify_tool_error(exc: Exception) -> dict[str, Any]:
    message = str(exc).strip() or exc.__class__.__name__
    if isinstance(exc, TimeoutError):
        return {"type": "timeout_error", "message": message, "retriable": True}
    if isinstance(exc, ConnectionError):
        return {"type": "connection_error", "message": message, "retriable": True}
    if isinstance(exc, ValueError):
        return {"type": "validation_error", "message": message, "retriable": False}
    return {"type": "tool_execution_error", "message": message, "retriable": False}


def _build_tool_cache_key(tool_name: str, arguments: dict[str, Any]) -> str | None:
    cache_policy = _get_tool_cache_config()["ttl_by_tool_name"]
    if tool_name not in cache_policy:
        return None
    encoded_args = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{tool_name}:{encoded_args}"


def _get_tool_cache_ttl_seconds(tool_name: str) -> float | None:
    ttl_seconds = _get_tool_cache_config()["ttl_by_tool_name"].get(tool_name)
    if ttl_seconds is None or ttl_seconds <= 0:
        return None
    return ttl_seconds


@lru_cache(maxsize=1)
def _get_tool_cache_config() -> dict[str, Any]:
    settings = get_settings()
    search_ttl = float(
        getattr(settings, "mcp_search_cache_ttl_seconds", TOOL_RESPONSE_CACHE_TTL_SECONDS)
    )
    max_entries = int(
        getattr(settings, "mcp_tool_cache_max_entries", TOOL_RESPONSE_CACHE_MAX_ENTRIES)
    )
    if search_ttl <= 0:
        search_ttl = TOOL_RESPONSE_CACHE_TTL_SECONDS
    if max_entries <= 0:
        max_entries = TOOL_RESPONSE_CACHE_MAX_ENTRIES
    return {
        "ttl_by_tool_name": {
            "search_products": search_ttl,
        },
        "max_entries": max_entries,
    }


def _get_cached_tool_payload(cache_key: str) -> dict[str, Any] | None:
    now = _monotonic()
    with _TOOL_RESPONSE_CACHE_LOCK:
        record = _TOOL_RESPONSE_CACHE.get(cache_key)
        if record is None:
            return None
        expires_at, payload = record
        if now >= expires_at:
            _TOOL_RESPONSE_CACHE.pop(cache_key, None)
            return None
        _TOOL_RESPONSE_CACHE.move_to_end(cache_key)
        return payload


def _set_cached_tool_payload(
    cache_key: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: float,
) -> None:
    expires_at = _monotonic() + ttl_seconds
    with _TOOL_RESPONSE_CACHE_LOCK:
        if cache_key in _TOOL_RESPONSE_CACHE:
            _TOOL_RESPONSE_CACHE.move_to_end(cache_key)
        _TOOL_RESPONSE_CACHE[cache_key] = (expires_at, payload)
        max_entries = int(_get_tool_cache_config()["max_entries"])
        while len(_TOOL_RESPONSE_CACHE) > max_entries:
            _TOOL_RESPONSE_CACHE.popitem(last=False)


def _build_tool_result_response(
    request_id: Any,
    tool_name: str,
    tool: ToolDefinition,
    structured_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build a compact tool/call result response."""
    success_text = _build_tool_success_text(tool_name, structured_payload)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": success_text}],
            "structuredContent": structured_payload,
            "isError": False,
        },
    }


def _build_tool_success_text(tool_name: str, structured_payload: dict[str, Any]) -> str:
    if tool_name == "search_products":
        products = structured_payload.get("products")
        if not isinstance(products, list) or not products:
            return "No products found."
        language = str(structured_payload.get("language") or "ru").strip().lower()
        prefer_ro = language.startswith("ro")
        lines = [f"Found {len(products)} products:"]
        for product in products:
            if not isinstance(product, dict):
                continue
            if prefer_ro:
                name = str(product.get("name_ro") or product.get("name_ru") or product.get("name") or "").strip()
                slug = str(product.get("slug_ro") or product.get("slug_ru") or "").strip()
            else:
                name = str(product.get("name_ru") or product.get("name_ro") or product.get("name") or "").strip()
                slug = str(product.get("slug_ru") or product.get("slug_ro") or "").strip()
            if not name:
                continue
            discount_price = product.get("discount_price") or product.get("discountPrice")
            price = product.get("price")
            if discount_price is not None:
                try:
                    price_display = f"{float(discount_price):.2f} MDL"
                except (TypeError, ValueError):
                    price_display = ""
            elif price is not None:
                try:
                    price_display = f"{float(price):.2f} MDL"
                except (TypeError, ValueError):
                    price_display = ""
            else:
                price_display = ""
            manufacturer = str(product.get("manufacturer") or "").strip()
            country = str(product.get("country") or "").strip()
            parts = [f"- {name}"]
            if price_display:
                parts.append(f"— {price_display}")
            if manufacturer:
                parts.append(f"| {manufacturer}")
            if country:
                parts.append(f"| {country}")
            if slug:
                parts.append(f"| slug: {slug}")
            lines.append(" ".join(parts))
        return "\n".join(lines)
    return "Tool call completed successfully."


def _build_widget_html_with_data(
    template_uri: str, structured_payload: dict[str, Any]
) -> str | None:
    """Load widget HTML, inline assets, and inject structured data as a script tag."""
    resource_index = _widget_resource_index()
    resource_data = resource_index.get(template_uri.strip())
    if resource_data is None:
        return None
    relative_path = str(resource_data["path"])
    file_path = Path(__file__).resolve().parents[2] / "widgets" / relative_path
    try:
        html_text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    html_text = _inline_local_widget_assets(html_text, widget_dir=file_path.parent)
    data_json = json.dumps(structured_payload, ensure_ascii=False, separators=(",", ":"))
    # Escape </script> so the inline script tag cannot be prematurely closed by
    # data values that contain the literal string "</script>".
    data_json = data_json.replace("</", "<\\/")
    injection = f"<script>window.__MCP_TOOL_RESULT__={data_json};</script>"
    if "</head>" in html_text:
        html_text = html_text.replace("</head>", f"{injection}</head>", 1)
    else:
        html_text = injection + html_text
    return html_text


def _inline_local_widget_assets(html_text: str, *, widget_dir: Path) -> str:
    def _read_local_asset(relative_path: str) -> str | None:
        normalized_path = Path(relative_path)
        if normalized_path.is_absolute():
            return None
        if any(part in {"..", ""} for part in normalized_path.parts):
            return None
        candidate = (widget_dir / normalized_path).resolve()
        widget_root = widget_dir.resolve()
        if candidate == widget_root or widget_root not in candidate.parents:
            return None
        try:
            return candidate.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    def _replace_css(match: re.Match[str]) -> str:
        asset_text = _read_local_asset(match.group(2))
        if asset_text is None:
            return match.group(0)
        return f"<style>\n{asset_text}\n</style>"

    def _replace_js(match: re.Match[str]) -> str:
        asset_text = _read_local_asset(match.group(2))
        if asset_text is None:
            return match.group(0)
        return f"<script>\n{asset_text}\n</script>"

    with_inlined_css = _WIDGET_CSS_LINK_PATTERN.sub(_replace_css, html_text)
    return _WIDGET_SCRIPT_SRC_PATTERN.sub(_replace_js, with_inlined_css)


def _sanitize_user_agent(user_agent: str) -> str:
    cleaned = re.sub(r"[\r\n\t]+", " ", user_agent).strip()
    max_length = 120
    if len(cleaned) > max_length:
        return f"{cleaned[:max_length]}..."
    return cleaned


def _parse_content_length(headers: Mapping[str, str]) -> int:
    transfer_encoding = str(headers.get("Transfer-Encoding") or "").lower()
    if "chunked" in transfer_encoding:
        raise ValueError("Unsupported Transfer-Encoding: chunked")
    raw_length = headers.get("Content-Length")
    if raw_length is None:
        raise ValueError("Missing Content-Length header")
    try:
        content_length = int(raw_length)
    except ValueError as exc:
        raise ValueError("Invalid Content-Length header") from exc
    if content_length < 0:
        raise ValueError("Content-Length must be non-negative")
    return content_length


def _resolve_http_request_id(incoming_request_id: str | None) -> str:
    if incoming_request_id is None:
        return uuid4().hex
    normalized = incoming_request_id.strip()
    if normalized:
        return normalized
    return uuid4().hex


def _build_access_log_message(
    *,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    client_ip: str,
    user_agent: str,
    request_id: str,
) -> str:
    safe_user_agent = _sanitize_user_agent(user_agent)
    return (
        f"[REQ] {method} {path} -> {status_code} | {latency_ms:.2f} ms | "
        f"ip={client_ip} | ua={safe_user_agent} | id={request_id}"
    )


class MCPHttpHandler(BaseHTTPRequestHandler):
    """HTTP transport for minimal MCP JSON-RPC methods."""

    server_version = "AptekaMCP/0.1"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        started_at = _perf_counter()
        request_id = _resolve_http_request_id(self.headers.get("X-Request-Id"))
        if self.path == "/health":
            self._send_json({"status": "ok"}, request_id=request_id)
            self._log_access(
                request_id=request_id, status_code=HTTPStatus.OK, started_at=started_at
            )
            return
        if self.path == "/metrics":
            self._send_json(get_runtime_metrics(), request_id=request_id)
            self._log_access(
                request_id=request_id, status_code=HTTPStatus.OK, started_at=started_at
            )
            return
        if self.path == "/mcp":
            self._send_method_not_allowed(request_id=request_id, allow="POST")
            self._log_access(
                request_id=request_id,
                status_code=HTTPStatus.METHOD_NOT_ALLOWED,
                started_at=started_at,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)
        self._log_access(
            request_id=request_id, status_code=HTTPStatus.NOT_FOUND, started_at=started_at
        )

    def do_DELETE(self) -> None:  # noqa: N802
        started_at = _perf_counter()
        request_id = _resolve_http_request_id(self.headers.get("X-Request-Id"))
        if self.path == "/mcp":
            self._send_method_not_allowed(request_id=request_id, allow="POST")
            self._log_access(
                request_id=request_id,
                status_code=HTTPStatus.METHOD_NOT_ALLOWED,
                started_at=started_at,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)
        self._log_access(
            request_id=request_id, status_code=HTTPStatus.NOT_FOUND, started_at=started_at
        )

    def do_POST(self) -> None:  # noqa: N802
        started_at = _perf_counter()
        request_id = _resolve_http_request_id(self.headers.get("X-Request-Id"))
        if self.path != "/mcp":
            self.send_error(HTTPStatus.NOT_FOUND)
            self._log_access(
                request_id=request_id, status_code=HTTPStatus.NOT_FOUND, started_at=started_at
            )
            return

        if not _is_json_content_type(self.headers.get("Content-Type")):
            self._send_json(
                _rpc_error(None, -32600, "Invalid Request: Content-Type must be application/json"),
                status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                request_id=request_id,
            )
            self._log_access(
                request_id=request_id,
                status_code=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                started_at=started_at,
            )
            return

        try:
            content_length = _parse_content_length(self.headers)
            if content_length > MAX_REQUEST_BODY_BYTES:
                self._send_json(
                    _rpc_error(None, -32600, "Invalid Request: body is too large"),
                    status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    request_id=request_id,
                )
                self._log_access(
                    request_id=request_id,
                    status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    started_at=started_at,
                )
                return

            raw_body = self.rfile.read(content_length)
            request_payload = json.loads(raw_body.decode("utf-8"))
            response_payload = handle_jsonrpc_payload(request_payload, http_request_id=request_id)
            if response_payload is None:
                self.send_response(HTTPStatus.NO_CONTENT)
                self.send_header("X-Request-Id", request_id)
                self.end_headers()
                self._log_access(
                    request_id=request_id, status_code=HTTPStatus.NO_CONTENT, started_at=started_at
                )
                return
            self._send_json(response_payload, request_id=request_id)
            self._log_access(
                request_id=request_id, status_code=HTTPStatus.OK, started_at=started_at
            )
        except ValueError as exc:
            error_message = str(exc)
            status = HTTPStatus.BAD_REQUEST
            if "Missing Content-Length" in error_message:
                status = HTTPStatus.LENGTH_REQUIRED
            self._send_json(
                _rpc_error(None, -32600, f"Invalid Request: {error_message}"),
                status=status,
                request_id=request_id,
            )
            self._log_access(request_id=request_id, status_code=status, started_at=started_at)
        except json.JSONDecodeError:
            self._send_json(
                _rpc_error(None, -32700, "Parse error"),
                status=HTTPStatus.BAD_REQUEST,
                request_id=request_id,
            )
            self._log_access(
                request_id=request_id, status_code=HTTPStatus.BAD_REQUEST, started_at=started_at
            )

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep server output concise in local development.
        return

    def _send_json(
        self,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        status: HTTPStatus = HTTPStatus.OK,
        request_id: str | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        should_compress = self._should_use_gzip(len(encoded))
        if should_compress:
            encoded = gzip.compress(encoded, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if should_compress:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        if request_id:
            self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_method_not_allowed(self, *, request_id: str, allow: str) -> None:
        payload = _rpc_error(None, -32600, "Method not allowed: server operates in stateless mode")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Allow", allow)
        self.send_header("X-Request-Id", request_id)
        self.end_headers()
        self.wfile.write(encoded)

    def _should_use_gzip(self, payload_size: int) -> bool:
        if payload_size < MIN_GZIP_BYTES:
            return False
        accept_encoding = str(self.headers.get("Accept-Encoding") or "").lower()
        return "gzip" in accept_encoding

    def _log_access(self, *, request_id: str, status_code: HTTPStatus, started_at: float) -> None:
        latency_ms = (_perf_counter() - started_at) * 1000.0
        client_host = str(self.client_address[0]) if self.client_address else ""
        client_port = int(self.client_address[1]) if self.client_address else 0
        user_agent = _sanitize_user_agent(str(self.headers.get("User-Agent") or ""))
        message = _build_access_log_message(
            method=self.command,
            path=self.path,
            status_code=int(status_code),
            latency_ms=latency_ms,
            client_ip=client_host,
            user_agent=user_agent,
            request_id=request_id,
        )
        logger.info(
            message,
            extra={
                "request_id": request_id,
                "method": self.command,
                "path": self.path,
                "status_code": int(status_code),
                "latency_ms": round(latency_ms, 3),
                "client_ip": client_host,
                "client_port": client_port,
                "user_agent": user_agent,
            },
        )


def _configure_runtime_logging() -> None:
    raw_level = str(os.getenv("MCP_LOG_LEVEL", "INFO")).strip().upper()
    log_level = getattr(logging, raw_level, logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root_logger.setLevel(log_level)
    logger.setLevel(log_level)


def run_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run MCP HTTP server."""

    _configure_runtime_logging()
    server = ThreadingHTTPServer((host, port), MCPHttpHandler)
    print(f"MCP server started on http://{host}:{port}/mcp")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("MCP server stopped gracefully.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run minimal MCP HTTP server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()

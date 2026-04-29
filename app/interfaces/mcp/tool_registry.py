"""MCP tool registry and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.config import get_settings
from app.interfaces.mcp.tools.apteka_urls import get_apteka_base_url
from app.interfaces.mcp.tools.search_tools import search_products


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Metadata and callable for an MCP tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    output_template: str
    ui: dict[str, Any]
    title: str | None = None
    annotations: dict[str, Any] = field(default_factory=dict)
    tool_invocation: dict[str, str] = field(default_factory=dict)
    visibility: str = "public"


def create_tool_registry() -> dict[str, ToolDefinition]:
    """Create the default tool registry for MCP requests."""
    widget_ui_config = _build_widget_ui_config()

    return {
        "search_products": ToolDefinition(
            name="search_products",
            title="Search products",
            description=(
                "Search products by free-text query via Stage API. "
                "Args: query and optional limit. "
                "Returns structuredContent.products and structuredContent.no_results when empty."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1},
                    "language": {
                        "type": "string",
                        "description": "User language preference (ru or ro).",
                    },
                },
                "required": ["query"],
            },
            handler=_search_products_handler,
            output_template="ui://widget/products.html",
            ui=widget_ui_config,
            annotations={
                "readOnlyHint": True,
                "openWorldHint": True,
                "destructiveHint": False,
            },
            tool_invocation={
                "invoking": "Searching products...",
                "invoked": "Products found.",
            },
        ),
    }


def serialize_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    ui_domain = str(tool.ui.get("domain") or "").strip()
    ui_csp = tool.ui.get("csp") if isinstance(tool.ui.get("csp"), dict) else {}
    connect_domains = ui_csp.get("connectDomains")
    resource_domains = ui_csp.get("resourceDomains")
    if not isinstance(connect_domains, list):
        connect_domains = []
    if not isinstance(resource_domains, list):
        resource_domains = []
    payload = {
        "name": tool.name,
        "title": tool.title or tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
        "ui": tool.ui,
        "_meta": {
            "ui": {
                "resourceUri": tool.output_template,
                "visibility": ["model", "app"],
            },
            "openai/widgetDomain": ui_domain,
            "openai/widgetCSP": {
                "connect_domains": list(connect_domains),
                "resource_domains": list(resource_domains),
            },
        },
    }
    if tool.tool_invocation:
        if tool.tool_invocation.get("invoking"):
            payload["_meta"]["openai/toolInvocation/invoking"] = tool.tool_invocation["invoking"]
        if tool.tool_invocation.get("invoked"):
            payload["_meta"]["openai/toolInvocation/invoked"] = tool.tool_invocation["invoked"]
    if tool.output_template:
        payload["outputTemplate"] = tool.output_template
        payload["_meta"]["openai/outputTemplate"] = tool.output_template
    if tool.annotations:
        payload["annotations"] = dict(tool.annotations)
    return payload


def decorate_tool_result(
    tool_name: str, tool: ToolDefinition, result_payload: dict[str, Any]
) -> dict[str, Any]:
    payload = dict(result_payload)

    if tool_name == "search_products":
        products = payload.get("products")
        if isinstance(products, list):
            normalized_products = products
        else:
            normalized_products = []
        payload["products"] = normalized_products
        payload["no_results"] = len(normalized_products) == 0

    if tool.output_template:
        payload["widget"] = {
            "open": {
                "template": tool.output_template,
                "replace_previous": True,
                "page": _resolve_widget_page(tool_name),
            },
            "ui": tool.ui,
        }
    return payload


def _resolve_widget_page(tool_name: str) -> str:
    if tool_name == "search_products":
        return "search"
    return "default"


def _build_widget_ui_config() -> dict[str, Any]:
    settings = get_settings()
    widget_domain = (
        str(
            getattr(
                settings,
                "mcp_widget_domain",
                "https://subgerminal-yevette-lactogenic.ngrok-free.dev",
            )
        ).strip()
        or "https://subgerminal-yevette-lactogenic.ngrok-free.dev"
    )
    apteka_base_url = get_apteka_base_url()
    resource_domains = [
        widget_domain,
        apteka_base_url,
        "https://www.apteka.md",
    ]
    return {
        "domain": widget_domain,
        "prefersBorder": True,
        "csp": {
            "connectDomains": [apteka_base_url],
            "resourceDomains": resource_domains,
        },
    }


def _search_products_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query", ""))
    limit = int(arguments.get("limit", 10))
    language = arguments.get("language")
    return search_products(query, limit=limit, language=language)

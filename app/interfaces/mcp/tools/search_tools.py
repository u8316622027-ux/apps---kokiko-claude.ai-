"""MCP search tools."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.request import urlopen as default_urlopen

from app.domain.products.entities import ProductSummary
from app.domain.products.repository import ProductSearchRepository
from app.domain.products.service import ProductSearchService
from app.interfaces.mcp.tools.apteka_urls import build_front_url, get_apteka_base_url

APTEKA_SEARCH_PATH = "/search"
APTEKA_MARKET_HEADER_NAME = "market"
APTEKA_MARKET_HEADER_VALUE = "kokikomd"


class AptekaSearchRepository(ProductSearchRepository):
    """HTTP-backed repository for apteka product search."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
        urlopen: Callable[..., Any] = default_urlopen,
    ) -> None:
        self._base_url = (base_url or build_front_url(APTEKA_SEARCH_PATH)).strip()
        self._timeout = timeout
        self._urlopen = urlopen

    def search(self, query: str, limit: int | None = None) -> list[ProductSummary]:
        payload = json.dumps({"query": query}, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        request = Request(
            url=self._base_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                APTEKA_MARKET_HEADER_NAME: APTEKA_MARKET_HEADER_VALUE,
            },
        )
        with self._urlopen(request, timeout=self._timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))

        items = _extract_items(response_payload)
        if limit is not None:
            items = items[:limit]
        return [_map_product(item) for item in items]


def search_products(
    query: str,
    *,
    limit: int | None = None,
    language: str | None = None,
    repository: ProductSearchRepository | None = None,
) -> dict[str, Any]:
    """Tool entrypoint for product search."""

    effective_repository = repository or AptekaSearchRepository()
    normalized_language = _normalize_language(language) or "ru"
    service = ProductSearchService(effective_repository)
    try:
        products = service.search_products(query, limit=limit)
    except HTTPError as error:
        retryable = 500 <= int(error.code) < 600
        return {
            "query": query.strip(),
            "count": 0,
            "products": [],
            "api_base_url": get_apteka_base_url(),
            "language": normalized_language,
            "upstream_error": {
                "status_code": int(error.code),
                "retryable": retryable,
            },
        }
    except URLError:
        return {
            "query": query.strip(),
            "count": 0,
            "products": [],
            "api_base_url": get_apteka_base_url(),
            "language": normalized_language,
            "upstream_error": {
                "status_code": None,
                "retryable": True,
            },
        }
    return {
        "query": query.strip(),
        "count": len(products),
        "products": [
            _product_to_dict(product, language=normalized_language) for product in products
        ],
        "api_base_url": get_apteka_base_url(),
        "language": normalized_language,
    }


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("results", "items", "products"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("results", "items", "products"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _map_product(item: dict[str, Any]) -> ProductSummary:
    product_id = str(item.get("id") or item.get("product_id") or item.get("sku") or "")
    fallback_name = str(item.get("name") or item.get("title") or "")
    translations = item.get("translations") if isinstance(item.get("translations"), dict) else {}
    ro_translation = translations.get("ro") if isinstance(translations.get("ro"), dict) else {}
    ru_translation = translations.get("ru") if isinstance(translations.get("ru"), dict) else {}
    name_ro = ro_translation.get("name")
    name_ru = ru_translation.get("name")
    description_ro = ro_translation.get("description")
    description_ru = ru_translation.get("description")
    raw_description = item.get("description")

    manufacturer = item.get("manufacturer")
    international_name = item.get("internationalName") or item.get("international_name")
    country = item.get("country")

    raw_price = item.get("price")
    price: float | None
    if raw_price is None:
        price = None
    else:
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            price = None

    raw_discount_price = item.get("discountPrice") or item.get("discount_price")
    discount_price: float | None
    if raw_discount_price is None:
        discount_price = None
    else:
        try:
            discount_price = float(raw_discount_price)
        except (TypeError, ValueError):
            discount_price = None

    image_url = _extract_image_url(item)
    product_url = item.get("url") or item.get("product_url") or item.get("productUrl")
    slug_ro = None
    slug_ru = None
    meta = item.get("meta")
    if isinstance(meta, dict):
        meta_translations = meta.get("translations")
        if isinstance(meta_translations, dict):
            meta_ro = meta_translations.get("ro")
            meta_ru = meta_translations.get("ru")
            if isinstance(meta_ro, dict):
                slug_ro = (
                    meta_ro.get("slug") or meta_ro.get("product_slug") or meta_ro.get("productSlug")
                )
            if isinstance(meta_ru, dict):
                slug_ru = (
                    meta_ru.get("slug") or meta_ru.get("product_slug") or meta_ru.get("productSlug")
                )
    return ProductSummary(
        id=product_id,
        name_ro=str(name_ro) if name_ro else (fallback_name or None),
        name_ru=str(name_ru) if name_ru else (fallback_name or None),
        manufacturer=str(manufacturer) if manufacturer else None,
        international_name=str(international_name) if international_name else None,
        country=str(country) if country else None,
        price=price,
        discount_price=discount_price,
        description_ro=str(description_ro)
        if description_ro
        else (str(raw_description) if raw_description else None),
        description_ru=str(description_ru)
        if description_ru
        else (str(raw_description) if raw_description else None),
        image_url=str(image_url) if image_url else None,
        product_url=str(product_url) if product_url else None,
        slug_ro=str(slug_ro) if slug_ro else None,
        slug_ru=str(slug_ru) if slug_ru else None,
    )


def _product_to_dict(product: ProductSummary, *, language: str = "ru") -> dict[str, Any]:
    payload = asdict(product)
    payload.pop("description_ro", None)
    payload.pop("description_ru", None)
    normalized_language = _normalize_language(language) or "ru"
    if normalized_language == "ro":
        preferred_name = product.name_ro or product.name_ru
    else:
        preferred_name = product.name_ru or product.name_ro
    payload["name"] = preferred_name
    payload["internationalName"] = payload.pop("international_name")
    return payload


def _normalize_language(language: str | None) -> str:
    normalized = str(language or "").strip().lower()
    if normalized.startswith("ro"):
        return "ro"
    if normalized.startswith("ru"):
        return "ru"
    return ""


def _extract_image_url(item: dict[str, Any]) -> str | None:
    direct_candidates = ("image", "image_url", "picture", "photo", "thumbnail")
    for key in direct_candidates:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value

    meta = item.get("meta")
    if isinstance(meta, dict):
        for key in direct_candidates:
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value

    images = item.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, str) and image.strip():
                return image
            if isinstance(image, dict):
                for key in ("full", "preview", "url", "image", "src"):
                    value = image.get(key)
                    if isinstance(value, str) and value.strip():
                        return value

    return None

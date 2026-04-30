"""Tests for search tool slug mapping."""

from __future__ import annotations

import json

from app.interfaces.mcp.tools.search_tools import (
    AptekaSearchRepository,
    _map_product,
    _product_to_dict,
)


def test_search_tool_maps_slug_from_meta_translations() -> None:
    item = {
        "id": 20859,
        "name": "Citramon U comprimate 240 mg/30 mg/180 mg N10",
        "meta": {
            "translations": {
                "ro": {"slug": "citramon-u-comprimate-240-mg30-mg180-mg-n10-51433"},
                "ru": {"slug": "citramon-u-tab-24030180mg-n10-51433"},
            }
        },
    }

    product = _map_product(item)
    payload = _product_to_dict(product, language="ru")

    assert payload["slug_ro"] == "citramon-u-comprimate-240-mg30-mg180-mg-n10-51433"
    assert payload["slug_ru"] == "citramon-u-tab-24030180mg-n10-51433"


def test_search_tool_prefers_language_specific_name() -> None:
    item = {
        "id": 1,
        "name": "Fallback name",
        "translations": {
            "ro": {"name": "Nume romanesc"},
            "ru": {"name": "Русское название"},
        },
    }

    product = _map_product(item)

    payload_ru = _product_to_dict(product, language="ru")
    payload_ro = _product_to_dict(product, language="ro")

    assert payload_ru["name"] == "Русское название"
    assert payload_ro["name"] == "Nume romanesc"


def test_search_repository_sends_market_header() -> None:
    captured: dict[str, object] = {}

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout

        class _Response:
            def __enter__(self):  # type: ignore[no-untyped-def]
                return self

            def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
                return False

            def read(self):  # type: ignore[no-untyped-def]
                return json.dumps({"items": []}).encode("utf-8")

        return _Response()

    repository = AptekaSearchRepository(urlopen=_fake_urlopen)
    repository.search("test query")

    headers = {key.lower(): value for key, value in captured["headers"].items()}
    assert headers["content-type"] == "application/json"
    assert headers["market"] == "kokikomd"


def test_search_tool_omits_long_description_fields_from_tool_payload() -> None:
    item = {
        "id": 10,
        "name": "Fallback name",
        "translations": {
            "ru": {"name": "Русское имя", "description": "Очень длинное описание"},
            "ro": {"name": "Nume", "description": "Descriere lunga"},
        },
        "description": "Raw description",
    }

    product = _map_product(item)
    payload = _product_to_dict(product, language="ru")

    assert "description_ru" not in payload
    assert "description_ro" not in payload

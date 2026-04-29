"""Supabase-backed MCP request logging."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen as default_urlopen

from app.core.env import read_env_file_value

ENV_FILE_PATH = Path(__file__).resolve().parents[3] / ".env"
DEFAULT_TABLE_NAME = "mcp_request_logs2"


class SupabaseMcpRequestLogger:
    """Persist MCP requests and responses into Supabase."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        table_name: str = DEFAULT_TABLE_NAME,
        timeout: float = 5.0,
        urlopen: Callable[..., Any] = default_urlopen,
    ) -> None:
        self._base_url = (base_url or _read_env("SUPABASE_URL")).strip().rstrip("/")
        self._api_key = (
            api_key or _read_env("SUPABASE_KEY") or _read_env("SUPABASE_SERVICE_ROLE_KEY")
        ).strip()
        self._table_name = table_name.strip() or DEFAULT_TABLE_NAME
        self._timeout = timeout
        self._urlopen = urlopen

    def log_request(self, request_payload: Any, response_payload: Any) -> None:
        if not self._base_url:
            raise ValueError("SUPABASE_URL is not configured")
        if not self._api_key:
            raise ValueError("SUPABASE_KEY is not configured")

        payload = json.dumps(
            [
                {
                    "request_payload": request_payload,
                    "response_payload": response_payload,
                }
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            url=f"{self._base_url}/rest/v1/{self._table_name}",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Prefer": "return=minimal",
                "User-Agent": "Mozilla/5.0",
                "apikey": self._api_key,
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with self._urlopen(request, timeout=self._timeout) as _:
                return None
        except HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                error_body = ""
            message = f"Supabase log failed: {exc.code} {exc.reason}"
            if error_body:
                message = f"{message} {error_body}"
            raise RuntimeError(message) from exc


@lru_cache(maxsize=1)
def _get_default_logger() -> SupabaseMcpRequestLogger | None:
    base_url = _read_env("SUPABASE_URL").strip()
    api_key = _read_env("SUPABASE_KEY").strip() or _read_env("SUPABASE_SERVICE_ROLE_KEY").strip()
    if not base_url or not api_key:
        return None
    return SupabaseMcpRequestLogger(base_url=base_url, api_key=api_key)


def log_mcp_request(request_payload: Any, response_payload: Any) -> bool:
    logger = _get_default_logger()
    if logger is None:
        return False
    logger.log_request(request_payload, response_payload)
    return True


def _read_env(key: str) -> str:
    value = str(os.getenv(key, "")).strip()
    if value:
        return value
    return read_env_file_value(key, env_path=ENV_FILE_PATH).strip()

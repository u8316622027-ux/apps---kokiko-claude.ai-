"""Centralized application settings."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Typed application settings loaded from environment and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    redis_url: str = ""
    cart_token_ttl_seconds: int = Field(default=604800, gt=0)
    mcp_search_cache_ttl_seconds: float = Field(default=30.0, gt=0)
    mcp_tracking_cache_ttl_seconds: float = Field(default=10.0, gt=0)
    mcp_checkout_reference_cache_ttl_seconds: float = Field(default=300.0, gt=0)
    mcp_tool_cache_max_entries: int = Field(default=256, gt=0)
    mcp_widget_domain: str = ""


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached settings singleton for the running process."""

    return AppSettings()

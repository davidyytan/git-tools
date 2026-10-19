"""Anthropic endpoint, built-in model choices and the live ``/models`` overlay.

Claude is reached through Anthropic's OpenAI-compatible endpoint, so the chat
transport is the shared one and only the catalog call differs: ``GET
/v1/models`` is the native Models API, which wants the key as ``x-api-key``
and an ``anthropic-version`` header rather than Bearer auth, so this module
fetches with those (``fetch_catalog_sync``). The built-in list below is the
default and the fallback when the call cannot be made. Credentials are
entered by the user, never bundled.
"""

from __future__ import annotations

from .catalog import CatalogFetchResult, ModelCatalogEntry, fetch_model_catalog_sync

PROVIDER_ID = "anthropic"
BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-opus-5-5"
PROFILE = "anthropic"
ALIASES = ("claude",)

# The Models API refuses a request without a version header.
API_VERSION = "2023-06-01"
# It pages at 20 by default, newest first; ask for everything so older
# built-ins do not silently fall off the picker.
CATALOG_QUERY = "limit=1000"

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

# Picker order: the default leads; an existing profile's model is pinned first.
MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(id=DEFAULT_MODEL, display_name="Claude Opus 5.5"),
    ModelCatalogEntry(id="claude-sonnet-5-5", display_name="Claude Sonnet 5.5"),
    ModelCatalogEntry(id="claude-haiku-5-5", display_name="Claude Haiku 5.5"),
    ModelCatalogEntry(id="claude-fable-5-1", display_name="Claude Fable 5.1"),
)

_DISPLAY_NAMES = {entry.id: entry.display_name for entry in MODELS}


def catalog_headers(api_key: str) -> dict[str, str]:
    """The headers the native Models API wants beside the shared Bearer one."""
    headers = {"anthropic-version": API_VERSION}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def fetch_catalog_sync(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 4.0,
) -> CatalogFetchResult[ModelCatalogEntry]:
    """``GET /v1/models`` with Anthropic's own auth and version headers, unpaged."""
    return fetch_model_catalog_sync(
        base_url, api_key, timeout=timeout, headers=catalog_headers(api_key),
        query=CATALOG_QUERY,
    )


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return the built-in catalog in the picker-compatible result shape."""
    return CatalogFetchResult(entries=MODELS, source="live")


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Prefer the endpoint's own list; fall back to the built-in one.

    Live ids are kept verbatim (they are what the server routes), with the
    server's display names kept, the built-in ones overlaid where it sent
    none, and the default model pinned first. When the fetch failed the
    built-in list is returned with the live error carried along so the
    caller can say why.
    """
    if live.source == "live" and live.entries:
        named = [
            ModelCatalogEntry(
                id=entry.id,
                display_name=entry.display_name or _DISPLAY_NAMES.get(entry.id),
            )
            for entry in live.entries
        ]
        named.sort(key=lambda entry: entry.id != DEFAULT_MODEL)
        return CatalogFetchResult(
            entries=tuple(named), source="live", fetched_at=live.fetched_at,
        )
    return CatalogFetchResult(
        entries=MODELS,
        source="live",
        error_kind=live.error_kind,
        error=live.error,
        status=live.status,
    )


__all__ = [
    "ALIASES",
    "API_VERSION",
    "CATALOG_QUERY",
    "BASE_URL",
    "DEFAULT_MODEL",
    "MODELS",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "catalog",
    "catalog_headers",
    "fetch_catalog_sync",
    "resolve_catalog",
]

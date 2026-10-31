"""Anthropic endpoint and the live ``/models`` overlay.

Claude is reached through Anthropic's OpenAI-compatible endpoint, so the chat transport is the shared one and only the catalog call differs: ``GET /v1/models`` is the native Models API, which wants the key as ``x-api-key`` and an ``anthropic-version`` header rather than Bearer auth, so this module fetches with those (``fetch_catalog_sync``). Unavailable discovery produces no choices rather than a static replacement list. Credentials are entered by the user, never bundled.
"""

from __future__ import annotations

from dataclasses import replace

from .catalog import CatalogFetchResult, ModelCatalogEntry, fetch_model_catalog_sync

PROVIDER_ID = "anthropic"
BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-opus-5-5"
PROFILE = "anthropic"
ALIASES = ("claude",)

# The Models API refuses a request without a version header.
API_VERSION = "2023-06-01"
# It pages at 20 by default, newest first; request older discoverable IDs too.
CATALOG_QUERY = "limit=1000"

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

# Compatibility export only: live discovery is the sole source of picker choices.
MODELS: tuple[ModelCatalogEntry, ...] = ()

# Labels may decorate discovered IDs, but never introduce choices of their own.
_DISPLAY_NAMES = {
    DEFAULT_MODEL: "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-fable-5-1": "Claude Fable 5.1",
}


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
    """Return no choices before live discovery; defaults are not a catalog."""
    return CatalogFetchResult()


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Return only the endpoint's live choices, never a static replacement list.

    Live IDs and server display names are kept verbatim, with missing names overlaid only on discovered IDs and the default model pinned first only if present. Failed or unavailable discovery yields empty entries with the original fetch metadata.
    """
    if (
        live.source != "live"
        or live.error_kind is not None
        or live.error is not None
        or (live.status is not None and live.status >= 400)
    ):
        return replace(live, entries=())
    named = [
        ModelCatalogEntry(
            id=entry.id,
            display_name=entry.display_name or _DISPLAY_NAMES.get(entry.id),
        )
        for entry in live.entries
    ]
    named.sort(key=lambda entry: entry.id != DEFAULT_MODEL)
    return replace(live, entries=tuple(named))


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

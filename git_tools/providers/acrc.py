"""ACRC endpoint, built-in model choices and the live ``/models`` overlay.

VPN connectivity is managed externally. The picker asks the endpoint for its
current model list (``resolve_catalog``); the built-in list below is the
default and the fallback when that call cannot be made. Credentials are
entered by the user, never bundled.
"""

from __future__ import annotations

from .catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDER_ID = "acrc"
BASE_URL = "https://fmodel.ai.acrc.a-star.edu.sg/v1"
DEFAULT_MODEL = "deepseek-v4.1-flash"
PROFILE = "acrc"
ALIASES: tuple[str, ...] = ()

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

# Picker order: the default leads; an existing profile's model is pinned first.
MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(id=DEFAULT_MODEL, display_name="DeepSeek V4.1 Flash"),
    ModelCatalogEntry(id="glm-5-3-flash", display_name="GLM 5-3 Flash"),
    ModelCatalogEntry(id="mimo-v2.6-pro", display_name="MiMo V2.6 Pro"),
)

_DISPLAY_NAMES = {entry.id: entry.display_name for entry in MODELS}


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return the built-in catalog in the picker-compatible result shape."""
    return CatalogFetchResult(entries=MODELS, source="live")


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Prefer the endpoint's own list; fall back to the built-in one.

    Live ids are kept verbatim (they are what the server routes), with the
    built-in display names overlaid where the id matches and the default
    model pinned first. When the fetch failed the built-in list is returned
    with the live error carried along so the caller can say why.
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
    "BASE_URL",
    "DEFAULT_MODEL",
    "MODELS",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "catalog",
    "resolve_catalog",
]

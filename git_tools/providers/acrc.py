"""ACRC endpoint and the live ``/models`` overlay.

VPN connectivity is managed externally. The picker asks the endpoint for its current model list (``resolve_catalog``); unavailable discovery produces no choices rather than a static replacement list. Credentials are entered by the user, never bundled.
"""

from __future__ import annotations

from dataclasses import replace

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

# Compatibility export only: live discovery is the sole source of picker choices.
MODELS: tuple[ModelCatalogEntry, ...] = ()

# Labels may decorate discovered IDs, but never introduce choices of their own.
_DISPLAY_NAMES = {
    DEFAULT_MODEL: "DeepSeek V4.1 Flash",
    "glm-5-3-flash": "GLM 5-3 Flash",
    "mimo-v2.6-pro": "MiMo V2.6 Pro",
}


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return no choices before live discovery; defaults are not a catalog."""
    return CatalogFetchResult()


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Return only the endpoint's live choices, never a static replacement list.

    Live IDs are kept verbatim, with display names overlaid only on discovered IDs and the default model pinned first only if present. Failed or unavailable discovery yields empty entries with the original fetch metadata.
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
    "BASE_URL",
    "DEFAULT_MODEL",
    "MODELS",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "catalog",
    "resolve_catalog",
]

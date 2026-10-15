"""Copilot OpenAI-compatible proxy (run and authenticate it separately).

Nothing provider-specific to parse: the picker lists whatever its ``/models``
returns through the shared catalog fetch, with the one built-in below as the
default and the offline fallback. git-tools only: agent-cli has no Copilot
module, so this one follows the shape of its ``cliproxyapi``.
"""

from __future__ import annotations

from .catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDER_ID = "copilot"
BASE_URL = "http://127.0.0.1:4141/v1"
DEFAULT_MODEL = "gpt-4.1"
PROFILE = "copilot"
ALIASES: tuple[str, ...] = ()

# What a fresh profile is seeded with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

# Picker order: the default leads; an existing profile's model is pinned first.
MODELS: tuple[ModelCatalogEntry, ...] = (ModelCatalogEntry(id=DEFAULT_MODEL),)


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return the built-in catalog in the picker-compatible result shape."""
    return CatalogFetchResult(entries=MODELS, source="live")


__all__ = [
    "ALIASES",
    "BASE_URL",
    "DEFAULT_MODEL",
    "MODELS",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "catalog",
]

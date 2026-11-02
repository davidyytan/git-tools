"""Copilot OpenAI-compatible proxy (run and authenticate it separately).

Nothing provider-specific to parse: the picker lists whatever its ``/models`` returns through the shared catalog fetch, with no static replacement list when discovery is unavailable. The single profile default is not a catalog choice. git-tools only: agent-cli has no Copilot module, so this one follows the shape of its ``cliproxyapi``.
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

# Compatibility export only: live discovery is the sole source of picker choices.
MODELS: tuple[ModelCatalogEntry, ...] = ()


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return no choices before live discovery; defaults are not a catalog."""
    return CatalogFetchResult()


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

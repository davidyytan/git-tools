"""Z.ai GLM Coding Plan metadata and effort mapping from agent-core.

The coding plan uses a separate endpoint and key from the general Z.ai API.
The curated choices are the two models documented by agent-core; arbitrary
model IDs remain available through the registry's manual-entry option.
"""

from __future__ import annotations

from .catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDER_ID = "zcode"
BASE_URL = "https://api.z.ai/api/coding/paas/v4"
API_KEY_ENV = "ZCODE_API_KEY"
DEFAULT_MODEL = "glm-5.3"
PROFILE = "zcode"
ALIASES: tuple[str, ...] = ()

PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(id=DEFAULT_MODEL, display_name="GLM-5.3"),
    ModelCatalogEntry(id="glm-5.3-flash", display_name="GLM-5.3-Flash"),
)

# Direct lift of agent_core.providers._ZCODE_EFFORT_TIERS. Thinking cannot
# be disabled on the coding plan, so "none" means its lowest tier, not off.
EFFORT_TIERS = {
    "none": "low",
    "minimal": "low",
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "max",
    "max": "max",
}


def resolve_reasoning_effort(effort: str | None) -> str | None:
    """Map a configured tier; absence remains absent (the server's max)."""
    requested = (effort or "").strip().lower()
    return EFFORT_TIERS.get(requested, requested) if requested else None


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return the curated coding-plan catalog without a network probe."""
    return CatalogFetchResult(entries=MODELS, source="live")


__all__ = [
    "ALIASES", "API_KEY_ENV", "BASE_URL", "DEFAULT_MODEL", "EFFORT_TIERS",
    "MODELS", "PRESET", "PROFILE", "PROVIDER_ID", "catalog",
    "resolve_reasoning_effort",
]

"""OpenAI platform endpoint and a heuristic live ``/models`` overlay.

``resolve_catalog`` filters live IDs by family names and modality markers; it does not verify ``/chat/completions`` compatibility or account access. Discovery failures and listings with no matching IDs produce no catalog choices, never a static replacement list. Credentials are entered by the user, never bundled.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDER_ID = "openai"
BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6-astra"
PROFILE = "openai"
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
    DEFAULT_MODEL: "GPT-6 Astra",
    "gpt-6.1-sol": "GPT-6.1 Sol",
}

# Candidate family-name prefixes for the picker heuristic, not a chat-completions compatibility guarantee.
_CHAT_FAMILY = re.compile(r"^(gpt-|chatgpt-|o\d)")
# Modality/name markers excluded by the heuristic, not an exhaustive capability inventory.
_NON_CHAT_MARKERS = (
    "-realtime", "-audio", "-transcribe", "-tts", "-image", "-search",
    "-instruct", "-embedding", "-moderation",
)


def is_chat_model(model_id: str) -> bool:
    """Return whether an ID passes the family-name and modality-marker heuristic.

    This is not a ``/chat/completions`` compatibility check; a Responses-only ID can pass if its name matches. It does not verify model availability or account access.
    """
    normalized = model_id.strip().lower()
    if not _CHAT_FAMILY.match(normalized):
        return False
    return not any(marker in normalized for marker in _NON_CHAT_MARKERS)


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return no choices before live discovery; defaults are not a catalog."""
    return CatalogFetchResult()


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Return only heuristic-filtered live IDs, never static replacement choices.

    Live IDs are kept verbatim, with display names overlaid only on discovered IDs and the default model pinned first only if present. No endpoint compatibility check is performed.

    Failed or unavailable discovery yields empty entries with the original fetch metadata. A successful listing with no heuristic matches retains its live source and timestamp without inventing a network or authentication error.
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
        if is_chat_model(entry.id)
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
    "is_chat_model",
    "resolve_catalog",
]

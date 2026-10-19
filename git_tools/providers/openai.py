"""OpenAI platform endpoint, built-in model choices and the live ``/models`` overlay.

The platform's ``/models`` lists everything the key can reach: chat models
beside audio, realtime, image, embedding and moderation ids that no chat
completion can use. The picker shows the chat families only
(``resolve_catalog``); the built-in list below is the default and the
fallback when the call cannot be made. Credentials are entered by the user,
never bundled.
"""

from __future__ import annotations

import re

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

# Picker order: the default leads; an existing profile's model is pinned first.
MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(id=DEFAULT_MODEL, display_name="GPT-6 Astra"),
    ModelCatalogEntry(id="gpt-6.1-sol", display_name="GPT-6.1 Sol"),
)

_DISPLAY_NAMES = {entry.id: entry.display_name for entry in MODELS}

# The families that answer chat completions: ``gpt-*``, ``chatgpt-*`` and the
# ``o<digit>`` reasoning series. Everything else the platform lists (whisper,
# tts, dall-e, embeddings, moderation, …) is not a chat model.
_CHAT_FAMILY = re.compile(r"^(gpt-|chatgpt-|o\d)")
# Same-family ids that are still not chat models: modality variants.
_NON_CHAT_MARKERS = (
    "-realtime", "-audio", "-transcribe", "-tts", "-image", "-search",
    "-instruct", "-embedding", "-moderation",
)


def is_chat_model(model_id: str) -> bool:
    """Whether a listed id can serve ``/chat/completions``."""
    normalized = model_id.strip().lower()
    if not _CHAT_FAMILY.match(normalized):
        return False
    return not any(marker in normalized for marker in _NON_CHAT_MARKERS)


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """Return the built-in catalog in the picker-compatible result shape."""
    return CatalogFetchResult(entries=MODELS, source="live")


def resolve_catalog(
    live: CatalogFetchResult[ModelCatalogEntry],
) -> CatalogFetchResult[ModelCatalogEntry]:
    """Prefer the platform's own list, chat models only; else the built-in one.

    Live ids are kept verbatim (they are what the platform routes), with the
    built-in display names overlaid where the id matches and the default
    model pinned first. When the fetch failed, or nothing it listed is a chat
    model, the built-in list is returned with the live error carried along so
    the caller can say why.
    """
    if live.source == "live" and live.entries:
        named = [
            ModelCatalogEntry(
                id=entry.id,
                display_name=entry.display_name or _DISPLAY_NAMES.get(entry.id),
            )
            for entry in live.entries
            if is_chat_model(entry.id)
        ]
        if named:
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
    "is_chat_model",
    "resolve_catalog",
]

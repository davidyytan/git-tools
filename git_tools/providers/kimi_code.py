"""Current Kimi Code model-catalog and thinking semantics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .catalog import (
    CatalogFetchResult,
    ModelCatalogEntry,
    fetch_model_catalog_sync,
    load_cached_catalog,
    parse_model_catalog,
    save_cached_catalog,
)

PROVIDER_ID = "kimicode"
# Verified against MoonshotAI/kimi-code: the Kimi Code platform is
# api.kimi.com/coding/v1 and its model is "kimi-for-coding" (kimi-k* models
# live on the separate Moonshot open platform).
BASE_URL = "https://api.kimi.com/coding/v1"
DEFAULT_MODEL = "kimi-for-coding"
PROFILE = "kimi"
ALIASES = ("kimi",)

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}
ThinkingChoice = tuple[str, bool, str | None]


@dataclass(frozen=True, slots=True)
class KimiCodeModelEntry(ModelCatalogEntry):
    """Normalized fields from the current Kimi Code ``/models`` schema."""

    context_length: int | None = None
    protocol: str | None = None
    supports_reasoning: bool | None = None
    supports_image_in: bool | None = None
    supports_video_in: bool | None = None
    supports_tool_use: bool | None = None
    supports_thinking_type: Literal["only", "both", "no"] | None = None
    valid_efforts: tuple[str, ...] = ()
    default_effort: str | None = None

    @classmethod
    def from_payload(cls, raw: Any) -> "KimiCodeModelEntry | None":
        if not isinstance(raw, dict):
            return None
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return None

        display_name = raw.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = None

        context_length = raw.get("context_length")
        if (
            not isinstance(context_length, int)
            or isinstance(context_length, bool)
            or context_length <= 0
        ):
            context_length = None

        protocol = raw.get("protocol")
        if not isinstance(protocol, str) or not protocol.strip():
            protocol = None

        thinking_type = raw.get("supports_thinking_type")
        if thinking_type not in {"only", "both", "no"}:
            thinking_type = None

        valid_efforts: tuple[str, ...] = ()
        default_effort: str | None = None
        think_efforts = raw.get("think_efforts")
        if isinstance(think_efforts, dict) and think_efforts.get("support") is True:
            raw_efforts = think_efforts.get("valid_efforts")
            if isinstance(raw_efforts, list):
                valid_efforts = tuple(
                    dict.fromkeys(
                        value.strip()
                        for value in raw_efforts
                        if isinstance(value, str) and value.strip()
                    )
                )
            candidate = think_efforts.get("default_effort")
            if isinstance(candidate, str) and candidate.strip():
                default_effort = candidate.strip()

        def optional_bool(name: str) -> bool | None:
            value = raw.get(name)
            return value if isinstance(value, bool) else None

        return cls(
            id=model_id.strip(),
            display_name=display_name.strip() if display_name else None,
            context_length=context_length,
            protocol=protocol.strip() if protocol else None,
            supports_reasoning=optional_bool("supports_reasoning"),
            supports_image_in=optional_bool("supports_image_in"),
            supports_video_in=optional_bool("supports_video_in"),
            supports_tool_use=optional_bool("supports_tool_use"),
            supports_thinking_type=thinking_type,
            valid_efforts=valid_efforts,
            default_effort=default_effort,
        )

    @classmethod
    def from_cache(cls, raw: Any) -> "KimiCodeModelEntry | None":
        """Decode only fields and types written by the current cache codec."""

        if not isinstance(raw, dict):
            return None
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return None

        def optional_text(name: str) -> str | None:
            value = raw.get(name)
            return value.strip() if isinstance(value, str) and value.strip() else None

        def optional_bool(name: str) -> bool | None:
            value = raw.get(name)
            return value if isinstance(value, bool) else None

        context_length = raw.get("context_length")
        if (
            not isinstance(context_length, int)
            or isinstance(context_length, bool)
            or context_length <= 0
        ):
            context_length = None

        thinking_type = raw.get("supports_thinking_type")
        if thinking_type not in {"only", "both", "no"}:
            thinking_type = None

        raw_efforts = raw.get("valid_efforts")
        valid_efforts: tuple[str, ...] = ()
        if isinstance(raw_efforts, (list, tuple)):
            valid_efforts = tuple(
                dict.fromkeys(
                    value.strip()
                    for value in raw_efforts
                    if isinstance(value, str) and value.strip()
                )
            )

        return cls(
            id=model_id.strip(),
            display_name=optional_text("display_name"),
            context_length=context_length,
            protocol=optional_text("protocol"),
            supports_reasoning=optional_bool("supports_reasoning"),
            supports_image_in=optional_bool("supports_image_in"),
            supports_video_in=optional_bool("supports_video_in"),
            supports_tool_use=optional_bool("supports_tool_use"),
            supports_thinking_type=thinking_type,
            valid_efforts=valid_efforts,
            default_effort=optional_text("default_effort"),
        )


def parse_kimi_code_catalog(payload: Any) -> tuple[KimiCodeModelEntry, ...]:
    return parse_model_catalog(payload, decode_entry=KimiCodeModelEntry.from_payload)


def fetch_kimi_code_catalog_sync(
    base_url: str,
    api_key: str,
    *,
    timeout: float = 4.0,
) -> CatalogFetchResult[KimiCodeModelEntry]:
    return fetch_model_catalog_sync(
        base_url,
        api_key,
        parser=parse_kimi_code_catalog,
        timeout=timeout,
    )


def save_cached_kimi_code_catalog(
    path: Path,
    *,
    base_url: str,
    api_key: str,
    result: CatalogFetchResult[KimiCodeModelEntry],
) -> None:
    save_cached_catalog(
        path,
        provider=PROVIDER_ID,
        base_url=base_url,
        api_key=api_key,
        result=result,
    )


def load_cached_kimi_code_catalog(
    path: Path,
    *,
    base_url: str,
    api_key: str,
) -> CatalogFetchResult[KimiCodeModelEntry]:
    return load_cached_catalog(
        path,
        provider=PROVIDER_ID,
        base_url=base_url,
        api_key=api_key,
        decode_entry=KimiCodeModelEntry.from_cache,
    )


def resolve_catalog(
    live: CatalogFetchResult[KimiCodeModelEntry],
    cached: CatalogFetchResult[KimiCodeModelEntry],
) -> CatalogFetchResult[KimiCodeModelEntry]:
    """Apply current Kimi Code last-known-good refresh semantics."""

    if live.source == "live" and live.entries:
        return live
    if live.error_kind == "http":
        return live
    if cached.entries and live.error_kind in {
        "auth",
        "network",
        "server",
        "malformed",
    }:
        return CatalogFetchResult(
            entries=cached.entries,
            source="cache",
            error_kind=live.error_kind,
            error=live.error,
            status=live.status,
            fetched_at=cached.fetched_at,
        )
    return live


def thinking_choices(entry: KimiCodeModelEntry) -> tuple[ThinkingChoice, ...]:
    """Return only choices declared by the current Kimi Code schema."""

    thinking_type = entry.supports_thinking_type
    if thinking_type == "no" or thinking_type is None:
        return ()
    choices: list[ThinkingChoice] = []
    if thinking_type == "both":
        choices.append(("off", False, None))
    if entry.valid_efforts:
        choices.extend((effort, True, effort) for effort in entry.valid_efforts)
    else:
        choices.append(("on", True, None))
    return tuple(choices)


def default_choice_index(
    entry: KimiCodeModelEntry,
    choices: tuple[ThinkingChoice, ...],
    *,
    current_thinking: bool | None,
    current_effort: str | None,
) -> int:
    """Match current Kimi Code thinking/effort resolution for picker defaults."""

    exact = next(
        (
            index
            for index, (_, enabled, effort) in enumerate(choices)
            if enabled == current_thinking and effort == current_effort
        ),
        None,
    )
    if exact is not None:
        return exact

    if current_thinking is not None:
        default_enabled = current_thinking
    else:
        default_enabled = entry.supports_thinking_type == "only" or (
            entry.supports_thinking_type == "both" and entry.supports_reasoning is True
        )

    if default_enabled and entry.valid_efforts:
        preferred_effort = entry.default_effort
        if preferred_effort not in entry.valid_efforts:
            preferred_effort = entry.valid_efforts[len(entry.valid_efforts) // 2]
        preferred = next(
            (
                index
                for index, (_, enabled, effort) in enumerate(choices)
                if enabled and effort == preferred_effort
            ),
            None,
        )
        if preferred is not None:
            return preferred

    desired = next(
        (
            index
            for index, (_, enabled, _) in enumerate(choices)
            if enabled is default_enabled
        ),
        None,
    )
    return desired if desired is not None else 0


__all__ = [
    "ALIASES",
    "BASE_URL",
    "DEFAULT_MODEL",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "KimiCodeModelEntry",
    "default_choice_index",
    "fetch_kimi_code_catalog_sync",
    "load_cached_kimi_code_catalog",
    "parse_kimi_code_catalog",
    "resolve_catalog",
    "save_cached_kimi_code_catalog",
    "thinking_choices",
]

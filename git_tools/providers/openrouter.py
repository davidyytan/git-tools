"""OpenRouter upstream-provider (endpoint) discovery.

OpenRouter serves one model id from many upstream providers. They differ in
price, context window, quantization — and, decisively, each keeps its OWN
prompt cache. Letting OpenRouter pick freely means a run can migrate between
upstreams mid-session and silently throw away the cache the previous turns
paid to build, so the CLI asks which one to pin and agent-core sends it as
``provider.only``.

The list is per model, so it is fetched from ``/models/<id>/endpoints`` at pick
time rather than kept as a constant here.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from .catalog import CatalogFetchResult

PROVIDER_ID = "openrouter"
BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
PROFILE = "openrouter"
ALIASES = ("router",)

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}
# What the shipped config pins. Routing is unpinned by default in agent-core;
# this is the explicit choice for DEFAULT_MODEL — measured cheapest at 1M
# context with working automatic prefix caching.
DEFAULT_ENDPOINT_TAG = "deepinfra/fp4"

# Sentinel value meaning "do not pin — let OpenRouter route". Understood by
# agent-core's _openrouter_provider_slug.
UNPINNED = "any"

_AUTH_STATUSES = frozenset({401, 402, 403})


@dataclass(frozen=True, slots=True)
class OpenRouterEndpoint:
    """One upstream provider serving a given model."""

    #: Routing slug, e.g. ``deepinfra`` or ``deepinfra/fp4``. Passed verbatim
    #: to ``provider.only``; the variant form pins quantization too.
    tag: str
    provider_name: str
    context_length: int | None = None
    prompt_price: float | None = None
    completion_price: float | None = None
    cache_read_price: float | None = None
    quantization: str | None = None
    uptime_30m: float | None = None

    @property
    def id(self) -> str:
        return self.tag

    @property
    def label(self) -> str:
        return self.provider_name or self.tag

    @property
    def caches(self) -> bool:
        """Whether cache reads are billed below the normal prompt rate.

        Derived from pricing rather than OpenRouter's ``supports_implicit_
        caching`` flag: that flag reports False for providers measured to do
        automatic prefix caching (DeepInfra among them), while a discounted
        cache-read price is what actually shows up on the bill.
        """

        if self.cache_read_price is None or self.prompt_price is None:
            return False
        return 0 < self.cache_read_price < self.prompt_price

    def price_text(self) -> str:
        """`$in/$out per million`, or an empty string when unpriced."""

        if self.prompt_price is None or self.completion_price is None:
            return ""
        return f"${self.prompt_price * 1e6:.3f}/${self.completion_price * 1e6:.3f} per M"

    def detail_text(self) -> str:
        """One-line summary for the picker row."""

        bits = [text for text in (self.price_text(),) if text]
        if self.context_length:
            bits.append(f"{self.context_length // 1024}k ctx")
        if self.quantization and self.quantization != "unknown":
            bits.append(self.quantization)
        if self.caches:
            bits.append("cached")
        if self.uptime_30m is not None:
            bits.append(f"{self.uptime_30m:.0f}% up")
        return " · ".join(bits)

    @classmethod
    def from_payload(cls, raw: Any) -> "OpenRouterEndpoint | None":
        if not isinstance(raw, dict):
            return None
        tag = raw.get("tag")
        if not isinstance(tag, str) or not tag.strip():
            return None
        pricing = raw.get("pricing")
        pricing = pricing if isinstance(pricing, dict) else {}

        def _price(key: str) -> float | None:
            try:
                return float(pricing[key])
            except (KeyError, TypeError, ValueError):
                return None

        def _int(key: str) -> int | None:
            value = raw.get(key)
            return value if isinstance(value, int) else None

        def _float(key: str) -> float | None:
            value = raw.get(key)
            return float(value) if isinstance(value, (int, float)) else None

        provider_name = raw.get("provider_name")
        quantization = raw.get("quantization")
        return cls(
            tag=tag.strip(),
            provider_name=(
                provider_name.strip()
                if isinstance(provider_name, str) and provider_name.strip()
                else tag.strip()
            ),
            context_length=_int("context_length"),
            prompt_price=_price("prompt"),
            completion_price=_price("completion"),
            cache_read_price=_price("input_cache_read"),
            quantization=(
                quantization.strip() if isinstance(quantization, str) else None
            ),
            uptime_30m=_float("uptime_last_30m"),
        )


def parse_endpoints(payload: Any) -> tuple[OpenRouterEndpoint, ...]:
    """Parse ``/models/<id>/endpoints`` into routing candidates.

    Ordered cheapest input first — the picker's order — since price is the
    axis a user is most often choosing on once caching is assured.
    """

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("endpoints response does not contain a data object")
    raw_endpoints = data.get("endpoints")
    if not isinstance(raw_endpoints, list):
        raise ValueError("endpoints response does not contain an endpoints array")
    entries: dict[str, OpenRouterEndpoint] = {}
    for raw in raw_endpoints:
        entry = OpenRouterEndpoint.from_payload(raw)
        if entry is not None:
            entries[entry.tag] = entry
    return tuple(
        sorted(
            entries.values(),
            key=lambda item: (
                item.prompt_price if item.prompt_price is not None else float("inf"),
                item.label.lower(),
            ),
        )
    )


def fetch_endpoints_sync(
    model_id: str,
    api_key: str,
    *,
    base_url: str = BASE_URL,
    timeout: float = 6.0,
) -> CatalogFetchResult[OpenRouterEndpoint]:
    """Fetch a model's upstream providers without raising UI-facing errors."""

    if not model_id.strip():
        return CatalogFetchResult(error_kind="malformed", error="model id is empty")
    url = f"{(base_url or BASE_URL).rstrip('/')}/models/{model_id.strip()}/endpoints"
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        entries = parse_endpoints(payload)
        if not entries:
            raise ValueError("model has no available upstream providers")
        return CatalogFetchResult(
            entries=entries,
            source="live",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        kind: Literal["auth", "server", "http"] = (
            "auth" if status in _AUTH_STATUSES else "server" if status >= 500 else "http"
        )
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        return CatalogFetchResult(
            error_kind=kind,
            error=detail or f"endpoint request failed with HTTP {status}",
            status=status,
        )
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return CatalogFetchResult(
            error_kind="network", error=str(exc) or type(exc).__name__
        )
    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError) as exc:
        return CatalogFetchResult(error_kind="malformed", error=str(exc))


__all__ = [
    "ALIASES",
    "BASE_URL",
    "DEFAULT_ENDPOINT_TAG",
    "DEFAULT_MODEL",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "UNPINNED",
    "OpenRouterEndpoint",
    "fetch_endpoints_sync",
    "parse_endpoints",
]

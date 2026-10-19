"""Shared OpenAI-compatible model-catalog transport and cache primitives."""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit, urlunsplit

from ..utils.io import atomic_write_json, read_json

MODEL_CATALOG_FILENAME = "model-catalog.json"
_CACHE_VERSION = 1
_AUTH_STATUSES = frozenset({401, 402, 403})


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    """Provider-neutral metadata from an OpenAI-compatible model catalog."""

    id: str
    display_name: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.id

    @classmethod
    def from_payload(cls, raw: Any) -> "ModelCatalogEntry | None":
        if not isinstance(raw, dict):
            return None
        model_id = raw.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return None
        display_name = raw.get("display_name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = None
        return cls(
            id=model_id.strip(),
            display_name=display_name.strip() if display_name else None,
        )

    @classmethod
    def from_cache(cls, raw: Any) -> "ModelCatalogEntry | None":
        return cls.from_payload(raw)


EntryT = TypeVar("EntryT", bound=ModelCatalogEntry)
EntryDecoder = Callable[[Any], EntryT | None]
EntryEncoder = Callable[[EntryT], Mapping[str, Any]]
CatalogParser = Callable[[Any], tuple[EntryT, ...]]


@dataclass(frozen=True, slots=True)
class CatalogFetchResult(Generic[EntryT]):
    entries: tuple[EntryT, ...] = ()
    source: Literal["live", "cache", "none"] = "none"
    error_kind: Literal["auth", "network", "server", "http", "malformed"] | None = None
    error: str | None = None
    status: int | None = None
    fetched_at: str | None = None


def parse_model_catalog(
    payload: Any,
    *,
    decode_entry: EntryDecoder[EntryT] = ModelCatalogEntry.from_payload,
) -> tuple[EntryT, ...]:
    """Parse an OpenAI-compatible ``data`` array with a provider codec."""

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("model catalog response does not contain a data array")
    entries: dict[str, EntryT] = {}
    for raw in data:
        entry = decode_entry(raw)
        if entry is not None:
            entries[entry.id] = entry
    return tuple(sorted(entries.values(), key=lambda item: (item.label.lower(), item.id)))


def fetch_model_catalog_sync(
    base_url: str,
    api_key: str,
    *,
    parser: CatalogParser[EntryT] = parse_model_catalog,
    timeout: float = 4.0,
    headers: Mapping[str, str] | None = None,
    query: str | None = None,
) -> CatalogFetchResult[EntryT]:
    """Fetch a provider catalog without raising UI-facing errors.

    ``query`` is appended to the URL for catalogs that page.
    """

    if not base_url:
        return CatalogFetchResult(
            error_kind="malformed", error="provider base URL is empty"
        )
    url = base_url.rstrip("/") + "/models" + (f"?{query}" if query else "")
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        entries = parser(payload)
        if not entries:
            raise ValueError("provider returned no usable model entries")
        return CatalogFetchResult(
            entries=entries,
            source="live",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        kind: Literal["auth", "server", "http"] = (
            "auth"
            if status in _AUTH_STATUSES
            else "server"
            if status >= 500
            else "http"
        )
        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        message = detail or f"model catalog request failed with HTTP {status}"
        return CatalogFetchResult(error_kind=kind, error=message, status=status)
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return CatalogFetchResult(
            error_kind="network", error=str(exc) or type(exc).__name__
        )
    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError) as exc:
        return CatalogFetchResult(error_kind="malformed", error=str(exc))


def _normalized_base_url(base_url: str) -> str:
    """Normalize URL identity while preserving a case-sensitive path."""

    candidate = base_url.strip().rstrip("/")
    parts = urlsplit(candidate)
    if not parts.scheme or not parts.netloc:
        return candidate
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, "")
    )


def _cache_key(provider: str, base_url: str, api_key: str) -> str:
    normalized_base = _normalized_base_url(base_url)
    credential = (
        hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        if api_key
        else "anonymous"
    )
    return hashlib.sha256(
        f"{provider.lower()}\0{normalized_base}\0{credential}".encode("utf-8")
    ).hexdigest()[:24]


def save_cached_catalog(
    path: Path,
    *,
    provider: str,
    base_url: str,
    api_key: str,
    result: CatalogFetchResult[EntryT],
    encode_entry: EntryEncoder[EntryT] = asdict,
) -> None:
    """Atomically store one credential-scoped last-known-good catalog."""

    if not result.entries:
        return
    payload = read_json(path, default={})
    if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
        payload = {"version": _CACHE_VERSION, "catalogs": {}}
    catalogs = payload.get("catalogs")
    if not isinstance(catalogs, dict):
        catalogs = {}
        payload["catalogs"] = catalogs
    catalogs[_cache_key(provider, base_url, api_key)] = {
        "provider": provider,
        "base_url": base_url.rstrip("/"),
        "fetched_at": result.fetched_at or datetime.now(timezone.utc).isoformat(),
        "entries": [dict(encode_entry(entry)) for entry in result.entries],
    }
    atomic_write_json(path, payload)


def load_cached_catalog(
    path: Path,
    *,
    provider: str,
    base_url: str,
    api_key: str,
    decode_entry: EntryDecoder[EntryT] = ModelCatalogEntry.from_cache,
) -> CatalogFetchResult[EntryT]:
    """Load a cache record only when its version and entry codec are valid."""

    payload = read_json(path, default={})
    if not isinstance(payload, dict) or payload.get("version") != _CACHE_VERSION:
        return CatalogFetchResult()
    catalogs = payload.get("catalogs")
    record = (
        catalogs.get(_cache_key(provider, base_url, api_key))
        if isinstance(catalogs, dict)
        else None
    )
    if not isinstance(record, dict):
        return CatalogFetchResult()
    raw_entries = record.get("entries")
    if not isinstance(raw_entries, list):
        return CatalogFetchResult()
    entries = tuple(
        entry
        for raw in raw_entries
        if (entry := decode_entry(raw)) is not None
    )
    if not entries:
        return CatalogFetchResult()
    fetched_at = record.get("fetched_at")
    return CatalogFetchResult(
        entries=entries,
        source="cache",
        fetched_at=fetched_at if isinstance(fetched_at, str) else None,
    )


__all__ = [
    "MODEL_CATALOG_FILENAME",
    "CatalogFetchResult",
    "ModelCatalogEntry",
    "fetch_model_catalog_sync",
    "load_cached_catalog",
    "parse_model_catalog",
    "save_cached_catalog",
]

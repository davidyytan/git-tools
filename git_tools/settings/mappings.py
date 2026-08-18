"""Provider and model definitions.

Provider metadata — API-key env vars, config classes, display details, model
catalog behavior, and static fallback models — lives in code here. There is no
external ``mappings.json`` to copy or maintain in the repo.

Every built-in provider exposes an OpenAI-compatible ``GET {base_url}/models``
catalog. ``refresh_live_models`` merges that account/endpoint-specific catalog
into ``PROVIDERS`` for pickers and validation. Static entries remain the offline
fallback, while manually entered model IDs are saved in
``~/.git-tools/models.json`` and retained across refreshes.
"""

import copy
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import typer

# OpenRouter model used when nothing else is configured.
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"

# User settings file holding manually entered model IDs by provider. Kept inside
# ~/.git-tools/ so a full reset stays a single `rm -rf ~/.git-tools`.
USER_MODELS_PATH = Path.home() / ".git-tools" / "models.json"

# Live-discovered CLIProxyAPI models matching these prefixes are
# effort-capable and receive this per-model default.
_LIVE_EFFORT_DEFAULT = "xhigh"
_AUTH_STATUSES = frozenset({401, 402, 403})


class LiveModelList(list[str]):
    """Model IDs plus bounded failure details for interactive diagnostics."""

    def __init__(
        self,
        values: List[str] | None = None,
        *,
        error_kind: str | None = None,
        error: str | None = None,
        status: int | None = None,
    ) -> None:
        super().__init__(values or [])
        self.error_kind = error_kind
        self.error = error
        self.status = status


@dataclass(frozen=True)
class LiveModelRefreshError:
    """Why a provider catalog could not be refreshed."""

    kind: str
    message: str
    status: int | None = None
    retained_live_catalog: bool = False


@dataclass(frozen=True)
class ProviderCatalogSnapshot:
    """Restorable in-process catalog and refresh state for one provider."""

    models: Dict[str, Any]
    refreshed: bool
    identity: tuple[str, str] | None
    error: LiveModelRefreshError | None


# Built-in provider definitions (source of truth). ``default_base_url`` is UI
# metadata only; the actual runtime value still comes from each config class so
# request behavior remains unchanged.
_BUILTIN_PROVIDERS: Dict[str, Any] = {
    "openrouter": {
        "label": "OpenRouter",
        "aliases": ("router",),
        "api_key_env": "OPENROUTER_API_KEY",
        "config_class": "OpenRouterConfig",
        "default_base_url": "https://openrouter.ai/api/v1",
        "live_models": True,
        "allow_manual_model": True,
        "live_model_defaults": {"data_collection": "deny"},
        "models": {
            DEFAULT_OPENROUTER_MODEL: {
                "model_name": DEFAULT_OPENROUTER_MODEL,
                "data_collection": "deny",
            },
        },
    },
    "kimicli": {
        "label": "Kimi Code",
        # Keep the existing git-tools provider key for compatibility while
        # accepting agent-core/agent-cli's canonical spelling and shorthand.
        "aliases": ("kimicode", "kimi"),
        "api_key_env": "KIMICODE_API_KEY",
        "config_class": "KimiCLIConfig",
        "default_base_url": "https://api.kimi.com/coding/v1",
        "live_models": True,
        "allow_manual_model": True,
        "models": {
            "kimi-k2.5": {"model_name": "kimi-k2.5"},
        },
    },
    "cliproxyapi": {
        "label": "CLIProxyAPI",
        "aliases": ("proxy",),
        "api_key_env": "CLIPROXYAPI_API_KEY",
        "config_class": "CLIProxyAPIConfig",
        "default_base_url": "http://localhost:8317/v1",
        "live_models": True,
        "allow_manual_model": True,
        "live_effort_prefixes": ("gpt-5",),
        "models": {
            "gpt-5.6-sol": {"model_name": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
            "gpt-5.5": {"model_name": "gpt-5.5", "reasoning_effort": "xhigh"},
            "gpt-5.4": {"model_name": "gpt-5.4", "reasoning_effort": "xhigh"},
        },
    },
}

# Aliases accepted by direct settings and environment configuration. Provider
# values are still persisted using the existing canonical git-tools keys.
PROVIDER_ALIASES = {
    str(alias).strip().lower(): provider
    for provider, definition in _BUILTIN_PROVIDERS.items()
    for alias in definition.get("aliases", ())
}

# Capability sets are derived from provider metadata instead of maintained as
# special-case lists, so adding a provider automatically updates the picker.
LIVE_MODEL_PROVIDERS = tuple(
    provider
    for provider, definition in _BUILTIN_PROVIDERS.items()
    if definition.get("live_models")
)
MANUAL_MODEL_PROVIDERS = tuple(
    provider
    for provider, definition in _BUILTIN_PROVIDERS.items()
    if definition.get("allow_manual_model")
)


def _normalize_provider_key(provider: str) -> str:
    key = str(provider).strip().lower()
    return PROVIDER_ALIASES.get(key, key)


def _provider_model_entry(provider: str, model_id: str) -> Dict[str, Any]:
    """Build provider-aware metadata for a discovered or manual model ID."""
    entry: Dict[str, Any] = {"model_name": model_id}
    definition = _BUILTIN_PROVIDERS[provider]
    entry.update(copy.deepcopy(definition.get("live_model_defaults", {})))
    prefixes = tuple(definition.get("live_effort_prefixes", ()))
    if prefixes and model_id.startswith(prefixes):
        entry["reasoning_effort"] = _LIVE_EFFORT_DEFAULT
    return entry


def _load_user_model_map() -> Dict[str, List[str]]:
    """Return clean, de-duplicated manually saved model IDs by provider."""
    if not USER_MODELS_PATH.exists():
        return {}

    try:
        data = json.loads(USER_MODELS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(
            typer.style(
                f"Warning: Error loading {USER_MODELS_PATH.name}: {e}",
                fg=typer.colors.YELLOW,
            )
        )
        return {}

    if not isinstance(data, dict):
        return {}

    result: Dict[str, List[str]] = {}
    for raw_provider, raw_models in data.items():
        if not isinstance(raw_provider, str) or not isinstance(raw_models, list):
            continue
        provider = _normalize_provider_key(raw_provider)
        if provider not in _BUILTIN_PROVIDERS:
            continue
        seen: set[str] = set()
        models: List[str] = []
        for item in raw_models:
            if not isinstance(item, str):
                continue
            model_id = item.strip()
            if model_id and model_id not in seen:
                seen.add(model_id)
                models.append(model_id)
        if models:
            result[provider] = models
    return result


def _load_user_openrouter_models() -> List[str]:
    """Compatibility helper returning saved OpenRouter model IDs."""
    return _load_user_model_map().get("openrouter", [])


_USER_MODELS = _load_user_model_map()


def _build_providers() -> Dict[str, Any]:
    """Assemble provider definitions plus manually saved model IDs."""
    providers = copy.deepcopy(_BUILTIN_PROVIDERS)
    for provider, model_ids in _USER_MODELS.items():
        models = providers[provider]["models"]
        for model_id in model_ids:
            models.setdefault(model_id, _provider_model_entry(provider, model_id))
    return providers


# Provider map used across the app.
PROVIDERS = _build_providers()

# Immutable-ish fallback catalogs. Live refreshes always merge against these,
# not against a prior live result, so force-refreshing cannot lose static model
# metadata such as privacy defaults or reasoning effort.
_FALLBACK_MODELS: Dict[str, Dict[str, Any]] = {
    provider: copy.deepcopy(definition["models"])
    for provider, definition in PROVIDERS.items()
}


def fetch_live_models(
    base_url: str,
    api_key: str,
    timeout: float = 4.0,
) -> LiveModelList:
    """GET ``{base_url}/models`` and return IDs plus failure metadata.

    The list remains backward-compatible with callers that only need model IDs,
    while interactive settings can distinguish authentication, network, HTTP,
    and malformed-catalog failures instead of silently showing a fallback as if
    it were the complete live catalog.
    """
    if not base_url:
        return LiveModelList(
            error_kind="malformed",
            error="provider base URL is empty",
        )
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        kind = "auth" if status in _AUTH_STATUSES else "server" if status >= 500 else "http"
        return LiveModelList(
            error_kind=kind,
            error=f"model catalog request failed with HTTP {status}",
            status=status,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return LiveModelList(
            error_kind="network",
            error=str(exc) or type(exc).__name__,
        )
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError) as exc:
        return LiveModelList(error_kind="malformed", error=str(exc))

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return LiveModelList(
            error_kind="malformed",
            error="model catalog response does not contain a data array",
        )
    ids = [
        str(model.get("id")).strip()
        for model in data
        if isinstance(model, dict) and model.get("id")
    ]
    unique = sorted(dict.fromkeys(model_id for model_id in ids if model_id))
    if not unique:
        return LiveModelList(
            error_kind="malformed",
            error="provider returned no usable model entries",
        )
    return LiveModelList(unique)


# Providers refreshed this process. The identity map prevents a successful
# catalog fetched with one endpoint/key from being reused after either changes.
_LIVE_REFRESHED: set[str] = set()
_LIVE_REFRESH_IDENTITIES: Dict[str, tuple[str, str]] = {}
_LIVE_REFRESH_ERRORS: Dict[str, LiveModelRefreshError] = {}


def get_live_model_refresh_error(provider: str) -> LiveModelRefreshError | None:
    """Return the last catalog refresh error for a provider, if any."""
    return _LIVE_REFRESH_ERRORS.get(_normalize_provider_key(provider))


def snapshot_provider_catalog(provider: str) -> ProviderCatalogSnapshot:
    """Capture provider catalog state before temporary credential discovery."""
    provider = _normalize_provider_key(provider)
    return ProviderCatalogSnapshot(
        models=copy.deepcopy(PROVIDERS[provider]["models"]),
        refreshed=provider in _LIVE_REFRESHED,
        identity=_LIVE_REFRESH_IDENTITIES.get(provider),
        error=_LIVE_REFRESH_ERRORS.get(provider),
    )


def restore_provider_catalog(
    provider: str,
    snapshot: ProviderCatalogSnapshot,
) -> None:
    """Restore provider catalog state after a cancelled/failed transaction."""
    provider = _normalize_provider_key(provider)
    PROVIDERS[provider]["models"] = copy.deepcopy(snapshot.models)
    if snapshot.refreshed:
        _LIVE_REFRESHED.add(provider)
    else:
        _LIVE_REFRESHED.discard(provider)
    if snapshot.identity is None:
        _LIVE_REFRESH_IDENTITIES.pop(provider, None)
    else:
        _LIVE_REFRESH_IDENTITIES[provider] = snapshot.identity
    if snapshot.error is None:
        _LIVE_REFRESH_ERRORS.pop(provider, None)
    else:
        _LIVE_REFRESH_ERRORS[provider] = snapshot.error


def _catalog_identity(base_url: str, api_key: str) -> tuple[str, str]:
    credential = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:16]
    return (base_url.strip().rstrip("/"), credential)


def _fallback_models(provider: str) -> Dict[str, Any]:
    """Return static plus manually saved models for an offline provider."""
    fallback = copy.deepcopy(_FALLBACK_MODELS[provider])
    for model_id in _load_user_model_map().get(provider, []):
        fallback.setdefault(model_id, _provider_model_entry(provider, model_id))
    return fallback


def refresh_live_models(provider: str, *, force: bool = False) -> bool:
    """Refresh one provider's model catalog from its configured ``/models``.

    Static entries still served live keep their metadata and priority order.
    Stale static entries are dropped for the live result, manually saved entries
    remain available as explicit user choices, and newly served IDs append in
    catalog order. A failed fetch keeps the current catalog for the same
    endpoint/key, or resets to static/manual fallbacks after an identity change.

    Returns ``True`` when a live catalog is available (including a memoized one)
    and ``False`` for unknown providers or failed fetches.
    """
    provider = _normalize_provider_key(provider)
    if provider not in LIVE_MODEL_PROVIDERS:
        return False

    # Runtime import: settings.py imports this module at load time.
    from .settings import load_provider_config

    try:
        config = load_provider_config(provider)
    except Exception as exc:
        _LIVE_REFRESH_ERRORS[provider] = LiveModelRefreshError(
            kind="configuration",
            # Pydantic validation text can echo rejected input values. Keep the
            # interactive diagnostic useful without ever retaining credentials.
            message=f"{type(exc).__name__}: provider configuration is invalid or incomplete",
        )
        # Configuration is no longer sufficient to identify the account. Never
        # retain a live catalog fetched under an earlier credential.
        PROVIDERS[provider]["models"] = _fallback_models(provider)
        _LIVE_REFRESHED.discard(provider)
        _LIVE_REFRESH_IDENTITIES.pop(provider, None)
        return False

    base_url = config.base_url or ""
    api_key = config.api_key or ""
    identity = _catalog_identity(base_url, api_key)
    if (
        not force
        and provider in _LIVE_REFRESHED
        and _LIVE_REFRESH_IDENTITIES.get(provider) == identity
    ):
        return True

    live = fetch_live_models(base_url, api_key)
    if not live:
        retained_live_catalog = (
            provider in _LIVE_REFRESHED
            and _LIVE_REFRESH_IDENTITIES.get(provider) == identity
        )
        _LIVE_REFRESH_ERRORS[provider] = LiveModelRefreshError(
            kind=getattr(live, "error_kind", None) or "unknown",
            message=getattr(live, "error", None) or "live model discovery failed",
            status=getattr(live, "status", None),
            retained_live_catalog=retained_live_catalog,
        )
        # If this provider was previously refreshed under a different endpoint
        # or credential, do not leak that old catalog into the new identity.
        if (
            provider in _LIVE_REFRESHED
            and _LIVE_REFRESH_IDENTITIES.get(provider) != identity
        ):
            PROVIDERS[provider]["models"] = _fallback_models(provider)
            _LIVE_REFRESHED.discard(provider)
            _LIVE_REFRESH_IDENTITIES.pop(provider, None)
        return False

    live_ids = set(live)
    remembered = _load_user_model_map().get(provider, [])
    remembered_ids = set(remembered)
    fallback = _FALLBACK_MODELS[provider]
    merged: Dict[str, Any] = {}
    for key, entry in fallback.items():
        model_id = entry.get("model_name")
        if model_id in live_ids or model_id in remembered_ids:
            merged[key] = copy.deepcopy(entry)
    for model_id in live:
        merged.setdefault(model_id, _provider_model_entry(provider, model_id))
    for model_id in remembered:
        merged.setdefault(model_id, _provider_model_entry(provider, model_id))

    PROVIDERS[provider]["models"] = merged
    _LIVE_REFRESHED.add(provider)
    _LIVE_REFRESH_IDENTITIES[provider] = identity
    _LIVE_REFRESH_ERRORS.pop(provider, None)
    return True


def add_user_model(provider: str, model_id: str) -> bool:
    """Persist a manual model ID for a provider and expose it immediately.

    Returns ``True`` if a new ID was saved, and ``False`` for blank input or a
    duplicate. Unknown providers raise ``ValueError`` because they cannot be
    loaded by the current provider registry.
    """
    provider = _normalize_provider_key(provider)
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")

    model_id = (model_id or "").strip()
    if not model_id:
        return False

    saved = _load_user_model_map()
    provider_models = saved.setdefault(provider, [])
    is_new = model_id not in provider_models
    if is_new:
        provider_models.append(model_id)
        USER_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_MODELS_PATH.write_text(json.dumps(saved, indent=2) + "\n")

    _USER_MODELS.setdefault(provider, [])
    if model_id not in _USER_MODELS[provider]:
        _USER_MODELS[provider].append(model_id)

    entry = _provider_model_entry(provider, model_id)
    _FALLBACK_MODELS[provider].setdefault(model_id, copy.deepcopy(entry))
    PROVIDERS[provider]["models"].setdefault(model_id, entry)
    return is_new


def add_user_openrouter_model(slug: str) -> bool:
    """Compatibility wrapper for callers that add an OpenRouter model slug."""
    return add_user_model("openrouter", slug)


def provider_allows_manual_model(provider: str) -> bool:
    """Return whether the provider picker accepts arbitrary model IDs."""
    return _normalize_provider_key(provider) in MANUAL_MODEL_PROVIDERS


__all__ = [
    "DEFAULT_OPENROUTER_MODEL",
    "LIVE_MODEL_PROVIDERS",
    "LiveModelList",
    "LiveModelRefreshError",
    "MANUAL_MODEL_PROVIDERS",
    "PROVIDER_ALIASES",
    "ProviderCatalogSnapshot",
    "PROVIDERS",
    "USER_MODELS_PATH",
    "add_user_model",
    "add_user_openrouter_model",
    "fetch_live_models",
    "get_live_model_refresh_error",
    "provider_allows_manual_model",
    "refresh_live_models",
    "restore_provider_catalog",
    "snapshot_provider_catalog",
]

"""Provider and model definitions.

Provider metadata — API-key env vars, config classes, display details, model
catalog behavior, and static fallback models — lives in code here. There is no
external ``mappings.json`` to copy or maintain in the repo.

Live providers expose an OpenAI-compatible ``GET {base_url}/models``
catalog; ``refresh_live_models`` resolves it exactly as agent-cli's provider
flow does (``resolve_provider_catalog``) and places the result in
``PROVIDERS`` for pickers, editors and clients. There is no list of git-tools'
own: the modules' built-in lists are the only fallback, Kimi Code keeps
agent-cli's last-known-good cache, and a typed model id is remembered only as
the saved main model.

Endpoints, default models, aliases, curated lists and the catalog codecs come
from ``git_tools.providers``, the provider package copied from agent-cli; this
module wraps those modules with git-tools' own wiring (credential env vars,
config classes, live/manual picker flags, per-model knobs) and keeps the
registry shape the rest of the application reads.
"""

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

from git_tools.providers import acrc, anthropic, cliproxyapi, copilot, kimi_code, openai, openrouter, qwen
from git_tools.providers.catalog import (
    MODEL_CATALOG_FILENAME,
    CatalogFetchResult,
    ModelCatalogEntry,
    fetch_model_catalog_sync,
)
from git_tools.providers.kimi_code import (
    KimiCodeModelEntry,
    fetch_kimi_code_catalog_sync,
    load_cached_kimi_code_catalog,
    save_cached_kimi_code_catalog,
)

# OpenRouter model used when nothing else is configured: agent-cli's.
DEFAULT_OPENROUTER_MODEL = openrouter.DEFAULT_MODEL

# Kimi Code's last-known-good catalog, in agent-cli's cache format and under
# its file name. Kept inside ~/.git-tools/ so a full reset stays a single
# `rm -rf ~/.git-tools`.
MODEL_CATALOG_PATH = Path.home() / ".git-tools" / MODEL_CATALOG_FILENAME

# OpenAI's reasoning families read the native ``reasoning_effort`` field and
# accept only the server's default temperature. The platform's other chat
# models (gpt-4.x, gpt-4o, gpt-3.5 and the ``*-chat-latest`` variants) reject
# the field outright and take a temperature instead. This is git-tools' wire
# policy; agent-core reaches the same outcome by sending OpenAI's default
# temperature of 1.
_OPENAI_REASONING_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4", "codex")
_OPENAI_NON_REASONING_MARKERS = ("-chat",)

# Kept as names for callers and tests; the catalog itself is resolved by the
# provider modules (see ``resolve_provider_catalog``).
is_openai_chat_model = openai.is_chat_model
ANTHROPIC_API_VERSION = anthropic.API_VERSION
anthropic_catalog_headers = anthropic.catalog_headers


def is_openai_reasoning_model(model_id: str) -> bool:
    """Whether an OpenAI model reads ``reasoning_effort`` (and refuses a temperature)."""
    normalized = model_id.strip().lower()
    if not normalized.startswith(_OPENAI_REASONING_PREFIXES):
        return False
    return not any(marker in normalized for marker in _OPENAI_NON_REASONING_MARKERS)


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


# Built-in provider definitions (source of truth). Endpoint, default model,
# aliases and curated lists come from the provider modules copied from
# agent-cli (``git_tools.providers``); what is added here is git-tools' own
# wiring: the credential env var, the config class, the UI label, which
# pickers are live, and per-model knobs. ``default_base_url`` is UI metadata
# only; the actual runtime value still comes from each config class so
# request behavior remains unchanged.


def _static_models(entries: tuple[ModelCatalogEntry, ...]) -> Dict[str, Any]:
    """A provider module's curated ``MODELS`` as registry entries, in picker order."""
    models: Dict[str, Any] = {}
    for entry in entries:
        model: Dict[str, Any] = {"model_name": entry.id}
        if entry.display_name:
            model["display_name"] = entry.display_name
        models[entry.id] = model
    return models


_BUILTIN_PROVIDERS: Dict[str, Any] = {
    openrouter.PROVIDER_ID: {
        "label": "OpenRouter",
        "aliases": openrouter.ALIASES,
        "api_key_env": "OPENROUTER_API_KEY",
        "config_class": "OpenRouterConfig",
        "default_base_url": openrouter.BASE_URL,
        "default_model": openrouter.DEFAULT_MODEL,
        "live_models": True,
        "allow_manual_model": True,
        # The catalog is live; agent-cli ships no static list and neither does this.
        "models": {},
    },
    acrc.PROVIDER_ID: {
        "label": "ACRC", "aliases": acrc.ALIASES, "api_key_env": "ACRC_API_KEY",
        "config_class": "ACRCConfig",
        "default_base_url": acrc.BASE_URL,
        "default_model": acrc.DEFAULT_MODEL,
        # Live /models drives the picker; these built-ins lead the list and
        # are the fallback when the VPN/endpoint cannot be reached.
        "live_models": True, "allow_manual_model": True,
        "models": _static_models(acrc.MODELS),
    },
    copilot.PROVIDER_ID: {
        "label": "Copilot proxy", "aliases": copilot.ALIASES, "api_key_env": "COPILOT_API_KEY",
        "config_class": "CopilotConfig", "default_base_url": copilot.BASE_URL,
        "default_model": copilot.DEFAULT_MODEL,
        "live_models": True, "allow_manual_model": True,
        "models": _static_models(copilot.MODELS),
    },
    qwen.PROVIDER_ID: {
        "label": "Qwen / DashScope", "aliases": qwen.ALIASES,
        "api_key_env": "DASHSCOPE_API_KEY", "config_class": "QwenConfig",
        # No endpoint on purpose (see the module): the host depends on the
        # plan, region and workspace, so the flow asks for it.
        "default_base_url": qwen.PRESET.get("base_url", ""),
        "default_model": qwen.DEFAULT_MODEL,
        "live_models": False, "allow_manual_model": True,
        "curated_models": True,
        "models": _static_models(qwen.MODELS),
    },
    "kimicli": {
        "label": "Kimi Code",
        # Keep the existing git-tools provider key for compatibility while
        # accepting agent-core/agent-cli's canonical spelling and shorthand.
        "aliases": (kimi_code.PROVIDER_ID, *kimi_code.ALIASES),
        "api_key_env": "KIMICODE_API_KEY",
        "config_class": "KimiCLIConfig",
        "default_base_url": kimi_code.BASE_URL,
        "default_model": kimi_code.DEFAULT_MODEL,
        "live_models": True,
        "allow_manual_model": True,
        # The account-aware catalog is live; no static list, as in agent-cli.
        "models": {},
    },
    cliproxyapi.PROVIDER_ID: {
        "label": "CLIProxyAPI",
        "aliases": cliproxyapi.ALIASES,
        "api_key_env": "CLIPROXYAPI_API_KEY",
        "config_class": "CLIProxyAPIConfig",
        "default_base_url": cliproxyapi.BASE_URL,
        "default_model": cliproxyapi.DEFAULT_MODEL,
        "live_models": True,
        "allow_manual_model": True,
        # The proxy's /models is the catalog; no static list, as in agent-cli.
        "models": {},
    },
    # OpenAI's own platform, spoken as chat completions like every provider
    # here. Live /models is narrowed to chat models; the built-ins lead the
    # picker and are the fallback when the call cannot be made.
    openai.PROVIDER_ID: {
        "label": "OpenAI", "aliases": openai.ALIASES, "api_key_env": "OPENAI_API_KEY",
        "config_class": "OpenAIConfig", "default_base_url": openai.BASE_URL,
        "default_model": openai.DEFAULT_MODEL,
        "live_models": True, "allow_manual_model": True,
        "models": _static_models(openai.MODELS),
    },
    # Anthropic through its OpenAI-compatible endpoint: the Messages API host
    # also answers /v1/chat/completions with Bearer auth. Thinking is adaptive
    # there by default and `reasoning_effort` is ignored by that layer (see the
    # client). Only the catalog call differs.
    anthropic.PROVIDER_ID: {
        "label": "Anthropic", "aliases": anthropic.ALIASES, "api_key_env": "ANTHROPIC_API_KEY",
        "config_class": "AnthropicConfig", "default_base_url": anthropic.BASE_URL,
        "default_model": anthropic.DEFAULT_MODEL,
        "live_models": True, "allow_manual_model": True,
        "models": _static_models(anthropic.MODELS),
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


# Provider map used across the app. ``models`` starts as the module's curated
# list (empty for the live-only providers) and is replaced by the resolved
# catalog once ``refresh_live_models`` has asked the endpoint.
PROVIDERS = copy.deepcopy(_BUILTIN_PROVIDERS)


def _builtin_models(provider: str) -> Dict[str, Any]:
    return copy.deepcopy(_BUILTIN_PROVIDERS[provider]["models"])


def normalize_catalog_metadata(raw: Any) -> Dict[str, Any]:
    """Validate optional endpoint metadata before UI or request construction.

    Parsing is Kimi Code's current ``/models`` codec from agent-cli
    (``KimiCodeModelEntry.from_payload``); this keeps the dict shape the
    registry, the settings editors and the clients read. Registry entries
    carry ``model_name`` rather than ``id``, and a malformed value must
    degrade to "no metadata", never fail the caller.
    """
    if not isinstance(raw, dict):
        return {}
    payload = dict(raw)
    model_id = payload.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        payload["id"] = "entry"
    # The codec tests membership in a set; an unhashable value would raise
    # instead of being dropped.
    if not isinstance(payload.get("supports_thinking_type"), str):
        payload["supports_thinking_type"] = None
    entry = KimiCodeModelEntry.from_payload(payload)
    if entry is None:
        return {}
    result: Dict[str, Any] = {}
    if entry.display_name:
        result["display_name"] = entry.display_name
    if entry.supports_thinking_type:
        result["supports_thinking_type"] = entry.supports_thinking_type
    if entry.supports_reasoning is not None:
        # agent-cli's picker preselects a tier only for models that reason.
        result["supports_reasoning"] = entry.supports_reasoning
    if entry.context_length:
        result["context_length"] = entry.context_length
    efforts = raw.get("think_efforts")
    if isinstance(efforts, dict) and efforts.get("support") is True:
        clean: Dict[str, Any] = {"support": True, "valid_efforts": list(entry.valid_efforts)}
        if entry.default_effort:
            clean["default_effort"] = entry.default_effort
        result["think_efforts"] = clean
    return result


def _entry_config(entry: ModelCatalogEntry) -> Dict[str, Any]:
    """A catalog entry as the registry's per-model config dict."""
    config: Dict[str, Any] = {"model_name": entry.id}
    if entry.display_name:
        config["display_name"] = entry.display_name
    if isinstance(entry, KimiCodeModelEntry):
        if entry.supports_thinking_type:
            config["supports_thinking_type"] = entry.supports_thinking_type
        if entry.supports_reasoning is not None:
            config["supports_reasoning"] = entry.supports_reasoning
        if entry.context_length:
            config["context_length"] = entry.context_length
        if entry.valid_efforts or entry.default_effort:
            efforts: Dict[str, Any] = {"support": True, "valid_efforts": list(entry.valid_efforts)}
            if entry.default_effort:
                efforts["default_effort"] = entry.default_effort
            config["think_efforts"] = efforts
    return config


# ---------------------------------------------------------------------------
# Catalog resolution: agent-cli's ``/settings provider`` flow, synchronous.
# ---------------------------------------------------------------------------

def _catalog_result(value: Any) -> CatalogFetchResult:
    """Normalize ID lists (tests, older callers) and the structured fetch result."""
    if isinstance(value, CatalogFetchResult):
        return value
    if isinstance(value, (list, tuple)):
        entries: list[ModelCatalogEntry] = []
        for item in value:
            if isinstance(item, ModelCatalogEntry):
                entries.append(item)
            elif isinstance(item, str) and item.strip():
                entries.append(ModelCatalogEntry(id=item.strip()))
        return CatalogFetchResult(entries=tuple(entries), source="live" if entries else "none")
    return CatalogFetchResult(error_kind="malformed", error="unsupported model catalog result")


def _fetch_models_sync(base_url: str, api_key: str, timeout: float = 4.0) -> CatalogFetchResult:
    """Fetch a provider-neutral OpenAI-compatible model catalog."""
    return fetch_model_catalog_sync(base_url, api_key, timeout=timeout)


def _fetch_kimi_code_models_sync(base_url: str, api_key: str, timeout: float = 4.0) -> CatalogFetchResult:
    """Fetch the current Kimi Code model schema."""
    return fetch_kimi_code_catalog_sync(base_url, api_key, timeout=timeout)


def _fetch_anthropic_models_sync(base_url: str, api_key: str, timeout: float = 4.0) -> CatalogFetchResult:
    """Fetch Anthropic's model list with the headers its Models API wants."""
    return anthropic.fetch_catalog_sync(base_url, api_key, timeout=timeout)


def _fetch_catalog(fetcher: Callable[[str, str], Any], base_url: str, api_key: str) -> CatalogFetchResult:
    """agent-cli's ``_fetch_catalog_async`` without the thread: never raises."""
    if not base_url:
        return CatalogFetchResult(error_kind="malformed", error="provider base URL is empty")
    try:
        return _catalog_result(fetcher(base_url, api_key))
    except Exception as exc:
        return CatalogFetchResult(error_kind="network", error=str(exc))


def _kimi_catalog(base_url: str, api_key: str, live: CatalogFetchResult) -> CatalogFetchResult:
    """Persist live Kimi metadata or resolve its last-known-good copy.

    agent-cli's ``_kimi_catalog_for_picker`` without the console: the cache
    file and format are its, scoped to this endpoint and key.
    """
    if live.source == "live" and live.entries:
        try:
            save_cached_kimi_code_catalog(MODEL_CATALOG_PATH, base_url=base_url, api_key=api_key, result=live)
        except OSError:
            pass  # A cache write failure must not block model selection.
        return live
    cached = load_cached_kimi_code_catalog(MODEL_CATALOG_PATH, base_url=base_url, api_key=api_key)
    return kimi_code.resolve_catalog(live, cached)


def resolve_provider_catalog(provider: str, base_url: str, api_key: str) -> CatalogFetchResult:
    """One provider's model catalog, resolved as agent-cli's provider flow does it.

    - Kimi Code: the account-aware ``/models``; on failure the last-known-good
      copy for this endpoint and key (``source == "cache"``), unless the
      failure was an HTTP client error.
    - ACRC, OpenAI, Anthropic: the endpoint's own list with the module's
      display names overlaid and the default first, or the module's built-in
      list with the error carried along when the call cannot be made.
      OpenAI's is narrowed to chat models; Anthropic's comes from the native
      Models API with its own headers.
    - Qwen: the module's curated list; nothing is fetched.
    - OpenRouter, CLIProxyAPI, Copilot: exactly what the endpoint lists.
    """
    provider = _normalize_provider_key(provider)
    if provider == "kimicli":
        return _kimi_catalog(base_url, api_key, _fetch_catalog(_fetch_kimi_code_models_sync, base_url, api_key))
    if provider == acrc.PROVIDER_ID:
        return acrc.resolve_catalog(_fetch_catalog(_fetch_models_sync, base_url, api_key))
    if provider == qwen.PROVIDER_ID:
        return qwen.catalog()
    if provider == openai.PROVIDER_ID:
        return openai.resolve_catalog(_fetch_catalog(_fetch_models_sync, base_url, api_key))
    if provider == anthropic.PROVIDER_ID:
        return anthropic.resolve_catalog(_fetch_catalog(_fetch_anthropic_models_sync, base_url, api_key))
    return _fetch_catalog(_fetch_models_sync, base_url, api_key)


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


def fetch_openrouter_endpoints(base_url: str, api_key: str, model_id: str) -> tuple[openrouter.OpenRouterEndpoint, ...]:
    """The upstreams OpenRouter can route ``model_id`` to, with price, context and caching.

    agent-cli's endpoint discovery, so the order is its picker order (cheapest
    input first). Empty when the endpoint cannot be listed.
    """
    if not base_url or not model_id:
        return ()
    return openrouter.fetch_endpoints_sync(model_id, api_key, base_url=base_url).entries


def fetch_openrouter_upstreams(base_url: str, api_key: str, model_id: str) -> list[str]:
    """The routing slugs of ``fetch_openrouter_endpoints``."""
    return [entry.tag for entry in fetch_openrouter_endpoints(base_url, api_key, model_id)]


def refresh_live_models(provider: str, *, force: bool = False) -> bool:
    """Resolve one provider's catalog into ``PROVIDERS[provider]["models"]``.

    ``resolve_provider_catalog`` decides what is shown, exactly as agent-cli's
    provider flow does; this only places it in the registry the pickers,
    editors and clients read, and memoizes a successful fetch per process for
    one endpoint and key. There is no git-tools list of its own: nothing is
    merged, remembered or retained across a failed fetch beyond the modules'
    built-in lists and Kimi's on-disk last-known-good copy.

    Returns ``True`` when the endpoint answered (or did so earlier in this
    process for the same endpoint and key); ``False`` for unknown or curated
    providers, failed fetches, and a stale Kimi copy.
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
        PROVIDERS[provider]["models"] = _builtin_models(provider)
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

    catalog = resolve_provider_catalog(provider, base_url, api_key)
    PROVIDERS[provider]["models"] = (
        {entry.id: _entry_config(entry) for entry in catalog.entries}
        if catalog.entries
        else _builtin_models(provider)
    )
    if catalog.source == "live" and catalog.error_kind is None:
        _LIVE_REFRESH_ERRORS.pop(provider, None)
        _LIVE_REFRESHED.add(provider)
        _LIVE_REFRESH_IDENTITIES[provider] = identity
        return True
    _LIVE_REFRESH_ERRORS[provider] = LiveModelRefreshError(
        kind=catalog.error_kind or "unknown",
        message=catalog.error or "live model discovery failed",
        status=catalog.status,
        retained_live_catalog=catalog.source == "cache",
    )
    _LIVE_REFRESHED.discard(provider)
    _LIVE_REFRESH_IDENTITIES.pop(provider, None)
    return False


def provider_allows_manual_model(provider: str) -> bool:
    """Return whether the provider picker accepts arbitrary model IDs."""
    return _normalize_provider_key(provider) in MANUAL_MODEL_PROVIDERS


__all__ = [
    "ANTHROPIC_API_VERSION",
    "DEFAULT_OPENROUTER_MODEL",
    "LIVE_MODEL_PROVIDERS",
    "LiveModelRefreshError",
    "MANUAL_MODEL_PROVIDERS",
    "MODEL_CATALOG_PATH",
    "PROVIDER_ALIASES",
    "ProviderCatalogSnapshot",
    "PROVIDERS",
    "fetch_openrouter_endpoints",
    "fetch_openrouter_upstreams",
    "get_live_model_refresh_error",
    "normalize_catalog_metadata",
    "provider_allows_manual_model",
    "refresh_live_models",
    "resolve_provider_catalog",
    "restore_provider_catalog",
    "snapshot_provider_catalog",
]

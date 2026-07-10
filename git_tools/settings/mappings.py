"""Provider and model definitions.

Provider metadata — the API-key env var, the config class, and the curated
model list for fixed-catalogue providers — lives in code here. There is no
external ``mappings.json`` to copy or maintain in the repo.

OpenRouter is the open-ended exception: its catalogue is huge, so users add
model slugs interactively via ``git-tools settings`` (or ``--model`` / the
``GIT_TOOLS_DEFAULT_MODEL`` env var). Custom slugs entered in ``settings`` are
persisted to ``~/.git-tools/models.json`` — a small user file alongside
``settings.env``, created at runtime and never committed — and merged into the
OpenRouter model list on load. When nothing is configured, OpenRouter defaults
to ``anthropic/claude-sonnet-4.6``.

CLIProxyAPI is live-discovered: ``refresh_live_models`` asks the local proxy
for its ``/models`` catalogue and swaps it into PROVIDERS in place, so the
pickers and ``--model`` validation always reflect what the proxy actually
serves. The static entries below are only the offline fallback.
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import typer

# OpenRouter model used when nothing else is configured.
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"

# User settings file holding custom OpenRouter model slugs. Kept inside
# ~/.git-tools/ so a full reset stays a single `rm -rf ~/.git-tools`.
USER_MODELS_PATH = Path.home() / ".git-tools" / "models.json"

# Providers whose OpenAI-compatible endpoint can enumerate its own models
# (GET {base_url}/models). Their static entries are an offline fallback.
LIVE_MODEL_PROVIDERS = ("cliproxyapi",)

# Live-discovered models matching these prefixes are effort-capable; they get
# this reasoning effort as their per-model default (same convention as the
# static entries below).
_EFFORT_CAPABLE_PREFIXES = ("gpt-5",)
_LIVE_EFFORT_DEFAULT = "xhigh"

# Built-in provider definitions (source of truth).
_BUILTIN_PROVIDERS: Dict[str, Any] = {
    "openrouter": {
        "api_key_env": "OPENROUTER_API_KEY",
        "config_class": "OpenRouterConfig",
        "models": {
            DEFAULT_OPENROUTER_MODEL: {
                "model_name": DEFAULT_OPENROUTER_MODEL,
                "data_collection": "deny",
            },
        },
    },
    "kimicli": {
        "api_key_env": "KIMICODE_API_KEY",
        "config_class": "KimiCLIConfig",
        "models": {
            "kimi-k2.5": {"model_name": "kimi-k2.5"},
        },
    },
    "cliproxyapi": {
        "api_key_env": "CLIPROXYAPI_API_KEY",
        "config_class": "CLIProxyAPIConfig",
        "models": {
            "gpt-5.6-sol": {"model_name": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
            "gpt-5.5": {"model_name": "gpt-5.5", "reasoning_effort": "xhigh"},
            "gpt-5.4": {"model_name": "gpt-5.4", "reasoning_effort": "xhigh"},
        },
    },
}


def _openrouter_model_entry(slug: str) -> Dict[str, Any]:
    """Model entry for a free-form OpenRouter slug (privacy-preserving default)."""
    return {"model_name": slug, "data_collection": "deny"}


def _load_user_openrouter_models() -> List[str]:
    """Return the user's saved OpenRouter model slugs (empty on any problem)."""
    if not USER_MODELS_PATH.exists():
        return []

    try:
        data = json.loads(USER_MODELS_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        typer.echo(
            typer.style(
                f"Warning: Error loading {USER_MODELS_PATH.name}: {e}",
                fg=typer.colors.YELLOW,
            )
        )
        return []

    models = data.get("openrouter") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return []

    # Clean, de-duplicated, order-preserving slugs.
    seen: set = set()
    result: List[str] = []
    for item in models:
        if not isinstance(item, str):
            continue
        slug = item.strip()
        if slug and slug not in seen:
            seen.add(slug)
            result.append(slug)
    return result


def _build_providers() -> Dict[str, Any]:
    """Assemble PROVIDERS: built-in definitions plus user OpenRouter models."""
    providers = copy.deepcopy(_BUILTIN_PROVIDERS)
    openrouter_models = providers["openrouter"]["models"]
    for slug in _load_user_openrouter_models():
        openrouter_models.setdefault(slug, _openrouter_model_entry(slug))
    return providers


# Provider map used across the app.
PROVIDERS = _build_providers()


def _live_model_entry(model_id: str) -> Dict[str, Any]:
    """Model entry for a live-discovered model id."""
    entry: Dict[str, Any] = {"model_name": model_id}
    if model_id.startswith(_EFFORT_CAPABLE_PREFIXES):
        entry["reasoning_effort"] = _LIVE_EFFORT_DEFAULT
    return entry


def fetch_live_models(base_url: str, api_key: str, timeout: float = 3.0) -> List[str]:
    """GET ``{base_url}/models`` and return the model ids ([] on any failure).

    Stdlib-only on purpose; failures — proxy down, bad key, non-OpenAI shape —
    all degrade to [] so callers keep the static fallback catalogue."""
    import urllib.request

    if not base_url:
        return []
    url = base_url.rstrip("/") + "/models"
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    ids = [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]
    return sorted(dict.fromkeys(ids))


# Providers already refreshed this process — one fetch is enough for a menu
# session or a content command, and keeps repeat pickers snappy.
_LIVE_REFRESHED: set = set()


def refresh_live_models(provider: str, *, force: bool = False) -> bool:
    """Swap a live provider's catalogue into PROVIDERS from its /models list.

    Static entries still served live keep their metadata and priority order
    (so the offline default stays the preferred first entry); models the
    endpoint no longer serves are dropped; newly served ones are appended.
    No-op (returns False) for non-live providers or when the fetch fails —
    the static fallback catalogue stays in place.
    """
    provider = str(provider).strip().lower()
    if provider not in LIVE_MODEL_PROVIDERS:
        return False
    if provider in _LIVE_REFRESHED and not force:
        return True

    # Runtime import: settings.py imports this module at load time.
    from .settings import load_provider_config

    try:
        config = load_provider_config(provider)
    except Exception:
        return False
    live = fetch_live_models(config.base_url or "", config.api_key or "")
    if not live:
        return False

    static = PROVIDERS[provider]["models"]
    merged: Dict[str, Any] = {}
    for key, entry in static.items():
        if entry.get("model_name") in live:
            merged[key] = entry
    for model_id in live:
        merged.setdefault(model_id, _live_model_entry(model_id))
    PROVIDERS[provider]["models"] = merged
    _LIVE_REFRESHED.add(provider)
    return True


def add_user_openrouter_model(slug: str) -> bool:
    """Persist a custom OpenRouter model slug and expose it in the current run.

    Writes to ``~/.git-tools/models.json`` and mirrors the slug into the
    in-memory PROVIDERS map so it is selectable immediately without a restart.

    Returns:
        True if a new slug was saved, False for blank input or a duplicate.
    """
    slug = (slug or "").strip()
    if not slug:
        return False

    saved = _load_user_openrouter_models()
    is_new = slug not in saved
    if is_new:
        saved.append(slug)
        USER_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_MODELS_PATH.write_text(json.dumps({"openrouter": saved}, indent=2) + "\n")

    # Reflect it in the loaded map so the current session picks it up.
    PROVIDERS["openrouter"]["models"].setdefault(slug, _openrouter_model_entry(slug))
    return is_new

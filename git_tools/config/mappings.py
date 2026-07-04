"""Provider and model definitions.

Provider metadata — the API-key env var, the config class, and the curated
model list for fixed-catalogue providers — lives in code here. There is no
external ``mappings.json`` to copy or maintain in the repo.

OpenRouter is the open-ended exception: its catalogue is huge, so users add
model slugs interactively via ``git-tools config`` (or ``--model`` / the
``GIT_TOOLS_DEFAULT_MODEL`` env var). Custom slugs entered in ``config`` are
persisted to ``~/.git-tools/models.json`` — a small user config file alongside
``config.env``, created at runtime and never committed — and merged into the
OpenRouter model list on load. When nothing is configured, OpenRouter defaults
to ``anthropic/claude-sonnet-4.6``.
"""

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import typer

# OpenRouter model used when nothing else is configured.
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"

# User config file holding custom OpenRouter model slugs. Kept inside
# ~/.git-tools/ so a full reset stays a single `rm -rf ~/.git-tools`.
USER_MODELS_PATH = Path.home() / ".git-tools" / "models.json"

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
            "gpt-5.5": {"model_name": "gpt-5.5", "reasoning_effort": "xhigh"},
            "gpt-5.4-codex": {"model_name": "gpt-5.4-codex", "reasoning_effort": "xhigh"},
            "gpt-5.3-codex": {"model_name": "gpt-5.3-codex", "reasoning_effort": "xhigh"},
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

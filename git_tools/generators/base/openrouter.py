"""OpenRouter request-body helpers: provider routing preferences per model."""

from typing import Any, Dict, Optional


def _get_openrouter_extra_body(
    model_name: str,
    base_extra_body: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return model-specific extra_body for OpenRouter.

    Reads provider configuration from the model's provider definition if
    available, otherwise falls back to the provided base_extra_body.

    Args:
        model_name: The model name/identifier
        base_extra_body: Default extra_body configuration
        model_config: Optional per-model config from the PROVIDERS map

    Returns:
        Dict with provider routing configuration
    """
    extra_body = base_extra_body.copy()
    provider_preferences: Dict[str, Any] = {
        "allow_fallbacks": True,
        "data_collection": model_config.get("data_collection", "deny") if model_config else "deny",
    }

    # Empty strings and empty arrays should behave like "unspecified" so
    # OpenRouter can use its default routing instead of an accidental filter.
    if model_config and "provider_config" in model_config:
        provider_preferences.update(
            _sanitize_openrouter_provider_config(model_config["provider_config"])
        )

    if provider_preferences:
        extra_body["provider"] = provider_preferences

    return extra_body


def _sanitize_openrouter_provider_config(provider_config: Any) -> Dict[str, Any]:
    """Drop empty provider preference values before sending them to OpenRouter."""
    if not isinstance(provider_config, dict):
        return {}

    sanitized: Dict[str, Any] = {}
    for key, value in provider_config.items():
        if value is None:
            continue

        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                sanitized[key] = stripped
            continue

        if isinstance(value, list):
            filtered = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, str):
                    item = item.strip()
                    if not item:
                        continue
                filtered.append(item)
            if filtered:
                sanitized[key] = filtered
            continue

        if isinstance(value, dict):
            nested = _sanitize_openrouter_provider_config(value)
            if nested:
                sanitized[key] = nested
            continue

        sanitized[key] = value

    return sanitized

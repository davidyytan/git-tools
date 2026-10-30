"""git-tools settings wrapper around agent-core's provider request policy."""

import uuid
from typing import Any, Dict, Optional

from git_tools.settings.mappings import PROVIDERS, is_openai_reasoning_model
from git_tools.settings.settings import normalize_provider_name, settings

# Like agent-core's general-role key, stable across calls in this process.
# git-tools has no role-specific sessions and runs host-local proxies unchanged.
_CLIPROXY_SESSION_ID = f"git-tools-{uuid.uuid4().hex[:16]}"


def create_chat_client(provider: str, **kwargs: Any):
    """Lazy import keeps the stdlib-only bump engine independent of the SDK."""
    from .transport import create_chat_client as create

    return create(provider, **kwargs)


class ChatClientMixin:
    """Wrap resolved git-tools settings around the lifted provider transport."""

    def _initialize_service(
        self,
        provider: str,
        model: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> bool:
        try:
            provider = normalize_provider_name(provider)
            provider_config = self.get_provider_config(provider)
            model_details = PROVIDERS[provider]["models"].get(model, {})
            model_to_use = model_details.get("model_name", model)
            if provider == "openrouter":
                self.chatclient = self._create_openrouter_client(model_to_use, provider_config, temperature, max_tokens)
            elif provider in {"kimicli", "kimicode"}:
                self.chatclient = self._create_kimicli_client(model_to_use, provider_config, temperature, max_tokens)
            elif provider == "cliproxyapi":
                self.chatclient = self._create_cliproxy_client(model_to_use, provider_config, temperature, max_tokens)
            elif provider in {"acrc", "copilot", "qwen", "qwencode", "openai", "anthropic", "zcode"}:
                self.chatclient = self._create_compatible_client(provider, model_to_use, provider_config, temperature, max_tokens)
            else:
                raise ValueError(f"Unsupported provider: {provider}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to initialize {provider} service: {type(exc).__name__}")
            self.logger.debug(f"Initialization error details: {exc}")
            return False

    def _add_optional_params(
        self,
        kwargs: Dict[str, Any],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> None:
        """Keep git-tools budgets; the application, not the SDK, owns retries."""
        kwargs["temperature"] = temperature if temperature is not None else settings.default_temperature
        kwargs["max_tokens"] = max_tokens if max_tokens is not None else settings.default_max_tokens
        kwargs["max_retries"] = 0

    def _create_provider_client(
        self, provider: str, model: str, config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        from .transport import provider_request_options

        kwargs = {"model": model, "api_key": config.api_key, "base_url": config.base_url}
        self._add_optional_params(kwargs, temperature, max_tokens)
        # One prompt-cache identity per generator invocation, reused by retries.
        cache_key = None
        if provider in {"kimicli", "kimicode"}:
            cache_key = getattr(self, "_kimi_prompt_cache_key", None)
            if cache_key is None:
                cache_key = self._kimi_prompt_cache_key = uuid.uuid4().hex
        temperature_value = kwargs.pop("temperature")
        kwargs.update(provider_request_options(
            provider, model, temperature=temperature_value,
            effort=settings.default_reasoning_effort,
            kimi_thinking=settings.kimi_thinking,
            openrouter_provider=settings.openrouter_provider,
            cache_key=cache_key, session_key=_CLIPROXY_SESSION_ID,
        ))
        return create_chat_client(provider, **kwargs)

    def _create_openrouter_client(
        self, model_to_use: str, provider_config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        # Routing is the operator's explicit pin only, not hidden model metadata.
        return self._create_provider_client("openrouter", model_to_use, provider_config, temperature, max_tokens)

    def _create_kimicli_client(
        self, model_to_use: str, provider_config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        # Like agent-core, runtime thinking is controlled by resolved settings;
        # catalog capabilities are a picker concern, not another request knob.
        return self._create_provider_client("kimicli", model_to_use, provider_config, temperature, max_tokens)

    def _create_compatible_client(
        self, provider: str, model: str, config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        return self._create_provider_client(provider, model, config, temperature, max_tokens)

    def _get_model_config(self, provider: str, model_name: str) -> Optional[Dict[str, Any]]:
        for model_data in PROVIDERS.get(provider, {}).get("models", {}).values():
            if model_data.get("model_name") == model_name:
                return model_data
        return None

    def _resolve_reasoning_effort(self, model_to_use: str) -> Optional[str]:
        effort = (settings.default_reasoning_effort or "").strip().lower()
        if not effort or effort == "none" or not is_openai_reasoning_model(model_to_use):
            return None
        return effort

    def _create_cliproxy_client(
        self, model_to_use: str, provider_config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        return self._create_provider_client("cliproxyapi", model_to_use, provider_config, temperature, max_tokens)

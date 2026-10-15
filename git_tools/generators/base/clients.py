"""LangChain chat-client construction for each supported provider."""

import uuid
from typing import Any, Dict, Optional

from git_tools.settings.mappings import PROVIDERS
from git_tools.settings.settings import normalize_provider_name, settings

from .openrouter import _get_openrouter_extra_body

# Stable per-process session id for CLIProxyAPI prompt-cache affinity. CLIProxyAPI
# keys reasoning/cache continuity off the Session_id header, so one id per run keeps
# a single git-tools invocation on the same upstream session.
_CLIPROXY_SESSION_ID = f"git-tools-{uuid.uuid4().hex[:16]}"


class ChatClientMixin:
    """Build the provider-specific ``ChatOpenAI`` client for a resolved model."""

    def _initialize_service(
        self,
        provider: str,
        model: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> bool:
        """Initialize LangChain chat client for the selected provider"""
        try:
            provider = normalize_provider_name(provider)
            provider_config = self.get_provider_config(provider)
            model_details = PROVIDERS[provider]["models"].get(model, {})
            model_to_use = model_details.get("model_name", model)

            if provider == "openrouter":
                self.chatclient = self._create_openrouter_client(
                    model_to_use, provider_config, temperature, max_tokens
                )
            elif provider == "kimicli":
                self.chatclient = self._create_kimicli_client(
                    model_to_use, provider_config, temperature, max_tokens
                )
            elif provider == "cliproxyapi":
                self.chatclient = self._create_cliproxy_client(
                    model_to_use, provider_config, temperature, max_tokens
                )
            elif provider in {"acrc", "copilot", "qwen"}:
                self.chatclient = self._create_compatible_client(
                    provider, model_to_use, provider_config, temperature, max_tokens
                )
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            return True

        except Exception as e:
            # Log error type without full message to avoid potential credential leaks
            self.logger.error(
                f"Failed to initialize {provider} service: {type(e).__name__}"
            )
            self.logger.debug(f"Initialization error details: {e}")
            return False

    def _add_optional_params(
        self,
        kwargs: Dict[str, Any],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> None:
        """Add optional parameters to kwargs dict using settings as fallback."""
        kwargs["temperature"] = temperature if temperature is not None else settings.default_temperature
        kwargs["max_tokens"] = max_tokens if max_tokens is not None else settings.default_max_tokens
        kwargs["max_retries"] = settings.default_max_retries

    def _create_openrouter_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for OpenRouter"""
        from langchain_openai import ChatOpenAI

        base_extra_body: Dict[str, Any] = {
            "usage": {"include": True},
        }

        # Get model config from PROVIDERS to pass provider_config
        model_config = None
        for model_key, model_data in PROVIDERS["openrouter"]["models"].items():
            if model_data.get("model_name") == model_to_use:
                model_config = model_data
                break

        extra_body = _get_openrouter_extra_body(
            model_to_use, base_extra_body, model_config
        )

        pin = settings.openrouter_provider
        if pin and pin.lower() not in {"any", "unpinned", "default"}:
            extra_body["provider"]["only"] = [pin]
            extra_body["provider"]["allow_fallbacks"] = False
        if settings.default_reasoning_effort:
            extra_body["reasoning"] = {"effort": settings.default_reasoning_effort}
        kwargs = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "extra_body": extra_body,
        }

        self._add_optional_params(kwargs, temperature, max_tokens)
        return ChatOpenAI(**kwargs)

    def _create_kimicli_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for the Kimi CLI-compatible endpoint."""
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "default_headers": {"User-Agent": "KimiCLI/1.3"},
            "extra_body": {
                "thinking": {"type": "disabled"},
            },
        }

        from git_tools.settings.mappings import normalize_catalog_metadata

        metadata = normalize_catalog_metadata(self._get_model_config("kimicli", model_to_use) or {})
        mode = metadata.get("supports_thinking_type")
        effort = settings.default_reasoning_effort
        efforts = metadata.get("think_efforts", {})
        valid_efforts = efforts.get("valid_efforts", []) if isinstance(efforts, dict) else []
        if effort and valid_efforts and effort not in valid_efforts:
            raise ValueError("Selected Kimi effort is not supported by this model")
        enabled = settings.kimi_thinking or (settings.kimi_thinking is None and effort)
        if mode == "only":
            enabled = True
        elif mode == "no":
            enabled = False
        if enabled:
            thinking = {"type": "enabled", "keep": "all"}
            if effort:
                thinking["effort"] = effort
            kwargs["extra_body"]["thinking"] = thinking

        # Kimi Code currently rejects every other value (HTTP 400: "only 0.6
        # is allowed for this model"). Enforce the provider requirement even if
        # a stale setting or explicit --temp override supplies another value.
        self._add_optional_params(kwargs, 0.6, max_tokens)
        return ChatOpenAI(**kwargs)

    def _create_compatible_client(
        self, provider: str, model: str, config: Any,
        temperature: Optional[float], max_tokens: Optional[int],
    ):
        """Text-generation transport for the remaining OpenAI-compatible providers."""
        from langchain_openai import ChatOpenAI

        kwargs = {"model": model, "api_key": config.api_key, "base_url": config.base_url}
        self._add_optional_params(kwargs, temperature, max_tokens)
        effort = settings.default_reasoning_effort
        if provider == "qwen":
            body: Dict[str, Any] = {"preserve_thinking": True}
            if effort:
                if model.lower().startswith("qwen3.8-max"):
                    body["reasoning_effort"] = effort
                elif model.lower().startswith("qwen") or model.lower() == "coder-model":
                    body["enable_thinking"] = effort != "none"
            kwargs["extra_body"] = body
        elif effort and model.lower().startswith(("gpt-", "o1", "o3", "o4", "codex-")):
            kwargs["reasoning_effort"] = effort
        return ChatOpenAI(**kwargs)

    def _get_model_config(
        self, provider: str, model_name: str
    ) -> Optional[Dict[str, Any]]:
        """Return the PROVIDERS model entry whose model_name matches.

        Used to read per-model knobs (e.g. OpenRouter provider routing or the
        CLIProxyAPI reasoning_effort default) for a resolved model name.
        """
        models = PROVIDERS.get(provider, {}).get("models", {})
        for model_data in models.values():
            if model_data.get("model_name") == model_name:
                return model_data
        return None

    def _resolve_reasoning_effort(
        self, model_config: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """Resolve reasoning effort: env/settings override > per-model default.

        ``GIT_TOOLS_REASONING_EFFORT`` (via ``settings.default_reasoning_effort``)
        wins for models that declare ``reasoning_effort`` in their provider
        definition; otherwise the model's per-model default applies (e.g. the
        gpt-5 family defaults to ``xhigh``).
        """
        if not model_config or not model_config.get("reasoning_effort"):
            return None
        if settings.default_reasoning_effort:
            return settings.default_reasoning_effort.strip().lower() or None
        return str(model_config["reasoning_effort"]).strip().lower() or None

    def _create_cliproxy_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for the CLIProxyAPI endpoint.

        CLIProxyAPI fronts CLI-authenticated Codex/GPT-5 models. Those reasoning
        models reject a custom ``temperature`` (only the server default is valid),
        so it is omitted for the gpt-5 family. The completion cap covers reasoning
        + visible tokens together, so it relies on the global ``default_max_tokens``
        (32k) being large enough to leave room for the answer. A stable
        ``Session_id`` header keeps the run on one upstream session, and
        ``reasoning_effort`` (default ``xhigh`` for the gpt-5 family) is forwarded when set.
        """
        from langchain_openai import ChatOpenAI

        model_config = self._get_model_config("cliproxyapi", model_to_use)

        kwargs: Dict[str, Any] = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "default_headers": {"Session_id": _CLIPROXY_SESSION_ID},
            "max_tokens": max_tokens if max_tokens is not None else settings.default_max_tokens,
            "max_retries": settings.default_max_retries,
        }

        # gpt-5 / Codex reasoning models reject a custom temperature; omit it so the
        # server default applies. Non-reasoning models keep the configured value.
        is_reasoning_model = str(model_to_use).strip().lower().startswith("gpt-5")
        if not is_reasoning_model:
            kwargs["temperature"] = (
                temperature if temperature is not None else settings.default_temperature
            )

        reasoning_effort = self._resolve_reasoning_effort(model_config)
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        return ChatOpenAI(**kwargs)

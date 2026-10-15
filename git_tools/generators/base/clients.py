"""LangChain chat-client construction for each supported provider."""

import uuid
from typing import Any, Dict, Optional

from git_tools.settings.mappings import PROVIDERS, is_openai_reasoning_model
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
            elif provider in {"acrc", "copilot", "qwen", "openai", "anthropic"}:
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
            "extra_body": {},
        }

        from git_tools.settings.mappings import normalize_catalog_metadata

        metadata = normalize_catalog_metadata(self._get_model_config("kimicli", model_to_use) or {})
        mode = metadata.get("supports_thinking_type")
        # Kimi has no "none" tier: as in agent-core, `none` is absence on the
        # wire, so it must not switch thinking on with an effort the API rejects.
        effort = settings.default_reasoning_effort
        if effort == "none":
            effort = None
        # The catalog's declared mode wins, then an explicit off, then the
        # agent-core rule that a tier alone switches thinking on. With neither
        # configured nothing thinking-related is sent and Kimi applies the
        # model's own default, exactly as agent-core does.
        if mode == "only":
            state = "enabled"
        elif mode == "no" or settings.kimi_thinking is False:
            state = "disabled"
        elif settings.kimi_thinking or effort:
            state = "enabled"
        else:
            state = None
        if state == "disabled":
            kwargs["extra_body"]["thinking"] = {"type": "disabled"}
        elif state == "enabled":
            # The tier is checked only when it will be sent. With thinking off
            # nothing thinking-related reaches the wire (as in agent-core, where
            # an explicit off takes precedence over the effort setting), so a
            # stale override must not block the client.
            efforts = metadata.get("think_efforts", {})
            valid_efforts = efforts.get("valid_efforts", []) if isinstance(efforts, dict) else []
            if effort and valid_efforts and effort not in valid_efforts:
                raise ValueError("Selected Kimi effort is not supported by this model")
            thinking = {"type": "enabled", "keep": "all"}
            if effort:
                thinking["effort"] = effort
            kwargs["extra_body"]["thinking"] = thinking

        # The configured temperature (0.6 by default) goes through like for
        # every other provider; Kimi answers with its own error if it rejects
        # a value, rather than this client silently overriding the setting.
        self._add_optional_params(kwargs, temperature, max_tokens)
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
        # As in agent-core, "off" is absence on the wire for every provider
        # here (OpenRouter, which has a real `none` tier, is handled apart).
        tier = None if effort == "none" else effort
        if provider == "qwen":
            # DashScope keeps thinking off by default on the qwen3-max/plus/flash
            # families; preserve_thinking is its equivalent of Kimi's keep: all.
            body: Dict[str, Any] = {"preserve_thinking": True}
            if tier:
                if model.lower().startswith("qwen3.8-max"):
                    body["reasoning_effort"] = tier
                elif model.lower().startswith("qwen") or model.lower() == "coder-model":
                    # Older hybrids have no effort ladder; it collapses to on/off.
                    body["enable_thinking"] = True
            kwargs["extra_body"] = body
        elif provider == "openai":
            # Only the reasoning families read the native top-level field;
            # OpenAI returns 400 for it on gpt-4.x/4o/3.5, so those never get
            # it. "none" is absence on the wire, i.e. the server default (GPT-6
            # rejects an explicit none). Reasoning families also accept only
            # the server's default temperature, so it is omitted for them.
            # Chat goes to /chat/completions; the pinned langchain-openai has
            # no Responses API routing to turn off, so no provider-specific
            # class is needed.
            if is_openai_reasoning_model(model):
                if effort and effort != "none":
                    kwargs["reasoning_effort"] = effort
                kwargs.pop("temperature", None)
        elif provider == "anthropic":
            # Anthropic's OpenAI-compatible layer ("OpenAI SDK compatibility"
            # docs) returns 400 on Claude 4.7+ for any temperature below 1, so
            # none is ever sent. It lists `reasoning_effort` as ignored: the
            # tier is still forwarded, for parity with agent-core and in case
            # the layer starts honouring it, while thinking itself is adaptive
            # and on by default. The one tier that acts is "none", sent as the
            # layer's documented `thinking` switch.
            kwargs.pop("temperature", None)
            if effort == "none":
                kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
            elif effort:
                kwargs["reasoning_effort"] = effort
        elif tier and is_openai_reasoning_model(model):
            # Proxies in front of OpenAI (Copilot) and mixed endpoints (ACRC):
            # only the reasoning families read the field; gpt-4.x would 400.
            kwargs["reasoning_effort"] = tier
        return ChatOpenAI(**kwargs)

    def _get_model_config(
        self, provider: str, model_name: str
    ) -> Optional[Dict[str, Any]]:
        """Return the PROVIDERS model entry whose model_name matches.

        Used to read per-model knobs (e.g. OpenRouter provider routing or Kimi
        catalog metadata) for a resolved model name.
        """
        models = PROVIDERS.get(provider, {}).get("models", {})
        for model_data in models.values():
            if model_data.get("model_name") == model_name:
                return model_data
        return None

    def _resolve_reasoning_effort(self, model_to_use: str) -> Optional[str]:
        """The configured tier for a proxied model that reads it, else nothing.

        As in agent-core there is no implicit default: ``GIT_TOOLS_REASONING_EFFORT``
        (``settings.default_reasoning_effort``) is forwarded when set and the
        model is one of OpenAI's reasoning families; ``none`` is absence on the
        wire.
        """
        effort = (settings.default_reasoning_effort or "").strip().lower()
        if not effort or effort == "none" or not is_openai_reasoning_model(model_to_use):
            return None
        return effort

    def _create_cliproxy_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for the CLIProxyAPI endpoint.

        CLIProxyAPI fronts CLI-authenticated Codex/GPT models. The configured
        ``temperature`` is sent to every model: the proxy's Codex backend
        accepted 0.6 on gpt-6-astra and gpt-5.6-sol when probed (2026-10-15),
        unlike OpenAI's own platform. The completion cap covers reasoning
        + visible tokens together, so it relies on the global ``default_max_tokens``
        (32k) being large enough to leave room for the answer. A stable
        ``Session_id`` header keeps the run on one upstream session, and the
        configured ``reasoning_effort`` is forwarded to reasoning models when set.
        """
        from langchain_openai import ChatOpenAI

        kwargs: Dict[str, Any] = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "default_headers": {"Session_id": _CLIPROXY_SESSION_ID},
        }
        self._add_optional_params(kwargs, temperature, max_tokens)

        reasoning_effort = self._resolve_reasoning_effort(str(model_to_use))
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort

        return ChatOpenAI(**kwargs)

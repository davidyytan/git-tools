"""Single-turn transport lifted from agent-core's ``agent_core/providers.py``.

The request policy, reasoning-field capture and Kimi usage normalization follow
that module. git-tools supplies its resolved settings, token budget and outer
retry loop; agent-core's session routing, deadline ladder and checkpoint/v1
content-block conversions are deliberately not dependencies of this adapter.
"""

from __future__ import annotations

from typing import Any, ClassVar

from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import _convert_message_to_dict

from git_tools.providers.zcode import resolve_reasoning_effort
from git_tools.settings.mappings import is_openai_reasoning_model


def provider_request_options(
    provider: str,
    model: str,
    *,
    temperature: float,
    effort: str | None,
    kimi_thinking: bool | None = None,
    openrouter_provider: str | None = None,
    cache_key: str | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    """Lift of get_model's mutually exclusive provider request branches.

    Inputs are already resolved by git-tools, so AGENT_* environment variables
    must not leak into this boundary. ``none`` is retained before provider
    dispatch: OpenRouter sends it verbatim, and ZCode maps it to low.
    """
    kwargs: dict[str, Any] = {"temperature": temperature}
    requested_effort = (effort or "").strip().lower() or None
    reasoning_effort = None if requested_effort == "none" else requested_effort
    if provider == "openrouter":
        provider_block: dict[str, Any] = {"data_collection": "deny"}
        slug = (openrouter_provider or "").strip().lower()
        # any/auto are agent-core's values; retain git-tools' old unset aliases.
        if slug and slug not in {"any", "auto", "unpinned", "default"}:
            provider_block["only"] = [slug]
            provider_block["allow_fallbacks"] = False
        else:
            provider_block["allow_fallbacks"] = True
        extra_body: dict[str, Any] = {"provider": provider_block, "usage": {"include": True}}
        if requested_effort:
            extra_body["reasoning"] = {"effort": requested_effort}
        kwargs["extra_body"] = extra_body
    elif provider in {"kimicli", "kimicode"}:
        if not cache_key:
            raise ValueError("Kimi requires an invocation prompt-cache key")
        kwargs["default_headers"] = {"User-Agent": "KimiCLI/1.52.0"}
        extra_body = {"prompt_cache_key": cache_key}
        if kimi_thinking is False:
            extra_body["thinking"] = {"type": "disabled"}
        elif kimi_thinking is True or reasoning_effort:
            thinking: dict[str, Any] = {"type": "enabled", "keep": "all"}
            if reasoning_effort:
                thinking["effort"] = reasoning_effort
            extra_body["thinking"] = thinking
        kwargs["extra_body"] = extra_body
    elif provider in {"qwen", "qwencode"}:
        extra_body = {"preserve_thinking": True}
        if reasoning_effort:
            normalized = model.strip().lower()
            if normalized.startswith("qwen3.8-max"):
                extra_body["reasoning_effort"] = reasoning_effort
            elif normalized.startswith("qwen") or normalized == "coder-model":
                extra_body["enable_thinking"] = True
        kwargs["extra_body"] = extra_body
    elif provider == "zcode":
        kwargs["default_headers"] = {"User-Agent": "ZCode/1.0"}
        kwargs["extra_body"] = {"thinking": {"type": "enabled", "clear_thinking": False}}
        if requested_effort:
            kwargs["reasoning_effort"] = resolve_reasoning_effort(requested_effort)
    elif provider == "openai":
        if reasoning_effort and is_openai_reasoning_model(model, platform=True):
            kwargs["reasoning_effort"] = reasoning_effort
    elif provider == "anthropic":
        kwargs.pop("temperature", None)
        if requested_effort == "none":
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        elif reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
    elif reasoning_effort and is_openai_reasoning_model(model):
        kwargs["reasoning_effort"] = reasoning_effort
    if provider == "cliproxyapi":
        kwargs["default_headers"] = {"Session_id": session_key}
    return kwargs


class ChatCompletionsClient(ChatOpenAI):
    """Pinned-SDK chat transport; retries are owned by ``invoke_llm``."""

    provider_name: ClassVar[str] = ""

    def _use_responses_api(self, payload: dict) -> bool:
        # The pinned SDK has no Responses API. Keep the upstream compatibility
        # providers' explicit guard without importing a newer SDK.
        return False

    def get_token_ids(self, text: str) -> list[int]:
        # Agent-core's _PlainTextTokenCounting, without its truncation module.
        return self._get_encoding_model()[1].encode(text, disallowed_special=())


class ReasoningChatOpenAI(ChatCompletionsClient):
    """Direct response capture/replay lift for ordinary chat messages.

    git-tools invokes non-streaming single turns. The pinned langchain-openai
    lacks upstream's v1 converter and subclassable streaming conversion hook;
    no checkpoint or streaming parity is claimed by this small adapter.
    """

    reasoning_text_field: ClassVar[str] = "reasoning_content"
    reasoning_detail_fields: ClassVar[tuple[str, ...]] = ()
    reasoning_preserves_empty: ClassVar[bool] = False

    def _normalize_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return payload

    def _capture_reasoning(self, source: Any, message: Any) -> None:
        if not isinstance(source, dict) or not isinstance(message, AIMessage):
            return
        for field in (self.reasoning_text_field, *self.reasoning_detail_fields):
            value = source.get(field)
            if isinstance(value, str) or (isinstance(value, list) and value):
                message.additional_kwargs[field] = value

    def _serialize_message(self, message: BaseMessage) -> dict[str, Any]:
        message_dict = _convert_message_to_dict(message)
        if isinstance(message, AIMessage):
            text_field = self.reasoning_text_field
            raw_text = message.additional_kwargs.get(text_field)
            if isinstance(raw_text, str) and (raw_text or self.reasoning_preserves_empty):
                message_dict[text_field] = raw_text
            for field in self.reasoning_detail_fields:
                details = message.additional_kwargs.get(field)
                if isinstance(details, list) and details:
                    message_dict[field] = details
        return message_dict

    def _get_request_payload(self, input_: Any, *, stop: list[str] | None = None, **kwargs: Any) -> dict:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload["messages"] = [self._serialize_message(message) for message in messages]
        return payload

    def _create_chat_result(self, response: Any, generation_info: dict | None = None):
        response_dict = response if isinstance(response, dict) else response.model_dump()
        response_dict = self._normalize_usage(response_dict)
        result = super()._create_chat_result(response_dict, generation_info)
        for generation, choice in zip(result.generations, response_dict.get("choices", [])):
            self._capture_reasoning(choice.get("message"), generation.message)
        return result


class KimiChatOpenAI(ReasoningChatOpenAI):
    provider_name: ClassVar[str] = "kimicode"
    reasoning_preserves_empty: ClassVar[bool] = True

    def _normalize_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload)
        usage = normalized.get("usage")
        if isinstance(usage, dict) and isinstance(usage.get("cached_tokens"), int):
            usage = dict(usage)
            details = usage.get("prompt_tokens_details")
            details = dict(details) if isinstance(details, dict) else {}
            details.setdefault("cached_tokens", usage["cached_tokens"])
            usage["prompt_tokens_details"] = details
            normalized["usage"] = usage
        return normalized


class QwenChatOpenAI(ReasoningChatOpenAI):
    provider_name: ClassVar[str] = "qwencode"


class ACRCChatOpenAI(ReasoningChatOpenAI):
    provider_name: ClassVar[str] = "acrc"


class OpenRouterChatOpenAI(ReasoningChatOpenAI):
    provider_name: ClassVar[str] = "openrouter"
    reasoning_text_field: ClassVar[str] = "reasoning"
    reasoning_detail_fields: ClassVar[tuple[str, ...]] = ("reasoning_details",)


class ZCodeChatOpenAI(ReasoningChatOpenAI):
    provider_name: ClassVar[str] = "zcode"


class AnthropicChatOpenAI(ChatCompletionsClient):
    provider_name: ClassVar[str] = "anthropic"


_MODEL_CLASSES = {
    "acrc": ACRCChatOpenAI,
    "anthropic": AnthropicChatOpenAI,
    "kimicli": KimiChatOpenAI,
    "kimicode": KimiChatOpenAI,
    "openrouter": OpenRouterChatOpenAI,
    "qwen": QwenChatOpenAI,
    "qwencode": QwenChatOpenAI,
    "zcode": ZCodeChatOpenAI,
}


def create_chat_client(provider: str, **kwargs: Any) -> ChatCompletionsClient:
    """Use an explicit endpoint and the upstream provider's response adapter."""
    if not (kwargs.get("base_url") or "").strip():
        raise ValueError(f"No API base configured for provider '{provider}'")
    model = _MODEL_CLASSES.get(provider, ChatCompletionsClient)(**kwargs)
    object.__setattr__(model, "provider_name", provider)
    return model

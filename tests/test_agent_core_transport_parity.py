"""Offline request/response contracts lifted from agent-core provider tests.

Set AGENT_CORE_PROVIDERS_SOURCE to an upstream providers.py to additionally
compare the exact request branch AST. No agent-core modules are imported, and
all HTTP requests below use an in-memory MockTransport.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from git_tools.generators.base import BaseGenerator
from git_tools.generators.base import clients
from git_tools.generators.base.transport import (
    ACRCChatOpenAI, AnthropicChatOpenAI, ChatCompletionsClient,
    KimiChatOpenAI, OpenRouterChatOpenAI, QwenChatOpenAI, ZCodeChatOpenAI,
    create_chat_client, provider_request_options,
)
from git_tools.providers.zcode import EFFORT_TIERS
from git_tools.settings.settings import settings

_CONFIG = SimpleNamespace(api_key="fixture-key", base_url="https://fixture.invalid/v1")
_PRESERVED = {"thinking": {"type": "enabled", "clear_thinking": False}}
_MESSAGES = [SystemMessage(content="Describe the change."), HumanMessage(content="hello")]
_PROVIDERS = {
    "openrouter": "vendor/model", "kimicli": "kimi-for-coding", "qwen": "qwen3.8-max",
    "zcode": "glm-5.3", "openai": "gpt-6-astra", "anthropic": "claude-opus-5-5",
    "acrc": "deepseek-v4.1-flash", "cliproxyapi": "gpt-6-astra", "copilot": "gpt-4.1",
}


def options(provider, model, effort=None, thinking=None, pin=None):
    return provider_request_options(provider, model, temperature=0.6, effort=effort,
                                    kimi_thinking=thinking, openrouter_provider=pin,
                                    cache_key="fixture-cache", session_key="fixture-session")


def make_model(provider, model, **overrides):
    opts = options(provider, model, **overrides)
    return create_chat_client(provider, model=model, api_key="fixture-key", base_url=_CONFIG.base_url,
                              max_tokens=1234, max_retries=0, client=Mock(), async_client=Mock(), **opts)


class SerializedPayloadTests(unittest.TestCase):
    def payload(self, provider, model=None, **overrides):
        return make_model(provider, model or _PROVIDERS[provider], **overrides)._get_request_payload(_MESSAGES)

    def test_all_providers_use_chat_messages_and_token_budget(self):
        classes = {"openrouter": OpenRouterChatOpenAI, "kimicli": KimiChatOpenAI, "qwen": QwenChatOpenAI,
                   "zcode": ZCodeChatOpenAI, "acrc": ACRCChatOpenAI, "anthropic": AnthropicChatOpenAI}
        for provider, name in _PROVIDERS.items():
            with self.subTest(provider=provider):
                model = make_model(provider, name)
                self.assertIsInstance(model, classes.get(provider, ChatCompletionsClient))
                self.assertEqual(model.provider_name, provider)
                payload = model._get_request_payload(_MESSAGES)
                self.assertEqual(payload["messages"], [{"role": "system", "content": "Describe the change."},
                                                       {"role": "user", "content": "hello"}])
                self.assertEqual(payload["max_completion_tokens"], 1234)
                self.assertFalse(payload["stream"])
                self.assertNotIn("input", payload)
                self.assertNotIn("use_responses_api", payload)
                self.assertFalse(model._use_responses_api(payload))
                self.assertEqual(model.max_retries, 0)
                if provider == "anthropic":
                    self.assertNotIn("temperature", payload)
                else:
                    self.assertEqual(payload["temperature"], 0.6)

    def test_zcode_every_supported_tier_on_every_model(self):
        expected = {"none": "low", "minimal": "low", "low": "low", "medium": "high",
                    "high": "high", "xhigh": "max", "max": "max"}
        self.assertEqual(EFFORT_TIERS, expected)
        for name in ("glm-5.3", "glm-5.3-flash", "glm-5.2", "glm-4.7", "manual-fixture"):
            for effort, sent in expected.items():
                with self.subTest(model=name, effort=effort):
                    payload = self.payload("zcode", name, effort=effort)
                    self.assertEqual(payload["extra_body"], _PRESERVED)
                    self.assertEqual(payload["reasoning_effort"], sent)
                    self.assertNotIn("reasoning", payload)
                    self.assertNotIn("enable_thinking", payload)
            self.assertNotIn("reasoning_effort", self.payload("zcode", name))
        self.assertEqual(self.payload("zcode", effort="future-tier")["reasoning_effort"], "future-tier")

    def test_kimi_exact_header_cache_and_exclusive_thinking(self):
        for thinking, effort, expected in (
            (None, None, None), (None, "none", None), (False, "high", {"type": "disabled"}),
            (True, "none", {"type": "enabled", "keep": "all"}),
            (None, "high", {"type": "enabled", "keep": "all", "effort": "high"}),
        ):
            model = make_model("kimicli", "kimi-for-coding", thinking=thinking, effort=effort)
            self.assertEqual(model.default_headers, {"User-Agent": "KimiCLI/1.52.0"})
            payload = model._get_request_payload(_MESSAGES)
            body = {"prompt_cache_key": "fixture-cache"}
            if expected is not None:
                body["thinking"] = expected
            self.assertEqual(payload["extra_body"], body)
            self.assertNotIn("reasoning_effort", payload)

    def test_openrouter_only_explicit_routing_and_none_verbatim(self):
        for pin in (None, "any", "auto", " ANY "):
            body = self.payload("openrouter", effort="none", pin=pin)["extra_body"]
            self.assertEqual(body, {"provider": {"data_collection": "deny", "allow_fallbacks": True},
                                    "usage": {"include": True}, "reasoning": {"effort": "none"}})
        body = self.payload("openrouter", pin=" DeepInfra/FP4 ", effort="high")["extra_body"]
        self.assertEqual(body["provider"], {"data_collection": "deny", "only": ["deepinfra/fp4"], "allow_fallbacks": False})
        self.assertNotIn("reasoning_effort", self.payload("openrouter", effort="high"))
        self.assertNotIn("reasoning", self.payload("openrouter")["extra_body"])

    def test_qwen_tier_vs_boolean_and_none(self):
        for effort in (None, "none"):
            self.assertEqual(self.payload("qwen", effort=effort)["extra_body"], {"preserve_thinking": True})
        self.assertEqual(self.payload("qwen", "qwen3.8-max-latest", effort="high")["extra_body"],
                         {"preserve_thinking": True, "reasoning_effort": "high"})
        self.assertEqual(self.payload("qwen", "coder-model", effort="high")["extra_body"],
                         {"preserve_thinking": True, "enable_thinking": True})
        self.assertEqual(self.payload("qwen", "foreign-model", effort="high")["extra_body"], {"preserve_thinking": True})

    def test_native_effort_and_temperature_rules(self):
        for provider in ("openai", "acrc", "cliproxyapi", "copilot"):
            for name in ("gpt-6-astra", "openai/gpt-6-astra", "o5-pro"):
                self.assertEqual(self.payload(provider, name, effort="high")["reasoning_effort"], "high")
                self.assertNotIn("reasoning_effort", self.payload(provider, name, effort="none"))
            for name in ("gpt-4.1", "openai/gpt-4.1", "gpt-5-chat-latest", "o1-mini"):
                self.assertNotIn("reasoning_effort", self.payload(provider, name, effort="high"))
        self.assertEqual(self.payload("openai", "unknown-platform-model", effort="high")["reasoning_effort"], "high")
        for provider in ("acrc", "cliproxyapi", "copilot"):
            self.assertNotIn("reasoning_effort", self.payload(provider, "deepseek-v4.1-flash", effort="high"))
        self.assertEqual(self.payload("anthropic", effort="none")["extra_body"], {"thinking": {"type": "disabled"}})
        self.assertNotIn("reasoning_effort", self.payload("anthropic", effort="none"))
        self.assertEqual(self.payload("anthropic", effort="high")["reasoning_effort"], "high")


class ResponseSemanticsTests(unittest.TestCase):
    def response(self, **message_fields):
        return {"id": "fixture", "object": "chat.completion", "model": "fixture-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": "visible answer", **message_fields}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

    def test_reasoning_capture_and_chat_replay_preserve_exact_fields(self):
        details = [{"type": "reasoning.encrypted", "data": "opaque", "signature": "do-not-edit", "index": 0}]
        for provider, fields in (
            ("kimicli", {"reasoning_content": "thought"}), ("acrc", {"reasoning_content": "thought"}),
            ("qwen", {"reasoning_content": "thought"}), ("zcode", {"reasoning_content": "thought"}),
            ("openrouter", {"reasoning": "thought", "reasoning_details": details}),
        ):
            with self.subTest(provider=provider):
                model = make_model(provider, _PROVIDERS[provider])
                response = self.response(**fields)
                message = model._create_chat_result(response).generations[0].message
                self.assertEqual(message.content, "visible answer")
                self.assertEqual(message.additional_kwargs, fields)
                self.assertEqual(message.usage_metadata["total_tokens"], 15)
                serialized = model._get_request_payload([HumanMessage(content="task"), message])["messages"][1]
                for key, value in fields.items():
                    self.assertEqual(serialized[key], value)
                self.assertEqual(serialized["content"], "visible answer")
                # SDK model_dump path is also used for the real .invoke response.
                sdk_response = SimpleNamespace(model_dump=lambda: response)
                self.assertEqual(model._create_chat_result(sdk_response).generations[0].message.additional_kwargs, fields)

    def test_tool_calls_and_usage_survive_capture(self):
        model = make_model("zcode", "glm-5.3")
        tool_calls = [{"id": "call-fixture", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"a.py"}'}}]
        response = self.response(reasoning_content="thought", tool_calls=tool_calls)
        response["choices"][0]["finish_reason"] = "tool_calls"
        message = model._create_chat_result(response).generations[0].message
        payload = model._get_request_payload([HumanMessage(content="task"), message, ToolMessage(content="file", tool_call_id="call-fixture")])
        self.assertEqual(payload["messages"][1]["reasoning_content"], "thought")
        replayed = payload["messages"][1]["tool_calls"][0]
        self.assertEqual(replayed["id"], "call-fixture")
        self.assertEqual(replayed["type"], "function")
        self.assertEqual(replayed["function"]["name"], "read_file")
        # Both pinned and upstream converters reserialize valid tool arguments.
        self.assertEqual(json.loads(replayed["function"]["arguments"]), {"path": "a.py"})
        self.assertEqual(message.usage_metadata["input_tokens"], 10)

    def test_empty_reasoning_is_only_replayed_for_kimi(self):
        for provider in ("kimicli", "qwen", "acrc", "zcode"):
            model = make_model(provider, _PROVIDERS[provider])
            message = model._create_chat_result(self.response(reasoning_content="")).generations[0].message
            self.assertEqual(message.additional_kwargs["reasoning_content"], "")
            payload = model._get_request_payload([message])["messages"][0]
            self.assertEqual("reasoning_content" in payload, provider == "kimicli")
            no_reasoning = model._create_chat_result(self.response()).generations[0].message
            self.assertNotIn("reasoning_content", model._get_request_payload([no_reasoning])["messages"][0])

    def test_kimi_cached_tokens_normalization_does_not_mutate_source(self):
        model = make_model("kimicli", "kimi-for-coding")
        response = self.response(reasoning_content="thought")
        response["usage"]["cached_tokens"] = 8
        result = model._create_chat_result(response)
        self.assertEqual(result.generations[0].message.usage_metadata["input_token_details"]["cache_read"], 8)
        self.assertEqual(result.llm_output["token_usage"]["prompt_tokens_details"]["cached_tokens"], 8)
        self.assertNotIn("prompt_tokens_details", response["usage"])
        response["usage"]["prompt_tokens_details"] = {"cached_tokens": 3}
        self.assertEqual(model._create_chat_result(response).generations[0].message.usage_metadata["input_token_details"]["cache_read"], 3)

    def test_openai_and_anthropic_do_not_invent_provider_reasoning(self):
        for provider in ("openai", "anthropic"):
            model = make_model(provider, _PROVIDERS[provider])
            message = model._create_chat_result(self.response(reasoning_content="not-an-official-field")).generations[0].message
            self.assertNotIn("reasoning_content", message.additional_kwargs)

    def test_special_token_markers_are_plain_text(self):
        for provider in ("openai", "zcode"):
            self.assertTrue(make_model(provider, _PROVIDERS[provider]).get_token_ids("file <|endoftext|> content"))


class ActualSDKHTTPTests(unittest.TestCase):
    def test_actual_serialized_http_bodies_headers_and_response_fields(self):
        for provider, model_id in _PROVIDERS.items():
            with self.subTest(provider=provider):
                captured = []
                def serve(request):
                    captured.append(request)
                    self.assertEqual(request.url.host, "fixture.invalid")
                    return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
                        "model": model_id, "choices": [{"index": 0, "finish_reason": "stop", "message": {
                            "role": "assistant", "content": "answer", "reasoning_content": "thought", "reasoning": "routed thought"}}],
                        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})
                with httpx.Client(transport=httpx.MockTransport(serve)) as http_client:
                    opts = options(provider, model_id, effort="none")
                    model = create_chat_client(provider, model=model_id, api_key="fixture-key", base_url=_CONFIG.base_url,
                                               max_tokens=1234, max_retries=0, http_client=http_client, async_client=Mock(), **opts)
                    response = model.invoke(_MESSAGES)
                self.assertEqual(len(captured), 1)
                request = captured[0]
                self.assertEqual(request.url.path, "/v1/chat/completions")
                self.assertEqual(request.headers["authorization"], "Bearer fixture-key")
                for key, value in opts.get("default_headers", {}).items():
                    self.assertEqual(request.headers[key], value)
                body = json.loads(request.content)
                self.assertEqual(body["model"], model_id)
                self.assertEqual(body["max_completion_tokens"], 1234)
                self.assertNotIn("extra_body", body)
                for key, value in opts.get("extra_body", {}).items():
                    self.assertEqual(body[key], value)
                if provider == "anthropic":
                    self.assertNotIn("temperature", body)
                else:
                    self.assertEqual(body["temperature"], 0.6)
                if provider == "zcode":
                    self.assertEqual(body["reasoning_effort"], "low")
                else:
                    self.assertNotIn("reasoning_effort", body)
                self.assertEqual(response.content, "answer")
                if provider in {"kimicli", "qwen", "zcode", "acrc"}:
                    self.assertEqual(response.additional_kwargs["reasoning_content"], "thought")
                elif provider == "openrouter":
                    self.assertEqual(response.additional_kwargs["reasoning"], "routed thought")

    def test_outer_application_loop_exclusively_owns_retries(self):
        calls = []
        def serve(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(500, json={"error": {"message": "fixture transient failure"}})
            return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 0,
                "model": "glm-5.3", "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": "answer", "reasoning_content": "thought"}}]})
        with httpx.Client(transport=httpx.MockTransport(serve)) as http_client:
            model = create_chat_client("zcode", model="glm-5.3", api_key="fixture", base_url=_CONFIG.base_url,
                http_client=http_client, async_client=Mock(), max_retries=0, **options("zcode", "glm-5.3"))
            generator = BaseGenerator()
            generator.chatclient = model
            response = generator.invoke_llm([{"role": "user", "content": "hello"}], max_retries=1, retry_delay=0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(response["content"], "answer")
        self.assertEqual(response["additional_kwargs"]["reasoning_content"], "thought")

    def test_factory_cache_identity_and_host_loopback_are_preserved(self):
        generator = BaseGenerator()
        with patch.object(settings, "default_reasoning_effort", None), patch.object(settings, "kimi_thinking", None), patch("git_tools.generators.base.clients.create_chat_client") as create:
            generator._create_kimicli_client("kimi-for-coding", _CONFIG, 0.6, 100)
            first = create.call_args.kwargs["extra_body"]["prompt_cache_key"]
            generator._create_kimicli_client("kimi-for-coding", _CONFIG, 0.6, 100)
            self.assertEqual(create.call_args.kwargs["extra_body"]["prompt_cache_key"], first)
            BaseGenerator()._create_kimicli_client("kimi-for-coding", _CONFIG, 0.6, 100)
            self.assertNotEqual(create.call_args.kwargs["extra_body"]["prompt_cache_key"], first)
            loopback = SimpleNamespace(api_key="fixture", base_url="http://127.0.0.1:8317/v1")
            with patch.dict(os.environ, {"RUNNING_IN_DOCKER": "1"}):
                generator._create_cliproxy_client("gpt-6-astra", loopback, 0.6, 100)
            self.assertEqual(create.call_args.kwargs["base_url"], loopback.base_url)

    def test_initialized_factories_reach_the_actual_response_adapters(self):
        def offline_create(provider, **kwargs):
            return create_chat_client(provider, client=Mock(), async_client=Mock(), **kwargs)
        for provider, model_id in _PROVIDERS.items():
            with self.subTest(provider=provider), patch.object(settings, "default_reasoning_effort", "none"), patch.object(settings, "kimi_thinking", None), patch("git_tools.generators.base.clients.create_chat_client", side_effect=offline_create):
                generator = BaseGenerator()
                with patch.object(generator, "get_provider_config", return_value=_CONFIG):
                    self.assertTrue(generator._initialize_service(provider, model_id, 0.2, 765))
                payload = generator.chatclient._get_request_payload(_MESSAGES)
                self.assertEqual(payload["max_completion_tokens"], 765)
                self.assertEqual(generator.chatclient.max_retries, 0)
                if provider == "anthropic":
                    self.assertNotIn("temperature", payload)
                else:
                    self.assertEqual(payload["temperature"], 0.2)
                if provider == "zcode":
                    self.assertEqual(payload["extra_body"], _PRESERVED)
                    self.assertEqual(payload["reasoning_effort"], "low")

    def test_absent_endpoint_fails_closed_before_sdk_creation(self):
        for provider in _PROVIDERS:
            for endpoint in (None, "", " "):
                with self.subTest(provider=provider, endpoint=endpoint), self.assertRaisesRegex(ValueError, "No API base"):
                    create_chat_client(provider, model=_PROVIDERS[provider], api_key="fixture", base_url=endpoint)


class UpstreamSourceComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("AGENT_CORE_PROVIDERS_SOURCE", "/worksites/0001/agent-core/agent_core/providers.py"))
        if not path.is_file():
            raise unittest.SkipTest("upstream checkout not supplied; fixture contracts still run")
        tree = ast.parse(path.read_text())
        names = {"_is_openai_o_series_model_name", "_is_openai_family_model_name", "_strip_openai_route_prefix",
                 "_is_known_non_reasoning_openai_model", "model_supports_reasoning_effort", "_is_qwen_family_model",
                 "_is_tiered_effort_qwen_model", "supports_reasoning_effort", "_openrouter_provider_slug", "_openrouter_extra_body"}
        constants = {"_OPENAI_FAMILY_MODEL_PREFIXES", "_NON_REASONING_MODEL_PREFIXES", "_NON_REASONING_MODEL_MARKERS",
                     "_ZCODE_EFFORT_TIERS", "OPENROUTER_PROVIDER_ENV", "_OPENROUTER_UNPINNED"}
        selected = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                selected.append(node)
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
                selected.append(node)
        namespace = {"os": os, "Any": object, "Dict": dict, "uuid": uuid}
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
        get_model = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_model")
        branches = [n for n in get_model.body if isinstance(n, ast.If) and ast.unparse(n.test) in {"provider == 'openrouter'", "provider == 'cliproxyapi'"}]
        if len(branches) != 2:
            raise AssertionError("upstream branch layout changed; refresh the direct-lift parity test")
        cls.namespace = namespace
        cls.branch_code = compile(ast.Module(body=branches, type_ignores=[]), str(path), "exec")

    def test_exact_request_options_against_upstream_branches(self):
        for provider in ("openrouter", "kimicli", "qwen", "zcode", "openai", "anthropic", "acrc", "cliproxyapi"):
            canonical = {"kimicli": "kimicode", "qwen": "qwencode"}.get(provider, provider)
            for name in ("gpt-6-astra", "openai/gpt-6-astra", "openai/gpt-4.1", "o5-pro", "gpt-5-chat-latest", "qwen3.8-max-latest", "coder-model", "glm-5.3", "manual-model"):
                for effort in (None, "none", "minimal", "low", "medium", "high", "xhigh", "max"):
                    for thinking in (None, False, True):
                        with self.subTest(provider=provider, model=name, effort=effort, thinking=thinking):
                            source = dict(self.namespace)
                            source.update(provider=canonical, model_id=name, kwargs={"temperature": 0.6},
                                          requested_effort=effort, reasoning_effort=None if effort == "none" else effort,
                                          inherit_knobs=False, cache_key="fixture-cache", model_type="general",
                                          _CLIPROXYAPI_SESSION_KEYS={"general": "fixture-session"},
                                          settings=SimpleNamespace(openrouter_provider="any", kimi_thinking_state=lambda: None if thinking is None else "enabled" if thinking else "disabled"))
                            exec(self.branch_code, source)
                            self.assertEqual(options(provider, name, effort, thinking, "any"), source["kwargs"])
        self.assertEqual(EFFORT_TIERS, self.namespace["_ZCODE_EFFORT_TIERS"])
        for pin in ("any", "auto", " DeepInfra/FP4 ", "anthropic", "deepinfra/turbo"):
            expected = self.namespace["_openrouter_extra_body"](pin)
            actual = options("openrouter", "vendor/model", pin=pin)["extra_body"]
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

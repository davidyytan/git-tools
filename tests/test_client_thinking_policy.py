"""Resolved request controls follow agent-core; no catalogs or live services."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from git_tools.generators.base import BaseGenerator
from git_tools.settings import mappings
from git_tools.settings.settings import settings

_CONFIG = SimpleNamespace(api_key="fixture", base_url="https://fixture.invalid/v1")


class KimiThinkingPrecedenceTests(unittest.TestCase):
    def _thinking(self, *, thinking: bool | None, effort: str | None, metadata: dict | None = None):
        with (
            patch.dict(mappings.PROVIDERS["kimicli"]["models"], {"fixture": {"model_name": "fixture", **(metadata or {})}}),
            patch.object(settings, "kimi_thinking", thinking),
            patch.object(settings, "default_reasoning_effort", effort),
            patch("git_tools.generators.base.clients.create_chat_client") as client,
        ):
            BaseGenerator()._create_kimicli_client("fixture", _CONFIG, 0.6, 100)
        return client.call_args.kwargs["extra_body"].get("thinking")

    def test_explicit_off_wins_even_with_a_tier(self):
        self.assertEqual(self._thinking(thinking=False, effort="high"), {"type": "disabled"})
        self.assertEqual(self._thinking(thinking=False, effort="xhigh", metadata={"supports_thinking_type": "only"}), {"type": "disabled"})

    def test_catalog_does_not_inject_or_validate_runtime_controls(self):
        self.assertIsNone(self._thinking(thinking=None, effort=None, metadata={"supports_thinking_type": "only"}))
        self.assertEqual(self._thinking(thinking=True, effort="xhigh", metadata={"supports_thinking_type": "no"}),
                         {"type": "enabled", "keep": "all", "effort": "xhigh"})
        self.assertEqual(self._thinking(thinking=None, effort="high", metadata={"think_efforts": {"support": True, "valid_efforts": ["low"]}}),
                         {"type": "enabled", "keep": "all", "effort": "high"})

    def test_explicit_on_and_tier_only_match_agent_core(self):
        self.assertEqual(self._thinking(thinking=None, effort="high"), {"type": "enabled", "keep": "all", "effort": "high"})
        self.assertEqual(self._thinking(thinking=True, effort=None), {"type": "enabled", "keep": "all"})
        self.assertEqual(self._thinking(thinking=True, effort="none"), {"type": "enabled", "keep": "all"})

    def test_none_is_no_tier_not_disable(self):
        self.assertIsNone(self._thinking(thinking=None, effort=None))
        self.assertIsNone(self._thinking(thinking=None, effort="none"))


class CompatibleProviderEffortTests(unittest.TestCase):
    def _kwargs(self, provider, model, effort):
        with patch.object(settings, "default_reasoning_effort", effort), patch("git_tools.generators.base.clients.create_chat_client") as client:
            BaseGenerator()._create_compatible_client(provider, model, _CONFIG, 0.6, 100)
        return client.call_args.kwargs

    def test_qwen_exclusive_controls(self):
        for model in ("qwen3.8-max", "qwen3-max", "coder-model"):
            for effort in (None, "none"):
                self.assertEqual(self._kwargs("qwen", model, effort)["extra_body"], {"preserve_thinking": True})
        self.assertEqual(self._kwargs("qwen", "qwen3.8-max-latest", "high")["extra_body"],
                         {"preserve_thinking": True, "reasoning_effort": "high"})
        for model in ("qwen3-max", "coder-model"):
            self.assertEqual(self._kwargs("qwen", model, "high")["extra_body"], {"preserve_thinking": True, "enable_thinking": True})

    def test_proxied_openai_models_including_route_prefix(self):
        for provider in ("copilot", "acrc"):
            for model in ("gpt-4.1", "openai/gpt-4.1", "deepseek-v4.1-flash"):
                self.assertNotIn("reasoning_effort", self._kwargs(provider, model, "high"))
            for model in ("gpt-6-astra", "openai/gpt-6-astra", "o4-mini", "gpt-7-nova"):
                self.assertEqual(self._kwargs(provider, model, "high")["reasoning_effort"], "high")
                self.assertNotIn("reasoning_effort", self._kwargs(provider, model, "none"))

    def test_openai_temperature_is_not_silently_removed(self):
        for model in ("gpt-6-astra", "gpt-4.1", "o3-mini"):
            self.assertEqual(self._kwargs("openai", model, "high")["temperature"], 0.6)
        self.assertNotIn("temperature", self._kwargs("anthropic", "claude-opus-5-5", "high"))


class CLIProxyClientTests(unittest.TestCase):
    def _kwargs(self, model, effort=None):
        with patch.object(settings, "default_reasoning_effort", effort), patch("git_tools.generators.base.clients.create_chat_client") as client:
            BaseGenerator()._create_cliproxy_client(model, _CONFIG, 0.6, 100)
        return client.call_args.kwargs

    def test_temperature_and_session_header(self):
        for model in ("gpt-6-astra", "o3-mini", "gpt-4.1", "claude-sonnet-4.6"):
            kwargs = self._kwargs(model)
            self.assertEqual(kwargs["temperature"], 0.6)
            self.assertRegex(kwargs["default_headers"]["Session_id"], r"^git-tools-[0-9a-f]{16}$")
            self.assertEqual(kwargs["max_retries"], 0)

    def test_explicit_reasoning_tier(self):
        for model in ("gpt-4.1", "openai/gpt-4.1", "gpt-5-chat-latest", "claude-sonnet-4.6"):
            self.assertNotIn("reasoning_effort", self._kwargs(model, "xhigh"))
        self.assertNotIn("reasoning_effort", self._kwargs("gpt-6-astra"))
        self.assertNotIn("reasoning_effort", self._kwargs("gpt-6-astra", "none"))
        self.assertEqual(self._kwargs("openai/gpt-6-astra", "Low")["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()

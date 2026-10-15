"""Thinking and temperature policy of the client factory, ported from agent-core.

Kimi: the catalog's declared mode wins, then an explicit off, then a tier
alone switches thinking on; with nothing configured nothing is sent and the
model default applies. With thinking off nothing thinking-related is sent,
so a saved tier is neither validated nor forwarded. CLIProxyAPI:
the configured temperature goes to every model (the proxy accepted it for
both GPT families when probed) and the configured tier is forwarded to
OpenAI's reasoning families when set; there is no implicit default, as in
agent-core.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from git_tools.generators.base import BaseGenerator
from git_tools.settings import mappings
from git_tools.settings.settings import settings

_KIMI = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
_PROXY = SimpleNamespace(api_key="cliproxyapi", base_url="http://127.0.0.1:8317/v1")
_TIERS = {"support": True, "valid_efforts": ["low", "high"]}
_TIERED = {"model_name": "tiered", "supports_thinking_type": "both", "think_efforts": _TIERS}
_NO_THINKING = {"model_name": "no-thinking", "supports_thinking_type": "no", "think_efforts": _TIERS}
_THINKING_ONLY = {"model_name": "thinking-only", "supports_thinking_type": "only", "think_efforts": _TIERS}
_ENABLED = {"type": "enabled", "keep": "all"}


class KimiThinkingPrecedenceTests(unittest.TestCase):
    def _thinking(self, model: dict, *, thinking: bool | None, effort: str | None) -> dict:
        name = model["model_name"]
        with (
            patch.dict(mappings.PROVIDERS["kimicli"]["models"], {name: model}),
            patch.object(settings, "kimi_thinking", thinking),
            patch.object(settings, "default_reasoning_effort", effort),
            patch("langchain_openai.ChatOpenAI") as client,
        ):
            BaseGenerator()._create_kimicli_client(name, _KIMI, 0.6, 100)
        return client.call_args.kwargs["extra_body"].get("thinking")

    def test_explicit_off_wins_over_a_tier_the_catalog_rejects(self) -> None:
        # The stale tier would be rejected if sent; off means it is not sent,
        # so the client must build (review issue 3).
        self.assertEqual(self._thinking(_TIERED, thinking=False, effort="xhigh"), {"type": "disabled"})

    def test_explicit_off_wins_over_a_declared_tier(self) -> None:
        self.assertEqual(self._thinking(_TIERED, thinking=False, effort="high"), {"type": "disabled"})

    def test_a_model_without_thinking_ignores_the_tier(self) -> None:
        for thinking in (True, None):
            with self.subTest(thinking=thinking):
                self.assertEqual(self._thinking(_NO_THINKING, thinking=thinking, effort="xhigh"),
                                 {"type": "disabled"})

    def test_a_tier_that_will_be_sent_is_still_validated(self) -> None:
        for thinking in (True, None):
            with self.subTest(thinking=thinking):
                with self.assertRaisesRegex(ValueError, "not supported by this model"):
                    self._thinking(_TIERED, thinking=thinking, effort="xhigh")

    def test_a_declared_tier_switches_thinking_on_and_ships(self) -> None:
        self.assertEqual(self._thinking(_TIERED, thinking=None, effort="high"), {**_ENABLED, "effort": "high"})
        self.assertEqual(self._thinking(_TIERED, thinking=True, effort="low"), {**_ENABLED, "effort": "low"})
        self.assertEqual(self._thinking(_TIERED, thinking=True, effort=None), _ENABLED)

    def test_nothing_configured_leaves_the_model_default(self) -> None:
        # agent-core sends no thinking field unless asked; so does this now.
        self.assertIsNone(self._thinking(_TIERED, thinking=None, effort=None))
        self.assertIsNone(self._thinking(_TIERED, thinking=None, effort="none"))
        self.assertIsNone(self._thinking({"model_name": "unlisted"}, thinking=None, effort=None))

    def test_thinking_only_models_override_an_explicit_off(self) -> None:
        self.assertEqual(self._thinking(_THINKING_ONLY, thinking=False, effort="high"),
                         {**_ENABLED, "effort": "high"})
        with self.assertRaisesRegex(ValueError, "not supported by this model"):
            self._thinking(_THINKING_ONLY, thinking=False, effort="xhigh")


class CompatibleProviderEffortTests(unittest.TestCase):
    """Qwen, Copilot and ACRC: the tier ships only where agent-core ships it."""

    def _kwargs(self, provider: str, model: str, effort: str | None) -> dict:
        with (
            patch.object(settings, "default_reasoning_effort", effort),
            patch("langchain_openai.ChatOpenAI") as client,
        ):
            BaseGenerator()._create_compatible_client(provider, model, _KIMI, 0.6, 100)
        return client.call_args.kwargs

    def test_qwen_none_sends_no_thinking_knob(self) -> None:
        for model in ("qwen3.8-max", "qwen3-max", "coder-model"):
            with self.subTest(model=model):
                for effort in (None, "none"):
                    self.assertEqual(self._kwargs("qwen", model, effort)["extra_body"],
                                     {"preserve_thinking": True})

    def test_qwen_tier_reaches_the_right_knob(self) -> None:
        self.assertEqual(self._kwargs("qwen", "qwen3.8-max", "high")["extra_body"],
                         {"preserve_thinking": True, "reasoning_effort": "high"})
        for model in ("qwen3-max", "coder-model"):
            with self.subTest(model=model):
                self.assertEqual(self._kwargs("qwen", model, "high")["extra_body"],
                                 {"preserve_thinking": True, "enable_thinking": True})

    def test_proxied_openai_models_get_the_tier_only_in_reasoning_families(self) -> None:
        for provider in ("copilot", "acrc"):
            with self.subTest(provider=provider):
                self.assertNotIn("reasoning_effort", self._kwargs(provider, "gpt-4.1", "high"))
                self.assertNotIn("reasoning_effort", self._kwargs(provider, "deepseek-v4.1-flash", "high"))
                self.assertNotIn("reasoning_effort", self._kwargs(provider, "gpt-6-astra", "none"))
                self.assertEqual(self._kwargs(provider, "gpt-6-astra", "high")["reasoning_effort"], "high")
                self.assertEqual(self._kwargs(provider, "o4-mini", "low")["reasoning_effort"], "low")


class CLIProxyClientTests(unittest.TestCase):
    def _kwargs(self, model: str, effort: str | None = None) -> dict:
        with (
            patch.object(settings, "default_reasoning_effort", effort),
            patch.object(settings, "default_temperature", 0.6),
            patch("langchain_openai.ChatOpenAI") as client,
        ):
            BaseGenerator()._create_cliproxy_client(model, _PROXY, None, 100)
        return client.call_args.kwargs

    def test_the_configured_temperature_is_sent_to_every_proxied_model(self) -> None:
        # The proxy's Codex backend accepted 0.6 on gpt-6-astra and gpt-5.6-sol
        # when probed (2026-10-15), so the proxy is treated like every other
        # endpoint that takes a temperature; only OpenAI's own platform omits it.
        for model in ("gpt-6-astra", "gpt-5.6-sol", "o3-mini", "gpt-4.1", "claude-sonnet-4.6"):
            with self.subTest(model=model):
                self.assertEqual(self._kwargs(model)["temperature"], 0.6)

    def test_other_models_never_get_the_tier(self) -> None:
        for model in ("gpt-4.1", "gpt-5-chat-latest", "claude-sonnet-4.6"):
            with self.subTest(model=model):
                self.assertNotIn("reasoning_effort", self._kwargs(model, "xhigh"))

    def test_the_configured_tier_is_forwarded_only_when_set(self) -> None:
        # No implicit default: agent-core sends the tier only when configured.
        self.assertNotIn("reasoning_effort", self._kwargs("gpt-6-astra"))
        self.assertNotIn("reasoning_effort", self._kwargs("gpt-6-astra", "none"))
        self.assertEqual(self._kwargs("gpt-6-astra", "xhigh")["reasoning_effort"], "xhigh")
        self.assertEqual(self._kwargs("gpt-5.6-sol", "Low")["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()

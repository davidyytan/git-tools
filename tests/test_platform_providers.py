"""OpenAI and Anthropic providers, ported from agent-core/agent-cli.

Both are spoken as OpenAI-compatible chat completions. What differs is the
catalog: OpenAI's ``/models`` is narrowed to chat models, and Anthropic's
native Models API wants its own auth and version headers.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from git_tools.generators.base import BaseGenerator
from git_tools.settings import mappings
from git_tools.settings.settings import (
    load_provider_config,
    normalize_provider_name,
    settings,
)

_CONFIG = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")


class RegistryTests(unittest.TestCase):
    def test_providers_are_registered_with_agent_core_defaults(self) -> None:
        openai = mappings.PROVIDERS["openai"]
        anthropic = mappings.PROVIDERS["anthropic"]
        self.assertEqual(openai["api_key_env"], "OPENAI_API_KEY")
        self.assertEqual(openai["default_base_url"], "https://api.openai.com/v1")
        self.assertEqual(next(iter(openai["models"])), "gpt-6-astra")
        self.assertEqual(anthropic["api_key_env"], "ANTHROPIC_API_KEY")
        self.assertEqual(anthropic["default_base_url"], "https://api.anthropic.com/v1")
        self.assertEqual(next(iter(anthropic["models"])), "claude-opus-5-5")
        self.assertIn("openai", mappings.LIVE_MODEL_PROVIDERS)
        self.assertIn("anthropic", mappings.LIVE_MODEL_PROVIDERS)
        self.assertEqual(normalize_provider_name("claude"), "anthropic")

    def test_configs_load_from_their_own_key_and_base_url_aliases(self) -> None:
        from git_tools.settings.settings import AnthropicConfig, OpenAIConfig

        for provider, config_class, key_env, base_env in (
            ("openai", OpenAIConfig, "OPENAI_API_KEY", "OPENAI_BASE_URL"),
            ("anthropic", AnthropicConfig, "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
        ):
            with self.subTest(provider=provider):
                with patch.dict(os.environ, {key_env: "k", base_env: "https://alt.invalid/v1"}, clear=True):
                    config = load_provider_config(provider)
                self.assertEqual(config.api_key, "k")
                self.assertEqual(config.base_url, "https://alt.invalid/v1")
                # The class is built directly here so a GIT_TOOLS_API_BASE saved
                # in the user's settings file cannot stand in for the default.
                with patch.dict(os.environ, {key_env: "k"}, clear=True):
                    config = config_class(_env_file=None)
                self.assertEqual(config.base_url, mappings.PROVIDERS[provider]["default_base_url"])


class OpenAICatalogTests(unittest.TestCase):
    def test_chat_model_filter_matches_agent_cli(self) -> None:
        chat = ("gpt-6-astra", "gpt-4.1", "chatgpt-4o-latest", "o3-mini", "GPT-4o")
        not_chat = (
            "whisper-1", "tts-1-hd", "dall-e-3", "gpt-image-1", "text-embedding-3-large",
            "gpt-4o-realtime-preview", "gpt-4o-audio-preview", "gpt-4o-transcribe",
            "gpt-4o-mini-tts", "gpt-4o-search-preview", "gpt-3.5-turbo-instruct",
            "omni-moderation-latest", "babbage-002",
            # Responses-API-only; the pinned chat-completions client cannot drive them.
            "gpt-5-pro", "o1-pro", "o3-pro", "gpt-5-codex", "gpt-5.1-codex-max", "codex-mini-latest",
            "o4-mini-deep-research",
        )
        for model in chat:
            self.assertTrue(mappings.is_openai_chat_model(model), model)
        for model in not_chat:
            self.assertFalse(mappings.is_openai_chat_model(model), model)

    def _refresh(self, provider: str, live: mappings.LiveModelList) -> tuple[bool, object]:
        snapshot = mappings.snapshot_provider_catalog(provider)
        self.addCleanup(mappings.restore_provider_catalog, provider, snapshot)
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp) / "catalog.json"),
            patch("git_tools.settings.settings.load_provider_config", return_value=_CONFIG),
            patch.object(mappings, "_load_user_model_map", return_value={}),
            patch.object(mappings, "fetch_live_models", return_value=live) as fetch,
        ):
            ok = mappings.refresh_live_models(provider, force=True)
        return ok, fetch

    def test_live_catalog_is_narrowed_to_chat_models_with_default_first(self) -> None:
        live = mappings.LiveModelList(
            sorted(["whisper-1", "gpt-6-astra", "text-embedding-3-large", "gpt-4.1",
                    "gpt-4o-realtime-preview", "o3-mini"]),
            metadata={"gpt-4.1": {"display_name": "GPT-4.1"}, "whisper-1": {"display_name": "Whisper"}},
        )
        ok, fetch = self._refresh("openai", live)

        self.assertTrue(ok)
        fetch.assert_called_once_with("https://test.invalid/v1", "test", headers={}, query=None)
        models = mappings.PROVIDERS["openai"]["models"]
        self.assertEqual(list(models)[0], "gpt-6-astra")
        self.assertEqual(set(models), {"gpt-6-astra", "gpt-4.1", "o3-mini"})
        self.assertEqual(models["gpt-4.1"]["display_name"], "GPT-4.1")
        self.assertEqual(models["gpt-6-astra"]["display_name"], "GPT-6 Astra")

    def test_catalog_without_chat_models_falls_back_to_built_ins(self) -> None:
        live = mappings.LiveModelList(["whisper-1", "text-embedding-3-large"])
        ok, _ = self._refresh("openai", live)

        self.assertFalse(ok)
        error = mappings.get_live_model_refresh_error("openai")
        self.assertEqual(error.kind, "malformed")
        self.assertIn("no chat models", error.message)
        self.assertEqual(list(mappings.PROVIDERS["openai"]["models"]), ["gpt-6-astra", "gpt-6.1-sol"])


class AnthropicCatalogTests(unittest.TestCase):
    def test_catalog_is_fetched_with_native_models_api_headers(self) -> None:
        provider = "anthropic"
        snapshot = mappings.snapshot_provider_catalog(provider)
        self.addCleanup(mappings.restore_provider_catalog, provider, snapshot)
        live = mappings.LiveModelList(
            ["claude-haiku-5-5", "claude-opus-5-5", "claude-opus-5-5-20260301"],
            metadata={"claude-opus-5-5-20260301": {"display_name": "Claude Opus 5.5 (2026-03-01)"}},
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp) / "catalog.json"),
            patch("git_tools.settings.settings.load_provider_config", return_value=_CONFIG),
            patch.object(mappings, "_load_user_model_map", return_value={}),
            patch.object(mappings, "fetch_live_models", return_value=live) as fetch,
        ):
            self.assertTrue(mappings.refresh_live_models(provider, force=True))

        fetch.assert_called_once_with(
            "https://test.invalid/v1", "test",
            headers={"anthropic-version": "2023-06-01", "x-api-key": "test"},
            query="limit=1000",
        )
        models = mappings.PROVIDERS[provider]["models"]
        self.assertEqual(list(models)[0], "claude-opus-5-5")
        self.assertEqual(models["claude-opus-5-5"]["display_name"], "Claude Opus 5.5")
        self.assertEqual(models["claude-opus-5-5-20260301"]["display_name"], "Claude Opus 5.5 (2026-03-01)")
        # Built-ins the endpoint did not list are dropped, as for every live provider.
        self.assertNotIn("claude-sonnet-5-5", models)

    def test_live_fetch_sends_extra_headers_beside_bearer(self) -> None:
        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"data": [{"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"}]}'

        def urlopen(request, timeout):
            captured["headers"] = {k.lower(): v for k, v in request.header_items()}
            captured["url"] = request.full_url
            return _Response()

        with patch("urllib.request.urlopen", side_effect=urlopen):
            live = mappings.fetch_live_models(
                "https://api.anthropic.com/v1", "sk-ant",
                headers=mappings.anthropic_catalog_headers("sk-ant"), query="limit=1000",
            )

        self.assertEqual(list(live), ["claude-opus-5-5"])
        self.assertEqual(captured["url"], "https://api.anthropic.com/v1/models?limit=1000")
        self.assertEqual(captured["headers"]["authorization"], "Bearer sk-ant")
        self.assertEqual(captured["headers"]["x-api-key"], "sk-ant")
        self.assertEqual(captured["headers"]["anthropic-version"], "2023-06-01")


class ClientTests(unittest.TestCase):
    def _client_kwargs(self, provider: str, model: str, effort: str | None) -> dict:
        with (
            patch("langchain_openai.ChatOpenAI") as client,
            patch.object(settings, "default_reasoning_effort", effort),
            patch.object(settings, "default_temperature", 0.6),
        ):
            BaseGenerator()._create_compatible_client(provider, model, _CONFIG, None, 100)
        return client.call_args.kwargs

    def test_dispatch_routes_both_through_the_compatible_transport(self) -> None:
        for provider in ("openai", "anthropic"):
            with self.subTest(provider=provider):
                generator = BaseGenerator()
                with (
                    patch.object(generator, "get_provider_config", return_value=_CONFIG),
                    patch.object(generator, "_create_compatible_client", return_value="client") as create,
                ):
                    self.assertTrue(generator._initialize_service(provider, "any-model", 0.6, 100))
                create.assert_called_once_with(provider, "any-model", _CONFIG, 0.6, 100)

    def test_openai_forwards_the_tier_and_omits_temperature_for_reasoning_families(self) -> None:
        kwargs = self._client_kwargs("openai", "gpt-6-astra", "high")
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("extra_body", kwargs)
        self.assertEqual((kwargs["model"], kwargs["base_url"]), ("gpt-6-astra", "https://test.invalid/v1"))

        kwargs = self._client_kwargs("openai", "o3-mini", None)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("temperature", kwargs)

    def test_openai_chat_models_outside_reasoning_families_keep_temperature(self) -> None:
        kwargs = self._client_kwargs("openai", "gpt-4.1", "medium")
        self.assertEqual(kwargs["reasoning_effort"], "medium")
        self.assertEqual(kwargs["temperature"], 0.6)

    def test_openai_none_is_absence_on_the_wire(self) -> None:
        kwargs = self._client_kwargs("openai", "gpt-4.1", "none")
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("extra_body", kwargs)
        self.assertEqual(kwargs["temperature"], 0.6)

    def test_anthropic_never_sends_temperature(self) -> None:
        # Claude 4.7+ returns 400 for any temperature below 1 (OpenAI SDK
        # compatibility docs), with or without thinking.
        for effort in (None, "high", "none"):
            with self.subTest(effort=effort):
                kwargs = self._client_kwargs("anthropic", "claude-haiku-5-5", effort)
                self.assertNotIn("temperature", kwargs)

    def test_anthropic_forwards_the_tier_and_none_disables_thinking(self) -> None:
        kwargs = self._client_kwargs("anthropic", "claude-opus-5-5", "high")
        self.assertEqual(kwargs["reasoning_effort"], "high")
        self.assertNotIn("extra_body", kwargs)

        kwargs = self._client_kwargs("anthropic", "claude-opus-5-5", None)
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertNotIn("extra_body", kwargs)

        kwargs = self._client_kwargs("anthropic", "claude-opus-5-5", "none")
        self.assertNotIn("reasoning_effort", kwargs)
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_no_responses_api_switch_is_passed_to_the_pinned_langchain(self) -> None:
        # langchain-openai 0.3.4 has no such field; an unknown kwarg would be
        # forwarded to the API as a body parameter and rejected.
        for provider, model in (("openai", "gpt-6-astra"), ("anthropic", "claude-opus-5-5")):
            with self.subTest(provider=provider):
                self.assertNotIn("use_responses_api", self._client_kwargs(provider, model, "high"))


if __name__ == "__main__":
    unittest.main()

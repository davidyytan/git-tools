"""Catalog resolution follows agent-cli's provider flow; the registry only holds the result."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from git_tools.providers import acrc, anthropic, openai, qwen
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog
from git_tools.providers.kimi_code import parse_kimi_code_catalog
from git_tools.settings import mappings
from git_tools.settings.mappings import (
    LIVE_MODEL_PROVIDERS,
    PROVIDERS,
    refresh_live_models,
    resolve_provider_catalog,
)

KIMI_PAYLOAD = {"data": [{
    "id": "k3", "supports_thinking_type": "both",
    "think_efforts": {"support": True, "valid_efforts": ["low", "high"], "default_effort": "high"},
}]}
NETWORK_DOWN = CatalogFetchResult(error_kind="network", error="VPN down")


def _live(*items) -> CatalogFetchResult:
    data = [{"id": item} if isinstance(item, str) else item for item in items]
    return CatalogFetchResult(entries=parse_model_catalog({"data": data}), source="live",
                              fetched_at="2026-10-16T00:00:00+00:00")


def _kimi_live() -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_kimi_code_catalog(KIMI_PAYLOAD), source="live",
                              fetched_at="2026-10-16T00:00:00+00:00")


class CatalogStateCase(unittest.TestCase):
    """Isolates the registry, the per-process memo and the cache file per test."""

    def setUp(self) -> None:
        cache_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cache_dir.cleanup)
        self.cache_path = Path(cache_dir.name) / "model-catalog.json"
        patcher = patch.object(mappings, "MODEL_CATALOG_PATH", self.cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        for provider in PROVIDERS:
            self.addCleanup(mappings.restore_provider_catalog, provider,
                            mappings.snapshot_provider_catalog(provider))
        mappings._LIVE_REFRESHED.clear()
        mappings._LIVE_REFRESH_IDENTITIES.clear()
        mappings._LIVE_REFRESH_ERRORS.clear()

    def configure(self, base_url: str = "http://x/v1", api_key: str = "k") -> SimpleNamespace:
        config = SimpleNamespace(base_url=base_url, api_key=api_key)
        patcher = patch("git_tools.settings.settings.load_provider_config", side_effect=lambda _p: config)
        patcher.start()
        self.addCleanup(patcher.stop)
        return config


class TestResolveProviderCatalog(CatalogStateCase):
    def test_live_only_providers_show_exactly_what_is_served(self) -> None:
        for provider in ("openrouter", "cliproxyapi", "copilot"):
            with self.subTest(provider=provider):
                with patch.object(mappings, "_fetch_models_sync", return_value=_live("b-model", "a-model")):
                    served = resolve_provider_catalog(provider, "http://x/v1", "k")
                self.assertEqual([e.id for e in served.entries], ["a-model", "b-model"])
                with patch.object(mappings, "_fetch_models_sync", return_value=NETWORK_DOWN):
                    failed = resolve_provider_catalog(provider, "http://x/v1", "k")
                # No built-in list stands in: the picker offers the saved model and typing.
                self.assertEqual(failed.entries, ())
                self.assertEqual((failed.error_kind, failed.error), ("network", "VPN down"))

    def test_module_resolvers_overlay_names_pin_the_default_and_fall_back(self) -> None:
        with patch.object(mappings, "_fetch_models_sync",
                          return_value=_live("glm-5-3-flash", "deepseek-v4.1-flash", "qwen3.6-plus")):
            served = resolve_provider_catalog("acrc", "http://x/v1", "k")
        self.assertEqual([e.id for e in served.entries], ["deepseek-v4.1-flash", "glm-5-3-flash", "qwen3.6-plus"])
        self.assertEqual(served.entries[0].display_name, "DeepSeek V4.1 Flash")
        self.assertIsNone(served.entries[2].display_name)

        with patch.object(mappings, "_fetch_models_sync", return_value=NETWORK_DOWN):
            fallback = resolve_provider_catalog("acrc", "http://x/v1", "k")
        self.assertEqual(fallback.entries, acrc.MODELS)
        self.assertEqual(fallback.error_kind, "network")

        with patch.object(mappings, "_fetch_models_sync", return_value=_live("whisper-1", "gpt-4.1", "gpt-6-astra")):
            chat_only = resolve_provider_catalog("openai", "http://x/v1", "k")
        self.assertEqual([e.id for e in chat_only.entries], ["gpt-6-astra", "gpt-4.1"])
        self.assertEqual(chat_only.entries[0].display_name, "GPT-6 Astra")

    def test_anthropic_is_fetched_with_the_modules_headers_and_query(self) -> None:
        calls = []

        def fake_fetch(base_url, api_key, *, timeout, headers, query=None):
            calls.append((base_url, api_key, timeout, dict(headers), query))
            return _live({"id": "claude-haiku-5-5"}, {"id": "claude-opus-5-5", "display_name": "Claude Opus 5.5"})

        with patch.object(anthropic, "fetch_model_catalog_sync", fake_fetch):
            served = resolve_provider_catalog("anthropic", "https://api.anthropic.com/v1", "sk-ant")
        self.assertEqual(calls, [("https://api.anthropic.com/v1", "sk-ant", 4.0,
                                  {"anthropic-version": "2023-06-01", "x-api-key": "sk-ant"}, "limit=1000")])
        self.assertEqual([e.id for e in served.entries], ["claude-opus-5-5", "claude-haiku-5-5"])
        self.assertEqual(served.entries[1].display_name, "Claude Haiku 5.5")  # built-in name overlaid

    def test_qwen_is_curated_and_never_fetched(self) -> None:
        with patch.object(mappings, "_fetch_models_sync") as fetch:
            curated = resolve_provider_catalog("qwen", "", "")
        fetch.assert_not_called()
        self.assertEqual(curated.entries, qwen.MODELS)

    def test_fetch_exceptions_and_an_empty_base_url_become_results(self) -> None:
        with patch.object(mappings, "_fetch_models_sync", side_effect=ValueError("Invalid IPv6 URL")):
            result = resolve_provider_catalog("cliproxyapi", "http://[::1/v1", "k")
        self.assertEqual(result.error_kind, "network")
        self.assertIn("IPv6", result.error)
        with patch.object(mappings, "_fetch_models_sync") as fetch:
            missing = resolve_provider_catalog("cliproxyapi", "", "k")
        fetch.assert_not_called()
        self.assertEqual((missing.error_kind, missing.error), ("malformed", "provider base URL is empty"))

    def test_kimi_live_catalog_is_cached_in_agent_cli_format_and_used_on_failure(self) -> None:
        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=_kimi_live()):
            live = resolve_provider_catalog("kimicli", "https://api.kimi.com/coding/v1", "secret-key")
        self.assertEqual(live.source, "live")
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["catalogs"]), 1)
        self.assertNotIn("secret-key", self.cache_path.read_text(encoding="utf-8"))

        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=NETWORK_DOWN):
            stale = resolve_provider_catalog("kimicli", "https://api.kimi.com/coding/v1", "secret-key")
            other = resolve_provider_catalog("kimicli", "https://api.kimi.com/coding/v1", "other-key")
        self.assertEqual((stale.source, [e.id for e in stale.entries], stale.error_kind), ("cache", ["k3"], "network"))
        self.assertEqual(other.entries, ())  # another account's copy is never shown

        refused = CatalogFetchResult(error_kind="http", error="bad request", status=400)
        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=refused):
            authoritative = resolve_provider_catalog("kimicli", "https://api.kimi.com/coding/v1", "secret-key")
        self.assertEqual((authoritative.entries, authoritative.status), ((), 400))


class TestRefreshLiveModels(CatalogStateCase):
    def test_every_live_provider_places_the_served_catalog_in_the_registry(self) -> None:
        self.assertEqual(set(LIVE_MODEL_PROVIDERS), set(PROVIDERS) - {"qwen"})
        self.configure()
        for provider in LIVE_MODEL_PROVIDERS:
            with self.subTest(provider=provider):
                live_id = "gpt-live-model" if provider == "openai" else f"{provider}-live-model"
                with (patch.object(mappings, "_fetch_models_sync", return_value=_live(live_id)),
                      patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=_live(live_id)),
                      patch.object(mappings, "_fetch_anthropic_models_sync", return_value=_live(live_id))):
                    self.assertTrue(refresh_live_models(provider, force=True))
                self.assertIn(live_id, PROVIDERS[provider]["models"])
                self.assertEqual(PROVIDERS[provider]["models"][live_id]["model_name"], live_id)

    def test_unknown_and_curated_providers_are_noop(self) -> None:
        self.assertFalse(refresh_live_models("unknown"))
        with patch.object(mappings, "_fetch_models_sync") as fetch:
            self.assertFalse(refresh_live_models("qwen", force=True))
        fetch.assert_not_called()

    def test_failed_fetch_shows_the_builtins_records_the_error_and_is_not_memoized(self) -> None:
        self.configure()
        with patch.object(mappings, "_fetch_models_sync", return_value=NETWORK_DOWN) as fetch:
            self.assertFalse(refresh_live_models("cliproxyapi"))
            self.assertFalse(refresh_live_models("cliproxyapi"))  # retried, never memoized
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(PROVIDERS["cliproxyapi"]["models"], {})
        error = mappings.get_live_model_refresh_error("cliproxyapi")
        self.assertEqual((error.kind, error.message, error.retained_live_catalog), ("network", "VPN down", False))

        with patch.object(mappings, "_fetch_models_sync", return_value=NETWORK_DOWN):
            self.assertFalse(refresh_live_models("acrc"))
        self.assertEqual(list(PROVIDERS["acrc"]["models"]), [entry.id for entry in acrc.MODELS])
        self.assertEqual(mappings.get_live_model_refresh_error("acrc").message, "VPN down")

        with patch.object(mappings, "_fetch_models_sync", return_value=_live("gpt-5.6-sol")):
            self.assertTrue(refresh_live_models("cliproxyapi"))
        self.assertIsNone(mappings.get_live_model_refresh_error("cliproxyapi"))

    def test_kimi_metadata_reaches_the_registry(self) -> None:
        self.configure()
        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=_kimi_live()):
            self.assertTrue(refresh_live_models("kimicli", force=True))
        self.assertEqual(PROVIDERS["kimicli"]["models"]["k3"], {
            "model_name": "k3", "supports_thinking_type": "both",
            "think_efforts": {"support": True, "valid_efforts": ["low", "high"], "default_effort": "high"},
        })

    def test_stale_kimi_cache_is_shown_but_not_reported_live(self) -> None:
        config = self.configure("https://cache-test.invalid/v1", "cache-test-key")
        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=_kimi_live()):
            self.assertTrue(refresh_live_models("kimicli", force=True))
        with patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=NETWORK_DOWN):
            self.assertFalse(refresh_live_models("kimicli", force=True))
            self.assertIn("k3", PROVIDERS["kimicli"]["models"])
            self.assertTrue(mappings.get_live_model_refresh_error("kimicli").retained_live_catalog)
            config.api_key = "different-account"
            self.assertFalse(refresh_live_models("kimicli"))
        self.assertEqual(PROVIDERS["kimicli"]["models"], {})

    def test_refresh_memoizes_by_provider_endpoint_and_api_key(self) -> None:
        config = self.configure()
        with patch.object(mappings, "_fetch_models_sync", return_value=_live("gpt-5.6-sol")) as fetch:
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 1)
            config.api_key = "k2"
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 2)
            config.base_url = "http://y/v1"
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 3)
            self.assertTrue(refresh_live_models("cliproxyapi", force=True))
            self.assertEqual(fetch.call_count, 4)

    def test_configuration_failure_diagnostic_does_not_echo_secret(self) -> None:
        secret = "sk-secret-that-must-not-appear"
        with patch("git_tools.settings.settings.load_provider_config",
                   side_effect=ValueError(f"invalid input: {secret}")):
            self.assertFalse(refresh_live_models("kimicli", force=True))
        failure = mappings.get_live_model_refresh_error("kimicli")
        self.assertNotIn(secret, failure.message)
        self.assertIn("configuration is invalid or incomplete", failure.message)

    def test_configuration_failure_drops_the_old_live_catalog(self) -> None:
        self.configure()
        with patch.object(mappings, "_fetch_models_sync", return_value=_live("gpt-5.6-sol", "old-account-only")):
            self.assertTrue(refresh_live_models("cliproxyapi"))
        with patch("git_tools.settings.settings.load_provider_config", side_effect=ValueError("missing API key")):
            self.assertFalse(refresh_live_models("cliproxyapi", force=True))
        self.assertEqual(PROVIDERS["cliproxyapi"]["models"], {})
        self.assertNotIn("cliproxyapi", mappings._LIVE_REFRESHED)

    def test_openrouter_privacy_default_lives_in_the_request_not_in_a_list(self) -> None:
        from git_tools.generators.base import BaseGenerator

        self.configure()
        with patch.object(mappings, "_fetch_models_sync", return_value=_live("vendor/new-model")):
            self.assertTrue(refresh_live_models("openrouter"))
        self.assertEqual(PROVIDERS["openrouter"]["models"]["vendor/new-model"], {"model_name": "vendor/new-model"})
        with patch("langchain_openai.ChatOpenAI") as client:
            BaseGenerator()._create_openrouter_client(
                "vendor/new-model", SimpleNamespace(api_key="k", base_url="http://x/v1"), 0.6, 100)
        self.assertEqual(client.call_args.kwargs["extra_body"]["provider"]["data_collection"], "deny")


class TestLiveProviderModelTrust(unittest.TestCase):
    """Dynamic providers trust configured model IDs as endpoint authority."""

    def test_settings_state_keeps_live_only_model_for_each_provider(self) -> None:
        from git_tools.cli import _resolve_current_model

        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(_resolve_current_model(provider, "provider-live-only"), "provider-live-only")

    def test_unset_model_still_uses_provider_fallback_default(self) -> None:
        from git_tools.cli import _resolve_current_model

        self.assertEqual(_resolve_current_model("cliproxyapi", None), "gpt-6-astra")

    def test_generator_default_keeps_live_only_model(self) -> None:
        from git_tools.generators.base import BaseGenerator
        from git_tools.settings import settings as settings_module

        models = PROVIDERS["cliproxyapi"]["models"]
        with patch.object(settings_module.settings, "main_model", None), patch.object(
            settings_module.settings, "default_model", "gpt-5.6-terra"
        ):
            resolved = BaseGenerator._get_default_model(BaseGenerator.__new__(BaseGenerator), models, "cliproxyapi")
        self.assertEqual(resolved, "gpt-5.6-terra")


if __name__ == "__main__":
    unittest.main()

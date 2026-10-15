"""The registry wraps the provider modules copied from agent-cli, not a second table.

agent-cli's version of this file checks its presets against agent-core's
table; here the equivalent is that ``git_tools.settings.mappings`` takes every
endpoint, alias, default model and curated list from ``git_tools.providers``
and adds only git-tools' own wiring on top.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.providers import acrc, anthropic, cliproxyapi, copilot, kimi_code, openai, openrouter, qwen
from git_tools.providers.catalog import CatalogFetchResult, ModelCatalogEntry, parse_model_catalog
from git_tools.providers.openrouter import OpenRouterEndpoint
from git_tools.settings import mappings

MODULES = (openrouter, acrc, copilot, qwen, kimi_code, cliproxyapi, openai, anthropic)
# git-tools stores Kimi under its historical key and keeps the module id as an alias.
REGISTRY_KEYS = {kimi_code.PROVIDER_ID: "kimicli"}


class ProviderModuleShapeTests(unittest.TestCase):
    def test_every_module_declares_a_consistent_preset(self) -> None:
        for module in MODULES:
            with self.subTest(module=module.PROVIDER_ID):
                self.assertEqual(module.PRESET["type"], module.PROVIDER_ID)
                self.assertEqual(module.PRESET["default_model"], module.DEFAULT_MODEL)
                self.assertEqual(module.PRESET["profile"], module.PROFILE)
                if module is qwen:
                    self.assertNotIn("base_url", module.PRESET)  # the endpoint is typed, never preset
                else:
                    self.assertEqual(module.PRESET["base_url"], module.BASE_URL)
                self.assertIsInstance(module.ALIASES, tuple)

    def test_curated_lists_lead_with_the_default_model(self) -> None:
        for module in (acrc, copilot, qwen, openai, anthropic):
            with self.subTest(module=module.PROVIDER_ID):
                self.assertEqual(module.MODELS[0].id, module.DEFAULT_MODEL)
                self.assertEqual(module.catalog().entries, module.MODELS)


class RegistryWrapsModulesTests(unittest.TestCase):
    def test_registry_order_and_keys_follow_the_modules(self) -> None:
        expected = [REGISTRY_KEYS.get(module.PROVIDER_ID, module.PROVIDER_ID) for module in MODULES]
        self.assertEqual(list(mappings.PROVIDERS), expected)
        self.assertEqual(list(mappings._BUILTIN_PROVIDERS), expected)

    def test_aliases_come_from_the_modules(self) -> None:
        for module in MODULES:
            key = REGISTRY_KEYS.get(module.PROVIDER_ID, module.PROVIDER_ID)
            with self.subTest(provider=key):
                aliases = mappings.PROVIDERS[key]["aliases"]
                if module is kimi_code:
                    self.assertEqual(aliases, (kimi_code.PROVIDER_ID, *kimi_code.ALIASES))
                else:
                    self.assertEqual(aliases, module.ALIASES)
                for alias in aliases:
                    self.assertEqual(mappings.PROVIDER_ALIASES[alias], key)

    def test_endpoints_come_from_the_modules(self) -> None:
        for module in MODULES:
            key = REGISTRY_KEYS.get(module.PROVIDER_ID, module.PROVIDER_ID)
            with self.subTest(provider=key):
                shown = mappings.PROVIDERS[key]["default_base_url"]
                if module is qwen:
                    self.assertEqual(shown, "")
                else:
                    self.assertEqual(shown, module.BASE_URL)
                self.assertEqual(mappings.PROVIDERS[key]["default_model"], module.DEFAULT_MODEL)

    def test_curated_lists_and_defaults_come_from_the_modules(self) -> None:
        # The built-in table, not PROVIDERS: that one also carries the ids the
        # user saved manually and whatever a live refresh merged in.
        builtin = mappings._BUILTIN_PROVIDERS
        for module in (acrc, copilot, qwen, openai, anthropic):
            with self.subTest(provider=module.PROVIDER_ID):
                models = builtin[module.PROVIDER_ID]["models"]
                self.assertEqual(list(models), [entry.id for entry in module.MODELS])
                for entry in module.MODELS:
                    self.assertEqual(models[entry.id].get("model_name"), entry.id)
                    self.assertEqual(models[entry.id].get("display_name"), entry.display_name)
        # Live-only in agent-cli, so no static list here either.
        for key in ("openrouter", "kimicli", "cliproxyapi"):
            self.assertEqual(builtin[key]["models"], {}, key)
        self.assertEqual(mappings.DEFAULT_OPENROUTER_MODEL, openrouter.DEFAULT_MODEL)

    def test_anthropic_catalog_call_is_the_modules(self) -> None:
        with patch.object(anthropic, "fetch_catalog_sync", return_value=anthropic.catalog()) as fetch:
            mappings.resolve_provider_catalog("anthropic", "https://x/v1", "sk-ant")
        fetch.assert_called_once_with("https://x/v1", "sk-ant", timeout=4.0)
        self.assertEqual(mappings.ANTHROPIC_API_VERSION, anthropic.API_VERSION)
        self.assertIs(mappings.anthropic_catalog_headers, anthropic.catalog_headers)

    def test_openai_chat_filter_is_the_modules(self) -> None:
        self.assertIs(mappings.is_openai_chat_model, openai.is_chat_model)
        with (patch.object(openai, "resolve_catalog", wraps=openai.resolve_catalog) as resolve,
              patch.object(mappings, "_fetch_models_sync", return_value=["whisper-1", "gpt-6-astra"])):
            result = mappings.resolve_provider_catalog("openai", "https://x/v1", "k")
        resolve.assert_called_once()
        self.assertEqual([entry.id for entry in result.entries], ["gpt-6-astra"])


class WrappedCallsTests(unittest.TestCase):
    def test_upstreams_are_the_modules_endpoints_in_its_order(self) -> None:
        result = CatalogFetchResult(entries=(
            OpenRouterEndpoint(tag="deepinfra/fp4", provider_name="DeepInfra"),
            OpenRouterEndpoint(tag="fireworks", provider_name="Fireworks"),
        ), source="live")
        with patch.object(openrouter, "fetch_endpoints_sync", return_value=result) as fetch:
            upstreams = mappings.fetch_openrouter_upstreams("https://openrouter.ai/api/v1", "key", "vendor/model")
        self.assertEqual(upstreams, ["deepinfra/fp4", "fireworks"])
        fetch.assert_called_once_with("vendor/model", "key", base_url="https://openrouter.ai/api/v1")

        with patch.object(openrouter, "fetch_endpoints_sync") as fetch:
            self.assertEqual(mappings.fetch_openrouter_upstreams("", "key", "vendor/model"), [])
            self.assertEqual(mappings.fetch_openrouter_upstreams("https://x/v1", "key", ""), [])
        fetch.assert_not_called()

    def test_live_only_catalogs_go_through_the_shared_transport(self) -> None:
        payload = {"data": [{"id": "zeta", "display_name": "Alpha Label"}, {"id": "alpha"}, {"id": "   "}]}
        calls = []

        def fake_fetch(base_url, api_key, *, timeout):
            calls.append((base_url, api_key, timeout))
            return CatalogFetchResult(entries=parse_model_catalog(payload), source="live")

        with patch.object(mappings, "fetch_model_catalog_sync", fake_fetch):
            live = mappings.resolve_provider_catalog("cliproxyapi", "https://x/v1", "key")
        self.assertEqual(calls, [("https://x/v1", "key", 4.0)])
        self.assertEqual([entry.id for entry in live.entries], ["alpha", "zeta"])  # parser order: by label
        self.assertEqual(live.entries[1].display_name, "Alpha Label")

    def test_live_only_catalog_failures_keep_their_kind_and_status(self) -> None:
        failure = CatalogFetchResult(error_kind="auth", error="Incorrect API key", status=401)
        with patch.object(mappings, "fetch_model_catalog_sync", return_value=failure):
            live = mappings.resolve_provider_catalog("openrouter", "https://x/v1", "bad")
        self.assertEqual(live.entries, ())
        self.assertEqual((live.error_kind, live.error, live.status), ("auth", "Incorrect API key", 401))

    def test_metadata_normalization_wraps_the_kimi_codec_and_tolerates_junk(self) -> None:
        entry = ModelCatalogEntry(id="k")  # the codec needs an id; registry entries carry model_name
        self.assertEqual(mappings.normalize_catalog_metadata({"model_name": entry.id, "display_name": " K "}),
                         {"display_name": "K"})
        self.assertEqual(mappings.normalize_catalog_metadata({"supports_thinking_type": [], "context_length": True}), {})
        self.assertEqual(mappings.normalize_catalog_metadata("nope"), {})
        self.assertEqual(mappings.normalize_catalog_metadata({"think_efforts": {"support": True, "valid_efforts": []}}),
                         {"think_efforts": {"support": True, "valid_efforts": []}})


if __name__ == "__main__":
    unittest.main()

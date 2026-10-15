from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner
from git_tools.cli import app
from git_tools.generators.base import BaseGenerator
from git_tools.settings import mappings
from git_tools.settings.settings import GitToolsSettings, load_provider_config, settings


class ProviderParityTests(unittest.TestCase):
    def test_all_core_providers_and_aliases(self):
        from git_tools.settings.settings import normalize_provider_name
        self.assertEqual(set(mappings.PROVIDERS), {"openrouter", "kimicli", "cliproxyapi", "acrc", "copilot", "qwen", "openai", "anthropic"})
        self.assertEqual(normalize_provider_name("kimicode"), "kimicli")
        self.assertEqual(normalize_provider_name("claude"), "anthropic")
        self.assertEqual(normalize_provider_name("dashscope"), "qwen")

    def test_main_over_legacy_support_unused(self):
        with patch.dict(os.environ, {"GIT_TOOLS_MODEL_MAIN": "main", "GIT_TOOLS_DEFAULT_MODEL": "old", "GIT_TOOLS_MODEL_SUPPORT": "sub"}):
            fresh = GitToolsSettings(_env_file=None)
        self.assertEqual(fresh.effective_main_model, "main")
        with patch.object(settings, "main_model", "main"), patch.object(settings, "support_model", "sub"):
            generator = BaseGenerator()
            self.assertEqual(generator._get_default_model(mappings.PROVIDERS["qwen"]["models"], "qwen"), "main")
        generator = BaseGenerator(model="explicit")
        self.assertEqual(generator._resolve_cli_model({}), "explicit")

    def test_qwen_requires_endpoint_and_all_configs_load(self):
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "test"}, clear=True):
            with self.assertRaises(ValueError):
                from git_tools.settings.settings import QwenConfig
                QwenConfig(_env_file=None)
        for provider in mappings.PROVIDERS:
            env = {mappings.PROVIDERS[provider]["api_key_env"]: "test", "GIT_TOOLS_API_BASE": "https://test.invalid/v1"}
            with patch.dict(os.environ, env, clear=True):
                config = load_provider_config(provider)
            self.assertEqual(config.base_url, "https://test.invalid/v1")

    def test_curated_providers_do_not_probe(self):
        with patch.object(mappings, "fetch_live_models") as fetch:
            self.assertFalse(mappings.refresh_live_models("qwen", force=True))
            fetch.assert_not_called()

    def test_generic_transports_and_qwen_thinking(self):
        config = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
        with patch("langchain_openai.ChatOpenAI") as client, patch.object(settings, "default_reasoning_effort", "high"):
            for provider in ("acrc", "copilot", "qwen"):
                BaseGenerator()._create_compatible_client(provider, "qwen3.8-max", config, 0.6, 100)
            kwargs = client.call_args.kwargs
            self.assertEqual(kwargs["extra_body"], {"preserve_thinking": True, "reasoning_effort": "high"})

    def test_openrouter_pin_and_explicit_none(self):
        config = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
        with patch("langchain_openai.ChatOpenAI") as client, patch.object(settings, "openrouter_provider", "deepinfra"), patch.object(settings, "default_reasoning_effort", "none"):
            BaseGenerator()._create_openrouter_client("vendor/model", config, 0.6, 100)
        body = client.call_args.kwargs["extra_body"]
        self.assertEqual(body["provider"]["only"], ["deepinfra"])
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertEqual(body["reasoning"], {"effort": "none"})

    def test_cache_scoped_to_endpoint_and_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp)/"catalog.json"):
            identity = mappings._catalog_identity("https://one/v1", "secret")
            mappings._save_catalog("kimicli", identity, mappings.LiveModelList(["served"], metadata={"served": {"supports_thinking_type": "only"}}))
            self.assertEqual(mappings._cached_catalog("kimicli", identity), ["served"])
            self.assertEqual(mappings._cached_catalog("kimicli", mappings._catalog_identity("https://one/v1", "other")), [])
            self.assertNotIn("secret", mappings.MODEL_CATALOG_PATH.read_text())

    def test_new_direct_settings_persist(self):
        from git_tools.settings import settings as module
        with tempfile.TemporaryDirectory() as tmp, patch.object(module, "DEFAULT_SETTINGS_PATH", Path(tmp)/"settings.env"), patch("git_tools.cli._remember_manual_model"):
            for name, value in (("main-model", "main-test"), ("support-model", "follow-main"), ("api-base", "https://test.invalid/v1"), ("effort", "none")):
                result = CliRunner().invoke(app, ["settings", name, value])
                self.assertEqual(result.exit_code, 0, result.output)
            text = module.DEFAULT_SETTINGS_PATH.read_text()
            self.assertIn('GIT_TOOLS_MODEL_MAIN="main-test"', text)
            self.assertIn('GIT_TOOLS_MODEL_SUPPORT="follow-main"', text)
            self.assertIn('GIT_TOOLS_REASONING_EFFORT="none"', text)

    def test_stale_cache_is_used_but_not_reported_live(self):
        provider = "kimicli"
        snapshot = mappings.snapshot_provider_catalog(provider)
        self.addCleanup(mappings.restore_provider_catalog, provider, snapshot)
        config = SimpleNamespace(base_url="https://cache-test.invalid/v1", api_key="cache-test-key")
        with tempfile.TemporaryDirectory() as tmp, patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp)/"catalog.json"), patch("git_tools.settings.settings.load_provider_config", return_value=config), patch.object(mappings, "_load_user_model_map", return_value={}):
            live = mappings.LiveModelList(["account-model"], metadata={"account-model": {"supports_thinking_type": "only"}})
            with patch.object(mappings, "fetch_live_models", return_value=live):
                self.assertTrue(mappings.refresh_live_models(provider, force=True))
            mappings._LIVE_REFRESHED.discard(provider)
            with patch.object(mappings, "fetch_live_models", return_value=mappings.LiveModelList(error_kind="network")):
                self.assertFalse(mappings.refresh_live_models(provider, force=True))
                self.assertIn("account-model", mappings.PROVIDERS[provider]["models"])
                self.assertTrue(mappings.get_live_model_refresh_error(provider).retained_live_catalog)
                self.assertFalse(mappings.refresh_live_models(provider))
            config.api_key = "different-account"
            with patch.object(mappings, "fetch_live_models", return_value=mappings.LiveModelList(error_kind="network")):
                self.assertFalse(mappings.refresh_live_models(provider, force=True))
            self.assertNotIn("account-model", mappings.PROVIDERS[provider]["models"])

    def test_cancelled_qwen_setup_preserves_endpoint(self):
        from git_tools.cli import _edit_provider
        from git_tools.settings import settings as module
        state = {"provider": "openrouter", "model": "main", "api_configured": True}
        with patch.dict(os.environ, {"GIT_TOOLS_API_BASE": "https://original.invalid/v1"}), patch("git_tools.cli._ask_with_back", side_effect=["qwen", None]), patch.object(module, "save_settings") as save:
            _edit_provider(state)
            self.assertEqual(os.environ["GIT_TOOLS_API_BASE"], "https://original.invalid/v1")
            self.assertEqual(state["provider"], "openrouter")
            save.assert_not_called()

    def test_catalog_metadata_drives_kimi_thinking(self):
        config = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
        model = {"model_name": "thinking-only", "supports_thinking_type": "only"}
        with patch.dict(mappings.PROVIDERS["kimicli"]["models"], {"thinking-only": model}), patch.object(settings, "kimi_thinking", False), patch.object(settings, "default_reasoning_effort", None), patch("langchain_openai.ChatOpenAI") as client:
            BaseGenerator()._create_kimicli_client("thinking-only", config, 0.6, 100)
            self.assertEqual(client.call_args.kwargs["extra_body"]["thinking"]["type"], "enabled")

    def test_effort_none_keeps_kimi_thinking_off(self):
        # Kimi has no "none" tier: a global `none` means thinking off, never an
        # effort on the wire, whether or not the catalog declares tiers.
        config = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
        tiered = {"model_name": "tiered", "supports_thinking_type": "both",
                  "think_efforts": {"support": True, "valid_efforts": ["low", "high"]}}
        plain = {"model_name": "plain", "supports_thinking_type": "both"}
        for name, model in (("tiered", tiered), ("plain", plain)):
            with self.subTest(model=name), patch.dict(mappings.PROVIDERS["kimicli"]["models"], {name: model}), patch.object(settings, "kimi_thinking", None), patch.object(settings, "default_reasoning_effort", "none"), patch("langchain_openai.ChatOpenAI") as client:
                BaseGenerator()._create_kimicli_client(name, config, 0.6, 100)
                self.assertEqual(client.call_args.kwargs["extra_body"]["thinking"], {"type": "disabled"})

    def test_generation_picker_keeps_unlisted_main_and_supports_manual_entry(self):
        from git_tools.cli import ADD_MODEL_SENTINEL

        models = mappings.PROVIDERS["kimicli"]["models"]
        with patch.object(settings, "main_model", "unlisted-main"), patch("git_tools.cli._ask_model_choice", return_value=ADD_MODEL_SENTINEL) as picker, patch("git_tools.cli._ask_with_back", return_value=" invocation-model "):
            selected = BaseGenerator(interactive=True)._interactive_model_selection(models, "kimicli")
        picker.assert_called_once_with("kimicli", current_model="unlisted-main", default_model="unlisted-main")
        self.assertEqual(selected, "invocation-model")

    def test_generation_picker_uses_search_for_large_catalog(self):
        from git_tools.cli import ADD_MODEL_SENTINEL

        models = {f"model-{i}": {"model_name": f"model-{i}"} for i in range(30)}
        with patch.dict(mappings.PROVIDERS["kimicli"], {"models": models}), patch.object(settings, "main_model", "unlisted-main"), patch("git_tools.cli.questionary.select") as search, patch("git_tools.cli._ask_with_back", return_value="model-20"):
            selected = BaseGenerator(interactive=True)._interactive_model_selection(models, "kimicli")
        self.assertEqual(selected, "model-20")
        search.assert_called_once()
        self.assertTrue(search.call_args.kwargs["use_search_filter"])
        labels = [choice.title for choice in search.call_args.kwargs["choices"]]
        self.assertTrue(any("unlisted-main" in label for label in labels))
        self.assertTrue(any("manually" in label for label in labels))

    def test_generation_picker_cancel_does_not_select_fallback(self):
        with patch("git_tools.cli._ask_model_choice", return_value=None):
            with self.assertRaises(KeyboardInterrupt):
                BaseGenerator(interactive=True)._interactive_model_selection(mappings.PROVIDERS["kimicli"]["models"], "kimicli")

    def test_generation_reports_refresh_failure_and_keeps_explicit_model(self):
        generator = BaseGenerator(model="explicit-model")
        with patch.object(generator, "get_provider_config", return_value=SimpleNamespace()), patch("git_tools.generators.base.models.refresh_live_models", return_value=False), patch("git_tools.cli._print_model_catalog_status") as status:
            model, _, _ = generator.select_model_params("kimicli")
        status.assert_called_once_with("kimicli", False)
        self.assertEqual(model, "explicit-model")

    def test_malformed_kimi_metadata_does_not_break_client(self):
        config = SimpleNamespace(api_key="test", base_url="https://test.invalid/v1")
        for invalid in (True, 123, "high", {"bad": "type"}, None):
            with self.subTest(value=invalid):
                metadata = {"model_name": "bad-metadata", "supports_thinking_type": [],
                            "think_efforts": {"support": True, "valid_efforts": invalid}}
                with patch.dict(mappings.PROVIDERS["kimicli"]["models"], {"bad-metadata": metadata}), patch.object(settings, "default_reasoning_effort", "high"), patch("langchain_openai.ChatOpenAI") as client:
                    BaseGenerator()._create_kimicli_client("bad-metadata", config, 0.6, 100)
                client.assert_called_once()

    def test_catalog_metadata_normalization_retains_only_valid_values(self):
        metadata = mappings.normalize_catalog_metadata({
            "display_name": " Label ", "supports_thinking_type": "both", "context_length": True,
            "think_efforts": {"support": True, "valid_efforts": [" high ", 123, None, "", "high", "low"]},
        })
        self.assertEqual(metadata["display_name"], "Label")
        self.assertNotIn("context_length", metadata)
        self.assertEqual(metadata["think_efforts"]["valid_efforts"], ["high", "low"])

    def test_named_provider_in_terminal_runs_full_wizard(self):
        from git_tools.settings import settings as module
        state = {"provider": "kimicli", "model": "old", "api_configured": True}
        with patch("git_tools.cli._has_interactive_terminal", return_value=True), patch("git_tools.cli._load_settings_state", return_value=state), patch("git_tools.cli._prompt_provider_api_key", return_value=(True, "test-key")), patch("git_tools.cli._choose_provider_model", return_value="vendor/model"), patch("git_tools.cli._ask_with_back", side_effect=["follow-main", "route-slug", "high"]), patch("git_tools.settings.mappings.fetch_openrouter_upstreams", return_value=["route-slug"]), patch.object(module, "save_settings") as save:
            result = CliRunner().invoke(app, ["settings", "provider", "openrouter"])
        self.assertEqual(result.exit_code, 0, str(result.exception))
        save.assert_called_once()
        updates = save.call_args.args[0]
        self.assertEqual(updates["GIT_TOOLS_MODEL_MAIN"], "vendor/model")
        self.assertEqual(updates["GIT_TOOLS_MODEL_SUPPORT"], "follow-main")
        self.assertEqual(updates["GIT_TOOLS_OPENROUTER_PROVIDER"], "route-slug")
        self.assertEqual(updates["GIT_TOOLS_REASONING_EFFORT"], "high")
        self.assertEqual(state["openrouter_provider"], "route-slug")

    def test_explicit_noninteractive_provider_never_prompts(self):
        from git_tools.settings import settings as module
        with patch("git_tools.cli._has_interactive_terminal", return_value=True), patch("git_tools.cli._ask_with_back") as ask, patch("git_tools.cli.refresh_live_models", return_value=False), patch.object(module, "save_settings") as save:
            result = CliRunner().invoke(app, ["settings", "provider", "acrc", "--non-interactive"])
        self.assertEqual(result.exit_code, 0, str(result.exception))
        ask.assert_not_called()
        save.assert_called_once()

    def test_cancel_at_last_wizard_step_saves_nothing(self):
        from git_tools.cli import _edit_provider
        from git_tools.settings import settings as module
        state = {"provider": "kimicli", "model": "old", "api_configured": True}
        with patch("git_tools.cli._prompt_provider_api_key", return_value=(True, "candidate-key")), patch("git_tools.cli._choose_provider_model", return_value="vendor/model"), patch("git_tools.cli._ask_with_back", side_effect=["follow-main", "any", None]), patch("git_tools.settings.mappings.fetch_openrouter_upstreams", return_value=[]), patch.object(module, "save_settings") as save, patch.dict(os.environ, {}, clear=False):
            original = os.environ.get("OPENROUTER_API_KEY")
            _edit_provider(state, "openrouter", interactive=True)
            self.assertEqual(os.environ.get("OPENROUTER_API_KEY"), original)
        save.assert_not_called()
        self.assertEqual(state["provider"], "kimicli")

    def test_upstream_uses_tag_not_label(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"data": {"endpoints": [{"tag": "route-slug", "provider_name": "Display"}]}}).encode()
        with patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(mappings.fetch_openrouter_upstreams("https://test/v1", "key", "vendor/model"), ["route-slug"])

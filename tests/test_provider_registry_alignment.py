"""Offline registry/config contracts aligned with agent-core provider metadata.

Run under an isolated HOME/XDG_CONFIG_HOME: importing settings can migrate
legacy settings. These tests do not construct generation clients or call APIs.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from git_tools.providers import acrc, anthropic, cliproxyapi, copilot, kimi_code, openai, openrouter, qwen, zcode
from git_tools.settings import mappings
from git_tools.settings import settings as config


class ProviderRegistryAlignmentTests(unittest.TestCase):
    def test_core_provider_ids_keep_storage_compatibility_and_copilot(self):
        self.assertEqual(set(mappings.PROVIDERS), {
            "acrc", "openrouter", "kimicli", "cliproxyapi", "qwen", "openai", "anthropic", "zcode", "copilot",
        })
        for alias, saved in (("kimicode", "kimicli"), ("kimi", "kimicli"),
                             ("qwencode", "qwen"), ("dashscope", "qwen"), ("alibaba", "qwen")):
            self.assertEqual(config.normalize_provider_name(alias.upper()), saved)
            self.assertEqual(config.provider_profile_key(alias, "MODEL_MAIN"),
                             config.provider_profile_key(saved, "MODEL_MAIN"))
        self.assertEqual(config.provider_api_key_env("qwencode"), "DASHSCOPE_API_KEY")
        self.assertEqual(copilot.BASE_URL, "http://127.0.0.1:4141/v1")
        self.assertEqual(cliproxyapi.BASE_URL, "http://127.0.0.1:8317/v1")

    def test_zcode_exact_metadata_and_curated_catalog_never_probe(self):
        definition = mappings.PROVIDERS["zcode"]
        self.assertEqual(zcode.BASE_URL, "https://api.z.ai/api/coding/paas/v4")
        self.assertEqual(zcode.API_KEY_ENV, "ZCODE_API_KEY")
        self.assertEqual(zcode.DEFAULT_MODEL, "glm-5.3")
        self.assertEqual(tuple(entry.id for entry in zcode.MODELS), ("glm-5.3", "glm-5.3-flash"))
        self.assertEqual(definition["config_class"], "ZCodeConfig")
        self.assertEqual(tuple(definition["models"]), tuple(entry.id for entry in zcode.MODELS))
        self.assertNotIn("zcode", mappings.LIVE_MODEL_PROVIDERS)
        self.assertTrue(mappings.provider_allows_manual_model("zcode"))
        with patch.object(mappings, "_fetch_models_sync") as fetch:
            self.assertEqual(mappings.resolve_provider_catalog("zcode", "", "").entries, zcode.MODELS)
            self.assertEqual(mappings.resolve_provider_catalog("qwencode", "", "").entries, qwen.MODELS)
            self.assertFalse(mappings.refresh_live_models("zcode", force=True))
            self.assertFalse(mappings.refresh_live_models("qwencode", force=True))
        fetch.assert_not_called()

    def test_zcode_effort_table_matches_core_and_keeps_unset_distinct(self):
        expected = {"none": "low", "minimal": "low", "low": "low", "medium": "high",
                    "high": "high", "xhigh": "max", "max": "max"}
        self.assertEqual(zcode.EFFORT_TIERS, expected)
        for requested, sent in expected.items():
            self.assertEqual(zcode.resolve_reasoning_effort(f" {requested.upper()} "), sent)
        for absent in (None, "", " "):
            self.assertIsNone(zcode.resolve_reasoning_effort(absent))
        self.assertEqual(zcode.resolve_reasoning_effort("future"), "future")

    def test_openai_route_prefix_classification_matches_direct_models(self):
        for model in ("gpt-6-astra", "o3", "gpt-4.1", "gpt-5-chat-latest", "codex-future"):
            self.assertEqual(mappings.is_openai_family_model(f"openai/{model}"),
                             mappings.is_openai_family_model(model))
            self.assertEqual(mappings.is_openai_reasoning_model(f"openai/{model}"),
                             mappings.is_openai_reasoning_model(model))
        self.assertFalse(mappings.is_openai_reasoning_model("openai/gpt-4.1"))
        self.assertTrue(mappings.is_openai_reasoning_model("openai/gpt-6-astra"))

    def test_optional_source_table_parity_without_importing_agent_core(self):
        source_root = os.environ.get("AGENT_CORE_SOURCE")
        if not source_root:
            self.skipTest("Set AGENT_CORE_SOURCE for a read-only source-level comparison")
        module = ast.parse((Path(source_root) / "agent_core/providers.py").read_text())
        assignments = {node.targets[0].id: node.value for node in module.body
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name)}
        definitions = ast.literal_eval(assignments["PROVIDER_CONFIGS"])
        compatible_keys = {"kimicode": "kimicli", "qwencode": "qwen"}
        for provider, source in definitions.items():
            key = compatible_keys.get(provider, provider)
            actual = mappings.PROVIDERS[key]
            if provider == "cliproxyapi":
                self.assertEqual(source["api_base"], "http://host.docker.internal:8317/v1")
                self.assertEqual(actual["default_base_url"], cliproxyapi.BASE_URL)
            else:
                self.assertEqual(actual["default_base_url"], source["api_base"])
            envs = config._get_provider_api_key_envs(key)
            self.assertIn(source["api_key_env"], envs)
            if "default_model" in source:
                self.assertEqual(actual["default_model"], source["default_model"])
        self.assertEqual(zcode.EFFORT_TIERS, ast.literal_eval(assignments["_ZCODE_EFFORT_TIERS"]))
        run = ast.parse((Path(source_root) / "agent_core/run.py").read_text())
        run_assignments = {node.targets[0].id: node.value for node in run.body
                           if isinstance(node, ast.Assign) and len(node.targets) == 1
                           and isinstance(node.targets[0], ast.Name)}
        for name, key in (("MODEL_CONFIGS", "openrouter"), ("ACRC_MODEL_CONFIGS", "acrc"),
                          ("CLIPROXYAPI_MODEL_CONFIGS", "cliproxyapi"), ("QWENCODE_MODEL_CONFIGS", "qwen"),
                          ("OPENAI_MODEL_CONFIGS", "openai"), ("ANTHROPIC_MODEL_CONFIGS", "anthropic"),
                          ("ZCODE_MODEL_CONFIGS", "zcode")):
            defaults = ast.literal_eval(run_assignments[name])
            self.assertEqual(mappings.PROVIDERS[key]["default_model"], defaults["general"]["model"])


class ProviderAliasConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.local = self.root / "git-tools.env"
        self.saved = self.root / "settings.env"
        for patcher in (patch.dict(os.environ, {}, clear=True),
                        patch.object(config, "DEFAULT_SETTINGS_PATH", self.saved),
                        patch.object(config, "_get_env_file_paths", return_value=[self.local, self.saved])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_temperature_default_matches_core_and_preserves_existing_overrides(self):
        self.assertEqual(config.GitToolsSettings.model_fields["default_temperature"].default, 1.0)
        self.assertEqual(config.GitToolsSettings().default_temperature, 1.0)
        self.saved.write_text('GIT_TOOLS_DEFAULT_TEMPERATURE="0.6"\n')
        self.assertEqual(config.GitToolsSettings().default_temperature, 0.6)
        self.assertEqual(config.GitToolsSettings(default_temperature=0.6, _env_file=None).default_temperature, 0.6)
        with patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_TEMPERATURE": "0.6"}):
            self.assertEqual(config.GitToolsSettings(_env_file=None).default_temperature, 0.6)
        self.saved.write_text('GIT_TOOLS_DEFAULT_TEMPERATURE=""\n')
        self.assertEqual(config.GitToolsSettings().default_temperature, 1.0)

    def test_zcode_requires_own_key_and_defaults_to_plan_endpoint(self):
        with self.assertRaises(ValidationError):
            config.ZCodeConfig(_env_file=None)
        with patch.dict(os.environ, {"ZCODE_API_KEY": "fixture"}):
            actual = config.load_provider_config("zcode")
            self.assertEqual(actual.api_key, "fixture")
            self.assertEqual(actual.base_url, zcode.BASE_URL)
            self.assertEqual(config.check_api_key_configured("zcode"), (True, "fixture"))
            self.assertEqual(config.provider_base_url_env("zcode"), "ZCODE_BASE_URL")
        with patch.dict(os.environ, {"ZAI_API_KEY": "not-a-coding-plan-key"}):
            self.assertEqual(config.check_api_key_configured("zcode"), (False, None))

    def test_qwencode_key_and_endpoint_aliases_load_without_guessing(self):
        with patch.dict(os.environ, {"QWENCODE_API_KEY": "fixture"}):
            with self.assertRaises(ValidationError):
                config.load_provider_config("qwencode")
            with patch.dict(os.environ, {"QWENCODE_BASE_URL": "https://plan.invalid/v1"}):
                actual = config.load_provider_config("qwencode")
                self.assertEqual(actual.api_key, "fixture")
                self.assertEqual(actual.base_url, "https://plan.invalid/v1")
                self.assertEqual(config.check_api_key_configured("qwencode"), (True, "fixture"))
                self.assertEqual(config.effective_provider_base_url("qwencode")[0], actual.base_url)
                self.assertEqual(config.saved_provider_base_url("qwencode"), actual.base_url)

    def test_qwen_alias_precedence_is_per_source_and_preserves_existing_keys(self):
        self.local.write_text('DASHSCOPE_API_KEY="local"\nQWEN_BASE_URL="https://local.invalid/v1"\n')
        self.saved.write_text('QWENCODE_API_KEY="saved"\nQWENCODE_BASE_URL="https://saved.invalid/v1"\n')
        actual = config.load_provider_config("qwen")
        self.assertEqual((actual.api_key, actual.base_url), ("saved", "https://saved.invalid/v1"))
        with patch.dict(os.environ, {"QWENCODE_API_KEY": "environment", "QWENCODE_BASE_URL": "https://env.invalid/v1"}):
            actual = config.load_provider_config("qwencode")
            self.assertEqual((actual.api_key, actual.base_url), ("environment", "https://env.invalid/v1"))
            self.assertEqual(config.check_api_key_configured("qwen"), (True, "environment"))
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "legacy", "QWENCODE_API_KEY": "compatible",
                                   "QWEN_BASE_URL": "https://legacy.invalid/v1", "QWENCODE_BASE_URL": "https://compatible.invalid/v1"}):
            actual = config.load_provider_config("qwencode")
            self.assertEqual((actual.api_key, actual.base_url), ("legacy", "https://legacy.invalid/v1"))
        actual = config.QwenConfig(api_key="explicit", base_url="https://explicit.invalid/v1")
        self.assertEqual((actual.api_key, actual.base_url), ("explicit", "https://explicit.invalid/v1"))

    def test_alias_provider_saves_model_and_endpoint_under_existing_qwen_profile(self):
        config.save_settings({"GIT_TOOLS_PROVIDER": "qwencode", "GIT_TOOLS_MODEL_MAIN": "custom-model",
                              "GIT_TOOLS_API_BASE": "https://saved.invalid/v1"})
        text = self.saved.read_text()
        self.assertIn('GIT_TOOLS_QWEN_MODEL_MAIN="custom-model"', text)
        self.assertIn('QWEN_BASE_URL="https://saved.invalid/v1"', text)
        self.assertNotIn("GIT_TOOLS_QWENCODE_MODEL_MAIN=", text)
        self.assertEqual(config.saved_provider_profile("qwencode")["model"], "custom-model")
        self.assertEqual(config.saved_provider_profile("qwen")["api_base"], "https://saved.invalid/v1")

    def test_saved_qwencode_blank_masks_lower_endpoint_and_does_not_guess_host(self):
        self.local.write_text('DASHSCOPE_API_KEY="fixture"\nQWEN_BASE_URL="https://local.invalid/v1"\n')
        self.saved.write_text('QWENCODE_BASE_URL=""\n')
        self.assertIsNone(config.effective_provider_base_url("qwen")[0])
        with self.assertRaises(ValidationError):
            config.load_provider_config("qwencode")


if __name__ == "__main__":
    unittest.main()

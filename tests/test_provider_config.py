from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.config.mappings import PROVIDERS
from git_tools.config.config import (
    CLIProxyAPIConfig,
    KimiCLIConfig,
    check_api_key_configured,
    load_provider_config,
)
from git_tools.generators.issueprgen import IssuePullRequestGenerator


class ProviderConfigTests(unittest.TestCase):
    def test_provider_api_key_env_names_are_exact(self) -> None:
        self.assertEqual(PROVIDERS["kimicli"]["api_key_env"], "KIMICODE_API_KEY")
        self.assertEqual(
            PROVIDERS["cliproxyapi"]["api_key_env"],
            "CLIPROXYAPI_API_KEY",
        )

    def test_openrouter_defaults_to_claude_sonnet(self) -> None:
        from git_tools.config.mappings import DEFAULT_OPENROUTER_MODEL

        self.assertEqual(DEFAULT_OPENROUTER_MODEL, "anthropic/claude-sonnet-4.6")
        models = PROVIDERS["openrouter"]["models"]
        # The default is the first (and, out of the box, only) OpenRouter model.
        first = next(iter(models.values()))
        self.assertEqual(first["model_name"], "anthropic/claude-sonnet-4.6")

    def test_add_user_openrouter_model_persists_and_merges(self) -> None:
        from git_tools.config import mappings as mappings_module

        slug = "vendor/test-model-x"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            with patch.object(mappings_module, "USER_MODELS_PATH", path):
                try:
                    # First insert is new and written to disk under "openrouter".
                    self.assertTrue(mappings_module.add_user_openrouter_model(slug))
                    saved = json.loads(path.read_text())
                    self.assertIn(slug, saved["openrouter"])
                    # A duplicate is a no-op that reports False.
                    self.assertFalse(mappings_module.add_user_openrouter_model(slug))
                    # Blank input is rejected.
                    self.assertFalse(mappings_module.add_user_openrouter_model("  "))
                    # It is mirrored into the live PROVIDERS map with a deny default.
                    entry = mappings_module.PROVIDERS["openrouter"]["models"][slug]
                    self.assertEqual(entry["model_name"], slug)
                    self.assertEqual(entry["data_collection"], "deny")
                finally:
                    mappings_module.PROVIDERS["openrouter"]["models"].pop(slug, None)

    def test_provider_api_key_env_must_be_declared(self) -> None:
        from git_tools.config import config as config_module

        with patch.dict(config_module.PROVIDERS, {"testprovider": {}}, clear=False):
            with self.assertRaisesRegex(ValueError, "must define api_key_env"):
                check_api_key_configured("testprovider")

    @patch.dict(os.environ, {"KIMICODE_API_KEY": "sk-kimi-test"}, clear=False)
    def test_check_api_key_configured_supports_kimicli_kimicode_env(self) -> None:
        configured, value = check_api_key_configured("kimicli")

        self.assertTrue(configured)
        self.assertEqual(value, "sk-kimi-test")

    @patch.dict(
        os.environ,
        {"KIMICODE_API_KEY": "sk-kimi-test", "GIT_TOOLS_API_BASE": "https://kimi.example/v1"},
        clear=False,
    )
    def test_load_provider_config_supports_kimicli(self) -> None:
        config = load_provider_config("kimicli")

        self.assertIsInstance(config, KimiCLIConfig)
        self.assertEqual(config.api_key, "sk-kimi-test")
        self.assertEqual(config.base_url, "https://kimi.example/v1")

    def test_create_kimicli_client_sets_headers_and_extra_body(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = KimiCLIConfig(
            KIMICODE_API_KEY="sk-kimi-test",
            GIT_TOOLS_API_BASE="https://api.kimi.com/coding/v1",
        )

        with patch("langchain_openai.ChatOpenAI") as chat_openai:
            generator._create_kimicli_client(
                "kimi-k2.5",
                provider_config,
                temperature=0.2,
                max_tokens=8000,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["model"], "kimi-k2.5")
        self.assertEqual(kwargs["api_key"], "sk-kimi-test")
        self.assertEqual(kwargs["base_url"], "https://api.kimi.com/coding/v1")
        self.assertEqual(kwargs["default_headers"], {"User-Agent": "KimiCLI/1.3"})
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    @patch.dict(os.environ, {"CLIPROXYAPI_API_KEY": "cliproxyapi"}, clear=False)
    def test_check_api_key_configured_supports_cliproxyapi_env(self) -> None:
        configured, value = check_api_key_configured("cliproxyapi")

        self.assertTrue(configured)
        self.assertEqual(value, "cliproxyapi")

    @patch.dict(
        os.environ,
        {"CLIPROXYAPI_API_KEY": "cliproxyapi"},
        clear=False,
    )
    def test_load_provider_config_supports_cliproxyapi(self) -> None:
        config = load_provider_config("cliproxyapi")

        self.assertIsInstance(config, CLIProxyAPIConfig)
        self.assertEqual(config.api_key, "cliproxyapi")
        self.assertEqual(config.base_url, "http://localhost:8317/v1")

    def test_cliproxyapi_api_key_defaults_without_env(self) -> None:
        # The CLIProxyAPI client key is a fixed placeholder, so it need not be set.
        from git_tools.config import config as config_module

        self.assertEqual(
            CLIProxyAPIConfig.model_fields["api_key"].default, "cliproxyapi"
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLIPROXYAPI_API_KEY", None)
            with patch.object(config_module, "_get_env_file_paths", return_value=[]):
                configured, value = config_module.check_api_key_configured("cliproxyapi")

        self.assertTrue(configured)
        self.assertEqual(value, "cliproxyapi")

    def test_openrouter_api_key_not_defaulted(self) -> None:
        # Only local-proxy providers get a default key; OpenRouter still requires one.
        from git_tools.config import config as config_module

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with patch.object(config_module, "_get_env_file_paths", return_value=[]):
                configured, value = config_module.check_api_key_configured("openrouter")

        self.assertFalse(configured)
        self.assertIsNone(value)

    def test_create_cliproxy_client_sets_session_header_and_reasoning_effort(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = CLIProxyAPIConfig(CLIPROXYAPI_API_KEY="cliproxyapi")

        with patch("langchain_openai.ChatOpenAI") as chat_openai:
            generator._create_cliproxy_client(
                "gpt-5.5",
                provider_config,
                temperature=0.2,
                max_tokens=8000,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.5")
        self.assertEqual(kwargs["api_key"], "cliproxyapi")
        self.assertEqual(kwargs["base_url"], "http://localhost:8317/v1")
        self.assertIn("Session_id", kwargs["default_headers"])
        self.assertTrue(kwargs["default_headers"]["Session_id"].startswith("git-tools-"))
        # gpt-5 family rejects a custom temperature, so it must be omitted.
        self.assertNotIn("temperature", kwargs)
        # The completion cap is forwarded (relies on the 32k global default for headroom).
        self.assertEqual(kwargs["max_tokens"], 8000)
        # gpt-5.5 carries reasoning_effort=xhigh in its provider definition.
        self.assertEqual(kwargs["reasoning_effort"], "xhigh")

    def test_cliproxy_client_override_beats_per_model_reasoning_effort(self) -> None:
        # settings is a singleton loaded at import; patch the resolved value to
        # emulate GIT_TOOLS_REASONING_EFFORT being set, and confirm it wins over
        # the per-model xhigh default from the provider definition.
        from git_tools.config import config as config_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = CLIProxyAPIConfig(CLIPROXYAPI_API_KEY="cliproxyapi")

        with patch.object(config_module.settings, "default_reasoning_effort", "low"):
            with patch("langchain_openai.ChatOpenAI") as chat_openai:
                generator._create_cliproxy_client(
                    "gpt-5.5",
                    provider_config,
                    temperature=0.2,
                    max_tokens=8000,
                )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")

    def test_reasoning_effort_override_requires_model_effort(self) -> None:
        from git_tools.config import config as config_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch.object(config_module.settings, "default_reasoning_effort", "low"):
            effort = generator._resolve_reasoning_effort({"model_name": "plain-model"})

        self.assertIsNone(effort)

    @patch.dict(os.environ, {"GIT_TOOLS_REASONING_EFFORT": "MEDIUM"}, clear=False)
    def test_settings_reads_and_normalizes_reasoning_effort_env(self) -> None:
        from git_tools.config.config import GitToolsSettings

        # A freshly constructed settings object reads the env alias and lowercases it.
        fresh = GitToolsSettings()
        self.assertEqual(fresh.default_reasoning_effort, "medium")

    @patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_MAX_TOKENS": ""}, clear=False)
    def test_settings_default_max_tokens_is_32k(self) -> None:
        from git_tools.config.config import GitToolsSettings

        # Default (and empty-string fallback) is the bumped 32k cap.
        self.assertEqual(GitToolsSettings().default_max_tokens, 32000)


if __name__ == "__main__":
    unittest.main()

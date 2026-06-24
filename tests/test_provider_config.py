from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from git_tools.config.config import (
    CLIProxyAPIConfig,
    KimiCLIConfig,
    check_api_key_configured,
    load_provider_config,
)
from git_tools.generators.issueprgen import IssuePullRequestGenerator


class ProviderConfigTests(unittest.TestCase):
    @patch.dict(os.environ, {"MOONSHOT_API_KEY": "sk-kimi-test"}, clear=False)
    def test_check_api_key_configured_supports_kimicli_moonshot_env(self) -> None:
        configured, value = check_api_key_configured("kimicli")

        self.assertTrue(configured)
        self.assertEqual(value, "sk-kimi-test")

    @patch.dict(
        os.environ,
        {"MOONSHOT_API_KEY": "sk-kimi-test", "GIT_TOOLS_API_BASE": "https://kimi.example/v1"},
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
            MOONSHOT_API_KEY="sk-kimi-test",
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
        # gpt-5.5 carries reasoning_effort=xhigh in mappings.json.
        self.assertEqual(kwargs["reasoning_effort"], "xhigh")

    def test_cliproxy_client_override_beats_per_model_reasoning_effort(self) -> None:
        # settings is a singleton loaded at import; patch the resolved value to
        # emulate GIT_TOOLS_REASONING_EFFORT being set, and confirm it wins over
        # the per-model xhigh default from mappings.json.
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

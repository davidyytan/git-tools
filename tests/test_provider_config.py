from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from git_tools.config.config import KimiCLIConfig, check_api_key_configured, load_provider_config
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.settings.mappings import PROVIDERS
from git_tools.settings.settings import (
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
        from git_tools.settings.mappings import DEFAULT_OPENROUTER_MODEL

        self.assertEqual(DEFAULT_OPENROUTER_MODEL, "anthropic/claude-sonnet-4.6")
        models = PROVIDERS["openrouter"]["models"]
        # The default is the first (and, out of the box, only) OpenRouter model.
        first = next(iter(models.values()))
        self.assertEqual(first["model_name"], "anthropic/claude-sonnet-4.6")

    def test_add_user_openrouter_model_persists_and_merges(self) -> None:
        from git_tools.settings import mappings as mappings_module

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
        from git_tools.settings import settings as settings_module

        with patch.dict(settings_module.PROVIDERS, {"testprovider": {}}, clear=False):
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
        # Kimi Code rejects every other value, so an explicit stale override is
        # normalized to the provider-required temperature.
        self.assertEqual(kwargs["temperature"], 0.6)

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
        from git_tools.settings import settings as settings_module

        self.assertEqual(
            CLIProxyAPIConfig.model_fields["api_key"].default, "cliproxyapi"
        )

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLIPROXYAPI_API_KEY", None)
            with patch.object(settings_module, "_get_env_file_paths", return_value=[]):
                configured, value = settings_module.check_api_key_configured("cliproxyapi")

        self.assertTrue(configured)
        self.assertEqual(value, "cliproxyapi")

    def test_openrouter_api_key_not_defaulted(self) -> None:
        # Only local-proxy providers get a default key; OpenRouter still requires one.
        from git_tools.settings import settings as settings_module

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            with patch.object(settings_module, "_get_env_file_paths", return_value=[]):
                configured, value = settings_module.check_api_key_configured("openrouter")

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
        from git_tools.settings import settings as settings_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = CLIProxyAPIConfig(CLIPROXYAPI_API_KEY="cliproxyapi")

        with patch.object(settings_module.settings, "default_reasoning_effort", "low"):
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
        from git_tools.settings import settings as settings_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch.object(settings_module.settings, "default_reasoning_effort", "low"):
            effort = generator._resolve_reasoning_effort({"model_name": "plain-model"})

        self.assertIsNone(effort)

    @patch.dict(os.environ, {"GIT_TOOLS_REASONING_EFFORT": "MEDIUM"}, clear=False)
    def test_settings_reads_and_normalizes_reasoning_effort_env(self) -> None:
        from git_tools.settings.settings import GitToolsSettings

        # A freshly constructed settings object reads the env alias and lowercases it.
        fresh = GitToolsSettings()
        self.assertEqual(fresh.default_reasoning_effort, "medium")

    @patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_TEMPERATURE": ""}, clear=False)
    def test_settings_default_temperature_is_point_six(self) -> None:
        from git_tools.settings.settings import GitToolsSettings

        self.assertEqual(GitToolsSettings().default_temperature, 0.6)

    @patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_MAX_TOKENS": ""}, clear=False)
    def test_settings_default_max_tokens_is_32k(self) -> None:
        from git_tools.settings.settings import GitToolsSettings

        # Default (and empty-string fallback) is the bumped 32k cap.
        self.assertEqual(GitToolsSettings().default_max_tokens, 32000)

    def test_legacy_config_env_migrates_to_settings_env(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "config.env"
            target = Path(tmp) / "settings.env"
            legacy.write_text('GIT_TOOLS_PROVIDER="openrouter"\n')

            with (
                patch.object(settings_module, "LEGACY_SETTINGS_PATH", legacy),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
            ):
                settings_module._migrate_legacy_settings_file()

            self.assertFalse(legacy.exists())
            self.assertEqual(target.read_text(), 'GIT_TOOLS_PROVIDER="openrouter"\n')

    def test_save_setting_preserves_backslashes_when_updating(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            path.write_text('GIT_TOOLS_DEFAULT_MODEL="old"\n')
            with patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path):
                self.assertTrue(
                    settings_module.save_setting("GIT_TOOLS_DEFAULT_MODEL", r"a\1b")
                )
            self.assertIn('GIT_TOOLS_DEFAULT_MODEL="a\\1b"', path.read_text())

    def test_save_settings_atomically_applies_multiple_updates(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            path.write_text('UNRELATED="keep"\nGIT_TOOLS_PROVIDER="openrouter"\n')
            with patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path):
                self.assertTrue(
                    settings_module.save_settings(
                        {
                            "KIMICODE_API_KEY": r"a\1b",
                            "GIT_TOOLS_PROVIDER": "kimicli",
                            "GIT_TOOLS_DEFAULT_MODEL": "kimi-k2.5",
                        }
                    )
                )

            content = path.read_text()
            self.assertIn('UNRELATED="keep"', content)
            self.assertIn('KIMICODE_API_KEY="a\\1b"', content)
            self.assertIn('GIT_TOOLS_PROVIDER="kimicli"', content)
            self.assertIn('GIT_TOOLS_DEFAULT_MODEL="kimi-k2.5"', content)

    def test_save_settings_replace_failure_keeps_original_and_cleans_temp(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            original = 'GIT_TOOLS_PROVIDER="openrouter"\n'
            path.write_text(original)
            with (
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path),
                patch.object(Path, "replace", side_effect=OSError("rename failed")),
            ):
                with self.assertRaisesRegex(OSError, "rename failed"):
                    settings_module.save_settings(
                        {"GIT_TOOLS_PROVIDER": "kimicli"}
                    )

            self.assertEqual(path.read_text(), original)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*")), [])

    def test_settings_env_wins_over_surviving_legacy_file(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "config.env"
            target = Path(tmp) / "settings.env"
            legacy.write_text('OPENROUTER_API_KEY="stale-key"\n')
            target.write_text('OPENROUTER_API_KEY="fresh-key"\n')

            with (
                patch.object(settings_module, "LEGACY_SETTINGS_PATH", legacy),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
                patch.dict(os.environ, {}, clear=False),
            ):
                os.environ.pop("OPENROUTER_API_KEY", None)
                # Once settings.env exists, the surviving legacy file is dropped
                # from the search list so it can never shadow fresh values.
                self.assertNotIn(legacy, settings_module._get_env_file_paths())
                configured, value = settings_module.check_api_key_configured("openrouter")

            self.assertTrue(configured)
            self.assertEqual(value, "fresh-key")

    def test_reload_settings_refreshes_singleton_in_place(self) -> None:
        from git_tools.settings import settings as settings_module

        original = settings_module.settings.default_temperature
        try:
            with patch.dict(
                os.environ, {"GIT_TOOLS_DEFAULT_TEMPERATURE": "1.5"}, clear=False
            ):
                settings_module.reload_settings()
                self.assertEqual(settings_module.settings.default_temperature, 1.5)
        finally:
            settings_module.reload_settings()
        self.assertEqual(settings_module.settings.default_temperature, original)

    def test_legacy_migration_never_overwrites_settings_env(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "config.env"
            target = Path(tmp) / "settings.env"
            legacy.write_text('GIT_TOOLS_PROVIDER="kimicli"\n')
            target.write_text('GIT_TOOLS_PROVIDER="openrouter"\n')

            with (
                patch.object(settings_module, "LEGACY_SETTINGS_PATH", legacy),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
            ):
                settings_module._migrate_legacy_settings_file()

            self.assertTrue(legacy.exists())
            self.assertEqual(target.read_text(), 'GIT_TOOLS_PROVIDER="openrouter"\n')


if __name__ == "__main__":
    unittest.main()

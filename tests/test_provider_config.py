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

    def test_openrouter_default_is_agent_clis_and_the_catalog_is_live(self) -> None:
        from git_tools.providers import openrouter
        from git_tools.settings.mappings import DEFAULT_OPENROUTER_MODEL, _BUILTIN_PROVIDERS

        self.assertEqual(DEFAULT_OPENROUTER_MODEL, openrouter.DEFAULT_MODEL)
        self.assertEqual(PROVIDERS["openrouter"]["default_model"], openrouter.DEFAULT_MODEL)
        # No static list: the live catalog (plus manually saved ids) is the picker.
        self.assertEqual(_BUILTIN_PROVIDERS["openrouter"]["models"], {})

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

    def test_display_token_usage_accepts_nullable_kimi_details(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        response = {
            "response_metadata": {
                "token_usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "completion_tokens_details": None,
                    "cost_details": None,
                }
            }
        }

        with patch("git_tools.generators.base.console.print") as print_mock:
            generator.display_token_usage(response)

        panel_calls = [call for call in print_mock.call_args_list if call.args]
        self.assertEqual(len(panel_calls), 1)
        self.assertEqual(print_mock.call_args.args, ())  # panel-owned trailing blank
        panel = panel_calls[0].args[0]
        rendered = str(panel.renderable)
        self.assertIn("120", rendered)
        self.assertIn("30", rendered)
        self.assertIn("150", rendered)
        self.assertNotIn("Reasoning", rendered)

    def test_display_token_usage_ignores_malformed_metadata(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch("git_tools.generators.base.console.print") as print_mock:
            generator.display_token_usage({"response_metadata": None})
            generator.display_token_usage(
                {"response_metadata": {"token_usage": None}}
            )

        print_mock.assert_not_called()

    def test_create_kimicli_client_sets_headers_and_extra_body(self) -> None:
        from git_tools.settings import settings as settings_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = KimiCLIConfig(
            KIMICODE_API_KEY="sk-kimi-test",
            GIT_TOOLS_API_BASE="https://api.kimi.com/coding/v1",
        )

        # The settings singleton reads ~/.git-tools/settings.env at import, so
        # a saved tier or thinking choice must be patched out for "nothing
        # configured" to hold on every machine.
        with (patch("langchain_openai.ChatOpenAI") as chat_openai,
              patch.object(settings_module.settings, "default_reasoning_effort", None),
              patch.object(settings_module.settings, "kimi_thinking", None)):
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
        # Nothing configured: nothing thinking-related is sent (agent-core).
        self.assertEqual(kwargs["extra_body"], {})
        # The configured temperature goes through, as for every provider.
        self.assertEqual(kwargs["temperature"], 0.2)

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
        self.assertEqual(config.base_url, "http://127.0.0.1:8317/v1")

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
        from git_tools.settings import settings as settings_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        provider_config = CLIProxyAPIConfig(CLIPROXYAPI_API_KEY="cliproxyapi")

        with (patch("langchain_openai.ChatOpenAI") as chat_openai,
              patch.object(settings_module.settings, "default_reasoning_effort", "xhigh")):
            generator._create_cliproxy_client(
                "gpt-5.5",
                provider_config,
                temperature=0.2,
                max_tokens=8000,
            )

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.5")
        self.assertEqual(kwargs["api_key"], "cliproxyapi")
        self.assertEqual(kwargs["base_url"], "http://127.0.0.1:8317/v1")
        self.assertIn("Session_id", kwargs["default_headers"])
        self.assertTrue(kwargs["default_headers"]["Session_id"].startswith("git-tools-"))
        # The configured temperature is sent through the proxy (it accepts it).
        self.assertEqual(kwargs["temperature"], 0.2)
        # The completion cap is forwarded (relies on the 32k global default for headroom).
        self.assertEqual(kwargs["max_tokens"], 8000)
        # The configured tier is forwarded to a reasoning model.
        self.assertEqual(kwargs["reasoning_effort"], "xhigh")

    def test_cliproxy_client_forwards_the_configured_tier(self) -> None:
        # settings is a singleton loaded at import; patch the resolved value to
        # emulate GIT_TOOLS_REASONING_EFFORT being set. There is no per-model
        # default to beat any more: as in agent-core, unset means nothing is sent.
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

    def test_reasoning_effort_needs_a_reasoning_model(self) -> None:
        from git_tools.settings import settings as settings_module

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch.object(settings_module.settings, "default_reasoning_effort", "low"):
            self.assertIsNone(generator._resolve_reasoning_effort("plain-model"))
            self.assertEqual(generator._resolve_reasoning_effort("gpt-6-astra"), "low")
        with patch.object(settings_module.settings, "default_reasoning_effort", "none"):
            self.assertIsNone(generator._resolve_reasoning_effort("gpt-6-astra"))
        with patch.object(settings_module.settings, "default_reasoning_effort", None):
            self.assertIsNone(generator._resolve_reasoning_effort("gpt-6-astra"))

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

    def test_xdg_config_env_migrates_creating_settings_directory(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            legacy = home / ".config" / "git-tools" / "config.env"
            target = home / ".git-tools" / "settings.env"
            legacy.parent.mkdir(parents=True)
            content = 'GIT_TOOLS_PROVIDER="kimicli"\n'
            legacy.write_text(content)
            with (
                patch.object(settings_module, "XDG_LEGACY_SETTINGS_PATH", legacy),
                patch.object(
                    settings_module, "LEGACY_SETTINGS_PATH", target.parent / "config.env"
                ),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
            ):
                settings_module._migrate_legacy_settings_file()
                self.assertNotIn(legacy, settings_module._get_env_file_paths())

            self.assertFalse(legacy.exists())
            self.assertEqual(target.read_text(), content)

    def test_xdg_migration_failure_keeps_legacy_settings_readable(self) -> None:
        from git_tools.settings import settings as settings_module

        for failing_operation in ("mkdir", "replace"):
            with (
                self.subTest(failing_operation=failing_operation),
                tempfile.TemporaryDirectory() as tmp,
            ):
                home = Path(tmp)
                legacy = home / ".config" / "git-tools" / "config.env"
                target = home / ".git-tools" / "settings.env"
                legacy.parent.mkdir(parents=True)
                legacy.write_text(
                    'OPENROUTER_API_KEY="legacy-key"\n'
                    'GIT_TOOLS_DEFAULT_TEMPERATURE="1.25"\n'
                )
                with (
                    patch.object(settings_module, "XDG_LEGACY_SETTINGS_PATH", legacy),
                    patch.object(
                        settings_module, "LEGACY_SETTINGS_PATH", target.parent / "config.env"
                    ),
                    patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
                    patch.object(Path, failing_operation, side_effect=OSError("migration denied")),
                    patch.dict(os.environ, {}, clear=True),
                ):
                    settings_module._migrate_legacy_settings_file()
                    self.assertIn(legacy, settings_module._get_env_file_paths())
                    self.assertEqual(
                        settings_module.check_api_key_configured("openrouter"),
                        (True, "legacy-key"),
                    )
                    self.assertEqual(
                        settings_module.GitToolsSettings(
                            _env_file=settings_module._get_env_file_paths()
                        ).default_temperature,
                        1.25,
                    )

                self.assertTrue(legacy.exists())
                self.assertFalse(target.exists())

    def test_xdg_migration_never_overwrites_existing_settings(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            xdg_legacy = home / ".config" / "git-tools" / "config.env"
            legacy = home / ".git-tools" / "config.env"
            target = legacy.parent / "settings.env"
            xdg_legacy.parent.mkdir(parents=True)
            legacy.parent.mkdir(parents=True)
            xdg_legacy.write_text('OPENROUTER_API_KEY="xdg-stale"\n')
            legacy.write_text('OPENROUTER_API_KEY="old-stale"\n')
            content = 'OPENROUTER_API_KEY="fresh-key"\n'
            target.write_text(content)
            with (
                patch.object(settings_module, "XDG_LEGACY_SETTINGS_PATH", xdg_legacy),
                patch.object(settings_module, "LEGACY_SETTINGS_PATH", legacy),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
                patch.object(Path, "replace") as replace,
                patch.dict(os.environ, {}, clear=True),
            ):
                settings_module._migrate_legacy_settings_file()
                replace.assert_not_called()
                paths = settings_module._get_env_file_paths()
                self.assertNotIn(xdg_legacy, paths)
                self.assertNotIn(legacy, paths)
                self.assertEqual(
                    settings_module.check_api_key_configured("openrouter"),
                    (True, "fresh-key"),
                )
            self.assertEqual(target.read_text(), content)
            self.assertTrue(xdg_legacy.exists())
            self.assertTrue(legacy.exists())

    def test_git_tools_legacy_migration_takes_priority_over_xdg(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            xdg_legacy = home / "xdg-config.env"
            legacy = home / "config.env"
            target = home / "settings.env"
            xdg_legacy.write_text('GIT_TOOLS_PROVIDER="openrouter"\n')
            legacy.write_text('GIT_TOOLS_PROVIDER="kimicli"\n')
            with (
                patch.object(settings_module, "XDG_LEGACY_SETTINGS_PATH", xdg_legacy),
                patch.object(settings_module, "LEGACY_SETTINGS_PATH", legacy),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", target),
            ):
                settings_module._migrate_legacy_settings_file()
            self.assertEqual(target.read_text(), 'GIT_TOOLS_PROVIDER="kimicli"\n')
            self.assertFalse(legacy.exists())
            self.assertTrue(xdg_legacy.exists())

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

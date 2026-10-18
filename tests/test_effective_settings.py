"""Regression tests for shared effective config and settings-first CLI UX."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import typer
from pydantic import ValidationError
from typer.testing import CliRunner

from git_tools import cli
from git_tools.generators.base import plain_title
from git_tools.settings import settings as config


class SettingsTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.local = self.root / "git-tools.env"
        self.user = self.root / "settings.env"
        for patcher in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "DEFAULT_SETTINGS_PATH", self.user),
            patch.object(config, "_get_env_file_paths", return_value=[self.local, self.user]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runner = CliRunner()


class IsolatedSettingsTests(SettingsTestCase):
    def test_every_provider_config_shares_alias_and_constructor_precedence(self):
        self.local.write_text('GIT_TOOLS_API_BASE="https://local.invalid/v1"\n')
        for provider in cli.PROVIDERS:
            with self.subTest(provider=provider):
                key_env = config.provider_api_key_env(provider)
                endpoint_env = config.provider_base_url_env(provider)
                self.user.write_text(f'{key_env}="saved-key"\n{endpoint_env}="https://user.invalid/v1"\n')
                self.assertEqual(config.load_provider_config(provider).base_url, "https://user.invalid/v1")
                self.assertEqual(config.check_api_key_configured(provider), (True, "saved-key"))
                with patch.dict(os.environ, {endpoint_env: "https://env.invalid/v1", key_env: "env-key"}):
                    model = config._provider_config_class(provider)
                    self.assertEqual(model().base_url, "https://env.invalid/v1")
                    self.assertEqual(model().api_key, "env-key")
                    self.assertEqual(model(base_url="https://cli.invalid/v1", api_key="cli-key").base_url,
                                     "https://cli.invalid/v1")
                    self.assertEqual(model(base_url="https://cli.invalid/v1", api_key="cli-key").api_key,
                                     "cli-key")

    def test_precheck_and_provider_config_choose_same_user_key(self):
        self.local.write_text('OPENAI_API_KEY="local-key"\n')
        self.user.write_text('export OPENAI_API_KEY="user#key"\n')
        self.assertEqual(config.check_api_key_configured("openai"), (True, "user#key"))
        self.assertEqual(config.load_provider_config("openai").api_key, "user#key")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}):
            self.assertEqual(config.check_api_key_configured("openai"), (True, "env-key"))
            self.assertEqual(config.load_provider_config("openai").api_key, "env-key")

    def test_endpoint_aliases_resolve_by_source_not_alias_order(self):
        self.local.write_text('GIT_TOOLS_API_BASE="https://local.invalid/v1"\n')
        self.user.write_text('OPENAI_BASE_URL="https://user.invalid/v1"\nOPENAI_API_KEY="test"\n')
        self.assertEqual(config.load_provider_config("openai").base_url, "https://user.invalid/v1")
        self.assertEqual(config.effective_provider_base_url("openai")[0], "https://user.invalid/v1")
        self.user.write_text('GIT_TOOLS_API_BASE="https://saved.invalid/v1"\nOPENAI_API_KEY="test"\n')
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://env.invalid/v1"}):
            self.assertEqual(config.load_provider_config("openai").base_url, "https://env.invalid/v1")
            self.assertEqual(config.effective_provider_base_url("openai"),
                             ("https://env.invalid/v1", "environment: OPENAI_BASE_URL"))
            self.assertEqual(config.OpenAIConfig(base_url="https://cli.invalid/v1").base_url,
                             "https://cli.invalid/v1")

    def test_provider_and_model_aliases_obey_same_precedence(self):
        self.local.write_text('GIT_TOOLS_PROVIDER="openrouter"\nGIT_TOOLS_MODEL_MAIN="local"\n')
        self.user.write_text('GIT_TOOLS_DEFAULT_PROVIDER="openai"\nGIT_TOOLS_DEFAULT_MODEL="saved"\n')
        fresh = config.GitToolsSettings()
        self.assertEqual(fresh.default_provider, "openai")
        self.assertEqual(fresh.effective_main_model, "saved")
        with patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_MODEL": "env-model"}):
            self.assertEqual(config.GitToolsSettings().effective_main_model, "env-model")
            self.assertEqual(config.GitToolsSettings(main_model="cli-model").effective_main_model, "cli-model")

    def test_obsolete_shared_and_profile_model_keys_are_tolerated_and_inert(self):
        obsolete = {
            "GIT_TOOLS_MODEL_SUPPORT": "unused-support",
            "GIT_TOOLS_MODEL_SUB": "unused-sub",
            **{config.provider_profile_key(provider, "MODEL_SUPPORT"): f"unused-{provider}"
               for provider in cli.PROVIDERS},
        }
        content = "".join(f'{key}="{value}"\n' for key, value in obsolete.items())
        baseline = config.GitToolsSettings().model_dump()
        baseline_state = cli._load_settings_state()
        baseline_profiles = {provider: config.saved_provider_profile(provider) for provider in cli.PROVIDERS}
        provider_env = {config.provider_api_key_env(provider): "test-key" for provider in cli.PROVIDERS}
        provider_env["GIT_TOOLS_API_BASE"] = "https://test.invalid/v1"
        for source in ("local file", "user file", "environment"):
            with self.subTest(source=source):
                self.local.write_text(content if source == "local file" else "")
                self.user.write_text(content if source == "user file" else "")
                with patch.dict(os.environ, obsolete if source == "environment" else {}):
                    fresh = config.GitToolsSettings()
                    self.assertEqual(fresh.model_dump(), baseline)
                    self.assertFalse(hasattr(fresh, "support_model"))
                    self.assertEqual(cli._load_settings_state(), baseline_state)
                    for provider in cli.PROVIDERS:
                        self.assertEqual(config.saved_provider_profile(provider), baseline_profiles[provider])
                    with patch.dict(os.environ, provider_env):
                        for provider in cli.PROVIDERS:
                            with self.subTest(provider=provider):
                                loaded = config.load_provider_config(provider)
                                self.assertEqual(loaded.api_key, "test-key")
                                self.assertEqual(loaded.base_url, "https://test.invalid/v1")
                self.assertEqual(self.local.read_text(), content if source == "local file" else "")
                self.assertEqual(self.user.read_text(), content if source == "user file" else "")

    def test_support_role_is_absent_from_settings_schema_and_provider_profiles(self):
        obsolete_names = {"support_model", "sub_model", "GIT_TOOLS_MODEL_SUPPORT", "GIT_TOOLS_MODEL_SUB"}
        self.assertTrue(obsolete_names.isdisjoint(config.GitToolsSettings.model_fields))
        for by_alias in (False, True):
            schema = config.GitToolsSettings.model_json_schema(by_alias=by_alias)
            self.assertTrue(obsolete_names.isdisjoint(schema["properties"]))
            self.assertTrue(obsolete_names.isdisjoint(config.GitToolsSettings().model_dump(by_alias=by_alias)))
        for provider in cli.PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(set(config.saved_provider_profile(provider)), {
                    "model", "reasoning_effort", "kimi_thinking", "openrouter_provider", "api_base",
                })

    def test_unrelated_save_preserves_obsolete_entries_without_support_mirroring(self):
        obsolete = {
            "GIT_TOOLS_MODEL_SUPPORT": "saved-support",
            "GIT_TOOLS_MODEL_SUB": "saved-sub",
            config.provider_profile_key("anthropic", "MODEL_SUPPORT"): "saved-anthropic-support",
        }
        original = ('# Obsolete entries remain user-owned.\nGIT_TOOLS_PROVIDER="openai"\n'
                    + "".join(f'{key}="{value}"\n' for key, value in obsolete.items()))
        self.user.write_text(original)
        for name, value in (("temperature", "0.7"), ("main-model", "remembered-main")):
            result = self.runner.invoke(cli.app, ["settings", name, value])
            self.assertEqual(result.exit_code, 0, result.output)
        text = self.user.read_text()
        self.assertTrue(text.startswith(original))
        saved_obsolete = {line.split("=", 1)[0]: line.split("=", 1)[1]
                          for line in text.splitlines()
                          if line.split("=", 1)[0].endswith(("_MODEL_SUPPORT", "_MODEL_SUB"))}
        self.assertEqual(saved_obsolete, {key: f'"{value}"' for key, value in obsolete.items()})
        self.assertIn('GIT_TOOLS_DEFAULT_TEMPERATURE="0.7"', text)
        self.assertIn('GIT_TOOLS_OPENAI_MODEL_MAIN="remembered-main"', text)
        self.assertEqual(config.saved_provider_profile("openai")["model"], "remembered-main")
        self.assertNotIn("support_model", cli._load_settings_state())

    def test_model_config_env_file_and_explicit_overrides_are_preserved(self):
        custom = self.root / "custom.env"
        custom.write_text('OPENAI_API_KEY="custom"\nOPENAI_BASE_URL="https://custom.invalid/v1"\n'
                          'GIT_TOOLS_DEFAULT_TOKEN_LIMIT="123"\n')
        with patch.dict(config.OpenAIConfig.model_config, {"env_file": custom}), \
             patch.dict(config.GitToolsSettings.model_config, {"env_file": custom}):
            self.assertEqual(config.OpenAIConfig().api_key, "custom")
            self.assertEqual(config.OpenAIConfig().base_url, "https://custom.invalid/v1")
            self.assertEqual(config.OpenAIConfig(api_key="explicit").api_key, "explicit")
            self.assertEqual(config.GitToolsSettings().default_token_limit, 123)
            self.assertEqual(config.GitToolsSettings(_env_file=None).default_token_limit, 200000)
            with patch.dict(os.environ, {"OPENAI_API_KEY": "environment"}):
                self.assertEqual(config.OpenAIConfig().api_key, "environment")
                self.assertEqual(config.OpenAIConfig(api_key="explicit").api_key, "explicit")
        with patch.dict(config.OpenAIConfig.model_config, {"env_file": None}):
            self.assertEqual(config.OpenAIConfig(api_key="explicit").base_url,
                             cli.PROVIDERS["openai"]["default_base_url"])

    def test_empty_env_is_unset_consistently(self):
        self.user.write_text('OPENAI_API_KEY="saved"\nOPENAI_BASE_URL="https://saved.invalid/v1"\n')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GIT_TOOLS_API_BASE": ""}):
            self.assertEqual(config.check_api_key_configured("openai"), (True, "saved"))
            self.assertEqual(config.load_provider_config("openai").api_key, "saved")
            self.assertEqual(config.load_provider_config("openai").base_url, "https://saved.invalid/v1")

    def test_saved_blank_credentials_and_ordinary_settings_still_fall_through(self):
        self.local.write_text('OPENAI_API_KEY="local-key"\nGIT_TOOLS_DEFAULT_TOKEN_LIMIT="123"\n')
        self.user.write_text('OPENAI_API_KEY=""\nGIT_TOOLS_DEFAULT_TOKEN_LIMIT=""\n')
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GIT_TOOLS_DEFAULT_TOKEN_LIMIT": ""}):
            self.assertEqual(config.check_api_key_configured("openai"), (True, "local-key"))
            self.assertEqual(config.OpenAIConfig().api_key, "local-key")
            self.assertEqual(config.GitToolsSettings().default_token_limit, 123)

    def test_saved_blank_controls_and_profiles_mask_lower_file_values(self):
        fields = {
            "GIT_TOOLS_MODEL_MAIN": "local-main",
            "GIT_TOOLS_DEFAULT_MODEL": "local-legacy",
            "GIT_TOOLS_REASONING_EFFORT": "high",
            "GIT_TOOLS_OPENROUTER_PROVIDER": "old-pin",
            "GIT_TOOLS_KIMI_THINKING": "true",
            **{config.provider_profile_key("openai", field): value for field, value in (
                ("MODEL_MAIN", "local-main"),
                ("REASONING_EFFORT", "high"), ("OPENROUTER_PROVIDER", "old-pin"),
                ("KIMI_THINKING", "true"),
            )},
        }
        self.local.write_text("".join(f'{key}="{value}"\n' for key, value in fields.items()))
        self.user.write_text("".join(f'{key}=""\n' for key in fields))
        with patch.dict(os.environ, {key: "" for key in fields}):
            fresh = config.GitToolsSettings()
            self.assertIsNone(fresh.effective_main_model)
            self.assertIsNone(fresh.default_model)
            self.assertIsNone(fresh.default_reasoning_effort)
            self.assertIsNone(fresh.openrouter_provider)
            self.assertIsNone(fresh.kimi_thinking)
            for key in fields:
                self.assertEqual(config.effective_value(key), ("", f"user settings: {key}"))
            profile = config.saved_provider_profile("openai")
            for key in ("model", "reasoning_effort", "openrouter_provider", "kimi_thinking"):
                self.assertEqual(profile[key], "")

    def test_endpoint_file_clears_obey_alias_order_for_every_provider(self):
        for provider in cli.PROVIDERS:
            endpoint_env = config.provider_base_url_env(provider)
            key_env = config.provider_api_key_env(provider)
            self.local.write_text('GIT_TOOLS_API_BASE="https://local.invalid/v1"\n')
            for saved, expected, source_key in (
                (f'GIT_TOOLS_API_BASE=""\n{endpoint_env}="https://secondary.invalid/v1"\n',
                 None, "GIT_TOOLS_API_BASE"),
                (f'GIT_TOOLS_API_BASE="https://primary.invalid/v1"\n{endpoint_env}=""\n',
                 "https://primary.invalid/v1", "GIT_TOOLS_API_BASE"),
                (f'{endpoint_env}=""\n', None, endpoint_env),
            ):
                with self.subTest(provider=provider, saved=saved):
                    self.user.write_text(f'{key_env}="fake-key"\n' + saved)
                    with patch.dict(os.environ, {"GIT_TOOLS_API_BASE": "", endpoint_env: ""}):
                        self.assertEqual(config.effective_provider_base_url(provider),
                                         (expected, f"user settings: {source_key}"))
                        if provider == "qwen" and expected is None:
                            with self.assertRaises(ValidationError):
                                config.load_provider_config(provider)
                        else:
                            self.assertEqual(config.load_provider_config(provider).base_url, expected)
                    with patch.dict(os.environ, {endpoint_env: "https://env.invalid/v1"}):
                        self.assertEqual(config.load_provider_config(provider).base_url, "https://env.invalid/v1")
                        self.assertEqual(config.effective_provider_base_url(provider),
                                         ("https://env.invalid/v1", f"environment: {endpoint_env}"))

    def test_saved_blank_main_masks_legacy_alias_in_same_file(self):
        self.local.write_text('GIT_TOOLS_MODEL_MAIN="local-main"\n')
        self.user.write_text('GIT_TOOLS_MODEL_MAIN=""\nGIT_TOOLS_DEFAULT_MODEL="secondary-main"\n')
        fresh = config.GitToolsSettings()
        self.assertIsNone(fresh.effective_main_model)
        self.assertEqual(config.effective_value("GIT_TOOLS_MODEL_MAIN", "GIT_TOOLS_DEFAULT_MODEL")[0], "")

    def test_bare_dotenv_names_do_not_clear_lower_settings(self):
        self.local.write_text('GIT_TOOLS_API_BASE="https://local.invalid/v1"\n'
                              'GIT_TOOLS_REASONING_EFFORT="high"\nOPENAI_API_KEY="fake-key"\n')
        self.user.write_text('GIT_TOOLS_API_BASE\nGIT_TOOLS_REASONING_EFFORT\nOPENAI_API_KEY\n')
        self.assertEqual(config.OpenAIConfig().base_url, "https://local.invalid/v1")
        self.assertEqual(config.effective_provider_base_url("openai")[0], "https://local.invalid/v1")
        self.assertEqual(config.GitToolsSettings().default_reasoning_effort, "high")
        self.assertEqual(config.check_api_key_configured("openai"), (True, "fake-key"))

    def test_clear_commands_mask_local_effort_and_routing(self):
        self.local.write_text('GIT_TOOLS_PROVIDER="openrouter"\nGIT_TOOLS_REASONING_EFFORT="high"\n'
                              'GIT_TOOLS_OPENROUTER_PROVIDER="old-pin"\n')
        for command in (("effort", "unset"), ("openrouter-provider", "any")):
            result = self.runner.invoke(cli.app, ["settings", *command])
            self.assertEqual(result.exit_code, 0, result.output)
        fresh = config.GitToolsSettings()
        self.assertIsNone(fresh.default_reasoning_effort)
        self.assertIsNone(fresh.openrouter_provider)
        self.assertIsNone(cli._load_settings_state()["reasoning_effort"])

    def test_qwen_switch_without_endpoint_cannot_inherit_local_provider_endpoint(self):
        self.local.write_text('GIT_TOOLS_PROVIDER="openai"\nGIT_TOOLS_API_BASE="http://127.0.0.1:8317/v1"\n'
                              'DASHSCOPE_API_KEY="fake-key"\nGIT_TOOLS_REASONING_EFFORT="high"\n')
        with patch("git_tools.cli.refresh_live_models") as refresh:
            result = self.runner.invoke(cli.app, ["settings", "provider", "--non-interactive", "qwen"])
        self.assertEqual(result.exit_code, 0, result.output)
        refresh.assert_not_called()
        self.assertIn('GIT_TOOLS_API_BASE=""', self.user.read_text())
        self.assertEqual(config.effective_provider_base_url("qwen"),
                         (None, "user settings: GIT_TOOLS_API_BASE"))
        with self.assertRaises(ValidationError):
            config.load_provider_config("qwen")
        state = cli._load_settings_state()
        self.assertEqual((state["provider"], state["api_base"]), ("qwen", ""))
        self.assertIsNone(state["reasoning_effort"])

    def test_explicit_constructor_nulls_override_saved_aliases(self):
        self.user.write_text('OPENAI_API_KEY="saved-key"\nGIT_TOOLS_API_BASE="https://saved.invalid/v1"\n'
                             'GIT_TOOLS_REASONING_EFFORT="high"\nGIT_TOOLS_DEFAULT_MODEL="saved-model"\n')
        for argument in ("base_url", "GIT_TOOLS_API_BASE"):
            with self.subTest(argument=argument):
                self.assertIsNone(config.OpenAIConfig(**{argument: None}).base_url)
        for argument in ("api_key", "OPENAI_API_KEY"):
            with self.subTest(argument=argument), self.assertRaises(ValidationError):
                config.OpenAIConfig(**{argument: None})
        for argument in ("default_reasoning_effort", "GIT_TOOLS_REASONING_EFFORT"):
            with self.subTest(argument=argument):
                self.assertIsNone(config.GitToolsSettings(**{argument: None}).default_reasoning_effort)
        for argument in ("main_model", "GIT_TOOLS_MODEL_MAIN", "default_model"):
            with self.subTest(argument=argument):
                self.assertIsNone(config.GitToolsSettings(**{argument: None}).effective_main_model)

    def test_legacy_model_constructor_override_and_explicit_main_priority(self):
        self.user.write_text('GIT_TOOLS_DEFAULT_MODEL="saved-model"\n')
        with patch.dict(os.environ, {"GIT_TOOLS_MODEL_MAIN": "environment-model"}):
            fresh = config.GitToolsSettings(default_model="constructor-model")
            self.assertEqual(fresh.effective_main_model, "constructor-model")
            for argument in ("main_model", "GIT_TOOLS_MODEL_MAIN", "GIT_TOOLS_DEFAULT_MODEL"):
                with self.subTest(argument=argument):
                    fresh = config.GitToolsSettings(default_model="legacy-model", **{argument: "main-model"})
                    self.assertEqual(fresh.effective_main_model, "main-model")
                    fresh = config.GitToolsSettings(default_model="legacy-model", **{argument: None})
                    self.assertIsNone(fresh.effective_main_model)

    def test_endpoint_without_credentials_and_source_are_visible(self):
        self.user.write_text('GIT_TOOLS_PROVIDER="qwen"\nQWEN_BASE_URL="https://plan.invalid/v1"\n')
        state = cli._load_settings_state()
        self.assertFalse(state["api_configured"])
        self.assertEqual(cli._current_api_base("qwen"), "https://plan.invalid/v1")
        self.assertEqual(state["api_base_source"], "user settings: QWEN_BASE_URL")
        self.assertEqual(config.effective_provider_base_url("openai")[1], "provider default")
        rows = {row.value: plain_title(row.title) for row in cli._build_settings_choices(state)}
        self.assertIn("https://plan.invalid/v1", rows["api-base"])
        self.assertIn("user settings: QWEN_BASE_URL", rows["api-base"])

    def test_environment_source_display_does_not_expose_secrets(self):
        with patch.dict(os.environ, {
            "GIT_TOOLS_PROVIDER": "openai", "OPENAI_API_KEY": "do-not-display-this",
            "OPENAI_BASE_URL": "https://user:secret@endpoint.invalid/v1?token=private#private",
        }):
            state = cli._load_settings_state()
            text = "\n".join(plain_title(row.title) for row in cli._build_settings_choices(state))
        self.assertIn("environment: OPENAI_BASE_URL", text)
        self.assertIn("environment: OPENAI_API_KEY", text)
        self.assertIn("https://endpoint.invalid/v1", text)
        for secret in ("user:secret", "do-not-display-this", "private"):
            self.assertNotIn(secret, text)

    def test_defaults_saved_preferences_and_input_output_budgets(self):
        fresh = config.GitToolsSettings()
        self.assertFalse(fresh.commit_include_scope)
        self.assertTrue(fresh.commit_include_body)
        self.assertEqual(fresh.commit_body_style, "bullets")
        self.assertFalse(fresh.commit_include_footer)
        self.assertEqual(fresh.issue_pr_source, "b")
        for name, value in (("commit-scope", "true"), ("commit-footer", "true"),
                            ("commit-body", "false"), ("commit-body-style", "prose"),
                            ("issue-pr-source", "c"), ("commit-input-budget", "1234"),
                            ("issue-pr-input-budget", "5678"), ("output-budget", "99")):
            result = self.runner.invoke(cli.app, ["settings", name, value])
            self.assertEqual(result.exit_code, 0, result.output)
        state = cli._load_settings_state()
        self.assertTrue(state["commit_include_scope"])
        self.assertFalse(state["commit_include_body"])
        self.assertEqual(state["commit_body_style"], "prose")
        self.assertTrue(state["commit_include_footer"])
        self.assertEqual((state["issue_pr_source"], state["token_limit"], state["issue_pr_token_limit"],
                          state["max_tokens"]), ("c", 1234, 5678, 99))
        rows = {row.value: plain_title(row.title) for row in cli._build_settings_choices(state)}
        self.assertEqual(rows["max-tokens"], "Output token budget: 99")
        self.assertEqual(rows["commit-input-budget"], "Commit input token budget: 1234")
        self.assertEqual(rows["issue-pr-input-budget"], "Issue/PR input token budget: 5678")
        self.assertNotIn("support-model", rows)
        self.assertNotIn("support-model", cli._SETTINGS_EDITORS)
        self.assertNotIn("support_model", state)

    def test_invalid_new_editor_values_do_not_save(self):
        with patch.object(config, "save_setting") as save:
            for name, value in (("commit-scope", "perhaps"), ("commit-footer", "perhaps"),
                                ("commit-body", "perhaps"), ("commit-body-style", "invalid"),
                                ("issue-pr-source", "invalid"), ("commit-input-budget", "0"),
                                ("issue-pr-input-budget", "-1"), ("commit-input-budget", "abc")):
                result = self.runner.invoke(cli.app, ["settings", name, value])
                self.assertNotEqual(result.exit_code, 0, (name, result.output))
        save.assert_not_called()

    def test_invalid_source_environment_keeps_documented_fallback(self):
        with patch.dict(os.environ, {"GIT_TOOLS_ISSUE_PR_SOURCE": "invalid"}):
            self.assertEqual(config.GitToolsSettings().issue_pr_source, "b")

    def test_menu_reloads_effective_values_after_an_edit(self):
        with patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_TOKEN_LIMIT": "777"}), \
             patch("git_tools.cli._ask_with_back", side_effect=["commit-input-budget", "123", "done"]), \
             patch("git_tools.cli._build_settings_choices", wraps=cli._build_settings_choices) as rows:
            cli._run_settings_menu()
        self.assertIn('GIT_TOOLS_DEFAULT_TOKEN_LIMIT="123"', self.user.read_text())
        self.assertEqual(rows.call_args.args[0]["token_limit"], 777)

    def test_implicit_default_profile_edits_survive_switching_away_and_back(self):
        self.assertEqual(config.GitToolsSettings().default_provider, "openrouter")
        for name, value in (("main-model", "vendor/remember-me"), ("effort", "high"),
                            ("api-base", "https://remember.invalid/v1")):
            result = self.runner.invoke(cli.app, ["settings", name, value])
            self.assertEqual(result.exit_code, 0, result.output)
        profile = config.saved_provider_profile("openrouter")
        self.assertEqual(profile["model"], "vendor/remember-me")
        self.assertEqual(profile["reasoning_effort"], "high")
        self.assertEqual(profile["api_base"], "https://remember.invalid/v1")
        self.assertIsNone(config.effective_value("GIT_TOOLS_PROVIDER")[0])
        with patch("git_tools.cli.refresh_live_models", side_effect=AssertionError("network discovery")):
            for provider in ("openai", "openrouter"):
                result = self.runner.invoke(cli.app, ["settings", "provider", provider, "--non-interactive"])
                self.assertEqual(result.exit_code, 0, result.output)
        fresh = config.GitToolsSettings()
        self.assertEqual(fresh.effective_main_model, "vendor/remember-me")
        self.assertEqual(fresh.default_reasoning_effort, "high")
        self.assertEqual(config.effective_provider_base_url("openrouter")[0], "https://remember.invalid/v1")

    def test_profile_owner_uses_provider_alias_precedence_and_explicit_switch(self):
        self.local.write_text('GIT_TOOLS_PROVIDER="openrouter"\n')
        self.user.write_text('GIT_TOOLS_DEFAULT_PROVIDER="openai"\n')
        config.save_setting("GIT_TOOLS_MODEL_MAIN", "saved-model")
        self.assertEqual(config.saved_provider_profile("openai")["model"], "saved-model")
        self.assertIsNone(config.saved_provider_profile("openrouter")["model"])
        with patch.dict(os.environ, {"GIT_TOOLS_DEFAULT_PROVIDER": "anthropic"}):
            config.save_setting("GIT_TOOLS_REASONING_EFFORT", "high")
            self.assertEqual(config.saved_provider_profile("anthropic")["reasoning_effort"], "high")
            config.save_settings({"GIT_TOOLS_PROVIDER": "qwen", "GIT_TOOLS_MODEL_MAIN": "qwen/saved"})
            self.assertEqual(config.saved_provider_profile("qwen")["model"], "qwen/saved")

    def test_provider_switch_does_not_inherit_previous_providers_model(self):
        state = {"provider": "openai", "model": "old-openai-model", "api_configured": False}
        with patch("git_tools.cli.refresh_live_models") as refresh:
            cli._edit_provider(state, "cliproxyapi", interactive=False)
        refresh.assert_not_called()  # named noninteractive selection does not probe
        self.assertEqual(state["model"], cli._provider_default_model("cliproxyapi"))

    def test_endpoint_save_keeps_effective_environment_override(self):
        state = {"provider": "openai"}
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://env.invalid/v1"}), \
             patch("git_tools.cli.warning") as warning:
            cli._edit_api_base(state, "https://saved.invalid/v1")
        self.assertEqual(state["api_base"], "https://env.invalid/v1")
        self.assertEqual(state["api_base_source"], "environment: OPENAI_BASE_URL")
        warning.assert_called_once()


class WizardNavigationTests(SettingsTestCase):
    def test_back_to_original_provider_keeps_its_prewizard_endpoint_and_key(self):
        self.user.write_text('GIT_TOOLS_PROVIDER="openai"\n'
                             'GIT_TOOLS_API_BASE="https://original-openai.invalid/v1"\n'
                             'GIT_TOOLS_MODEL_MAIN="gpt-4o"\nOPENAI_API_KEY="fake-openai-key"\n')
        state = cli._load_settings_state()
        discovery_identities = []

        def choose_model(provider, current):
            provider_config = config.load_provider_config(provider)
            discovery_identities.append((provider, provider_config.base_url, provider_config.api_key))
            return "gpt-4o"

        with patch("git_tools.cli._ask_with_back", side_effect=[
            "qwen", "https://pending-qwen.invalid/v1", None, "openai",
        ]), patch("git_tools.cli._prompt_provider_api_key", side_effect=[(False, None), (True, None)]), \
             patch("git_tools.cli._choose_provider_model", side_effect=choose_model):
            cli._edit_provider(state, interactive=True)
        self.assertEqual(discovery_identities,
                         [("openai", "https://original-openai.invalid/v1", "fake-openai-key")])
        self.assertEqual(state["api_base"], "https://original-openai.invalid/v1")
        self.assertEqual(config.OpenAIConfig().base_url, "https://original-openai.invalid/v1")
        self.assertIn('OPENAI_BASE_URL="https://original-openai.invalid/v1"', self.user.read_text())
        self.assertNotIn("pending-qwen", self.user.read_text())
        self.assertNotIn("GIT_TOOLS_API_BASE", os.environ)
        self.assertNotIn("OPENAI_API_KEY", os.environ)

    def test_back_from_model_retains_pending_key_and_model_default(self):
        state = {"provider": "openrouter", "model": "old", "api_configured": False}
        with patch("git_tools.cli._prompt_provider_api_key", side_effect=[(True, "candidate"), (True, None)]) as key, \
             patch("git_tools.cli._choose_provider_model", side_effect=[None, "chosen"]), \
             patch("git_tools.cli._ask_with_back", return_value=""), \
             patch.dict(os.environ, {}, clear=True):
            cli._edit_provider(state, "openai", interactive=True)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "candidate")
        self.assertEqual(key.call_count, 2)
        self.assertIn('OPENAI_API_KEY="candidate"', self.user.read_text())
        self.assertEqual(state["model"], "chosen")

    def test_effort_back_revisits_routing_with_pending_pin_and_effort_default(self):
        state = {"provider": "openai", "model": "old", "api_configured": False}
        self.user.write_text('GIT_TOOLS_OPENROUTER_REASONING_EFFORT="high"\n')
        with patch("git_tools.cli._prompt_provider_api_key", return_value=(True, "candidate")), \
             patch("git_tools.cli._choose_provider_model", return_value="vendor/model"), \
             patch("git_tools.cli._prompt_openrouter_upstream", side_effect=["saved-pin", "saved-pin"]) as upstream, \
             patch("git_tools.cli._ask_with_back", side_effect=[None, "high"]), \
             patch("git_tools.cli.questionary.select", wraps=cli.questionary.select) as select:
            cli._edit_provider(state, "openrouter", interactive=True)
        self.assertEqual(upstream.call_args_list[1].args, ("vendor/model", "saved-pin"))
        self.assertEqual(select.call_args.kwargs["default"], "high")
        self.assertEqual(state["reasoning_effort"], "high")

    def test_back_to_provider_retains_endpoint_and_cancel_is_atomic(self):
        state = {"provider": "openrouter", "model": "old", "api_configured": False}
        original = copy.deepcopy(state)
        with patch.dict(os.environ, {"GIT_TOOLS_API_BASE": "https://original.invalid/v1"}), \
             patch("git_tools.cli._ask_with_back", side_effect=["https://pending.invalid/v1", None, "qwen", None, None]), \
             patch("git_tools.cli._prompt_provider_api_key", return_value=(False, None)), \
             patch("git_tools.cli.questionary.text", wraps=cli.questionary.text) as text, \
             patch.object(config, "save_settings") as save:
            cli._edit_provider(state, "qwen", interactive=True)
            self.assertEqual(os.environ["GIT_TOOLS_API_BASE"], "https://original.invalid/v1")
        self.assertEqual(text.call_args.kwargs["default"], "https://pending.invalid/v1")
        save.assert_not_called()
        self.assertEqual(state, original)

    def test_keyboard_interrupt_restores_pending_process_values(self):
        state = {"provider": "openrouter", "model": "old", "api_configured": False}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "old-key", "GIT_TOOLS_API_BASE": "https://old.invalid/v1"}), \
             patch("git_tools.cli._prompt_provider_api_key", return_value=(True, "candidate")), \
             patch("git_tools.cli._choose_provider_model", side_effect=KeyboardInterrupt), \
             patch.object(config, "save_settings") as save:
            with self.assertRaises(KeyboardInterrupt):
                cli._edit_provider(state, "openai", interactive=True)
            self.assertEqual(os.environ["OPENAI_API_KEY"], "old-key")
            self.assertEqual(os.environ["GIT_TOOLS_API_BASE"], "https://old.invalid/v1")
        save.assert_not_called()
        self.assertEqual(state["provider"], "openrouter")


class CommandContractTests(unittest.TestCase):
    def test_interactive_flags_are_discoverable(self):
        for command in ("commit", "issue", "pr", "bump", "init"):
            with self.subTest(command=command):
                result = CliRunner().invoke(cli.app, [command, "--help"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("--interactive", result.output)

    def test_init_defaults_overrides_explicit_interactive_mode(self):
        with patch("git_tools.generators.initgen.CommitizenInitGenerator") as generator:
            result = CliRunner().invoke(cli.app, ["init", "--interactive", "--defaults"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(generator.call_args.kwargs["interactive"])

    def test_issue_pr_copy_options_preserve_tristate(self):
        for command in ("issue", "pr"):
            for flags, expected in (([], None), (["--copy"], True), (["--no-copy"], False)):
                with self.subTest(command=command, flags=flags), \
                     patch("git_tools.generators.issueprgen.IssuePullRequestGenerator") as generator:
                    result = CliRunner().invoke(cli.app, [command, *flags])
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertIs(generator.call_args.kwargs["copy_clipboard"], expected)

    def test_expected_validation_errors_keep_message_and_nonzero_exit(self):
        for command, target, method in (("commit", "commitgen.CommitGenerator", "generate_commit"),
                                        ("issue", "issueprgen.IssuePullRequestGenerator", "generate_issue_pullrequest"),
                                        ("pr", "issueprgen.IssuePullRequestGenerator", "generate_issue_pullrequest")):
            with self.subTest(command=command), patch("git_tools.generators." + target) as generator, \
                 patch("git_tools.cli.logging.error") as log:
                getattr(generator.return_value, method).side_effect = ValueError("specific validation message")
                result = CliRunner().invoke(cli.app, [command])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("specific validation message", result.output)
            self.assertNotIn("unexpected", result.output.lower())
            log.assert_not_called()

    def test_intentional_typer_exit_is_not_swallowed(self):
        with patch("git_tools.generators.issueprgen.IssuePullRequestGenerator") as generator, \
             patch("git_tools.cli.logging.error") as log:
            generator.return_value.generate_issue_pullrequest.side_effect = typer.Exit(3)
            result = CliRunner().invoke(cli.app, ["pr"])
        self.assertEqual(result.exit_code, 3)
        self.assertNotIn("unexpected", result.output.lower())
        log.assert_not_called()

    def test_explicit_workflow_validation_does_not_become_unexpected_error(self):
        with patch("git_tools.cli.logging.error") as log:
            result = CliRunner().invoke(cli.app, ["pr", "--start-pr", "--release-pr"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Use only one", result.output)
        self.assertNotIn("unexpected", result.output.lower())
        log.assert_not_called()

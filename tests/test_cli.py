from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.generators.base import plain_title
from git_tools.settings import mappings

from git_tools.cli import (
    app,
    _build_model_choices,
    _build_provider_choices,
    _build_settings_choices,
    _edit_provider,
    _print_model_catalog_status,
)


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_no_args_non_interactive_shows_help_without_prompting(self) -> None:
        with patch("git_tools.cli.questionary.select") as select_mock:
            result = self.runner.invoke(app, [])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage:", result.output)
        self.assertIn("Commands", result.output)
        select_mock.assert_not_called()

    def test_settings_requires_interactive_terminal(self) -> None:
        with patch("git_tools.cli.questionary.select") as select_mock:
            result = self.runner.invoke(app, ["settings"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("git-tools settings requires an interactive terminal.", result.output)
        select_mock.assert_not_called()

    def test_config_command_is_gone(self) -> None:
        result = self.runner.invoke(app, ["config"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_settings_direct_value_works_without_terminal(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            with patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path):
                result = self.runner.invoke(app, ["settings", "temperature", "0.7"])

            self.assertEqual(result.exit_code, 0)
            # Rich styles the number separately, so match the parts.
            self.assertIn("Temperature set to", result.output)
            self.assertIn('GIT_TOOLS_DEFAULT_TEMPERATURE="0.7"', path.read_text())

    def test_settings_provider_switch_persists_model_for_new_provider(self) -> None:
        from git_tools.cli import _find_model_config, _provider_default_model
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            env = {
                "GIT_TOOLS_PROVIDER": "cliproxyapi",
                "GIT_TOOLS_DEFAULT_MODEL": "gpt-5.5",
            }
            with (
                patch.dict(os.environ, env, clear=False),
                patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path),
            ):
                result = self.runner.invoke(app, ["settings", "provider", "openrouter"])

            self.assertEqual(result.exit_code, 0)
            content = path.read_text()
            self.assertIn('GIT_TOOLS_PROVIDER="openrouter"', content)
            # The old provider's model must not leak to the new provider: it is
            # kept only if OpenRouter's catalogue knows it, else reset to the
            # provider default — and persisted either way.
            model_config = _find_model_config("openrouter", "gpt-5.5")
            expected = (
                model_config["model_name"]
                if model_config
                else _provider_default_model("openrouter")
            )
            self.assertIn(f'GIT_TOOLS_DEFAULT_MODEL="{expected}"', content)

    def test_settings_provider_accepts_agent_canonical_kimicode_alias(self) -> None:
        from git_tools.settings import settings as settings_module

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            with patch.object(settings_module, "DEFAULT_SETTINGS_PATH", path):
                result = self.runner.invoke(
                    app, ["settings", "provider", "kimicode"]
                )

            self.assertEqual(result.exit_code, 0)
            self.assertIn('GIT_TOOLS_PROVIDER="kimicli"', path.read_text())

    def test_interactive_provider_flow_prompts_key_before_model(self) -> None:
        from git_tools.settings import settings as settings_module

        state = {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "api_configured": False,
        }
        events: list[str] = []

        def save(updates: dict[str, str]) -> bool:
            events.append(f"save:{updates}")
            return True

        def refresh(provider: str, *, force: bool = False) -> bool:
            events.append(f"discover:{provider}:{force}")
            self.assertEqual(os.environ.get("KIMICODE_API_KEY"), "new-kimi-key")
            mappings.PROVIDERS["kimicli"]["models"] = {
                "kimi-k2.5": {"model_name": "kimi-k2.5"},
                "candidate-only": {"model_name": "candidate-only"},
            }
            return True

        answers = iter(["kimicli", "new-kimi-key", "kimi-k2.5"])
        original_models = mappings.PROVIDERS["kimicli"]["models"]
        self.addCleanup(
            mappings.PROVIDERS["kimicli"].__setitem__,
            "models",
            original_models,
        )

        with (
            patch("git_tools.cli._ask_with_back", side_effect=lambda _q: next(answers)),
            patch.object(settings_module, "save_settings", side_effect=save),
            patch("git_tools.cli.refresh_live_models", side_effect=refresh),
            patch("git_tools.cli._print_model_catalog_status"),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("KIMICODE_API_KEY", None)
            _edit_provider(state)
            self.assertEqual(os.environ.get("KIMICODE_API_KEY"), "new-kimi-key")

        self.assertEqual(
            events,
            [
                "discover:kimicli:True",
                "save:{'KIMICODE_API_KEY': 'new-kimi-key', "
                "'GIT_TOOLS_PROVIDER': 'kimicli', "
                "'GIT_TOOLS_DEFAULT_MODEL': 'kimi-k2.5', 'GIT_TOOLS_MODEL_MAIN': 'kimi-k2.5', "
                "'GIT_TOOLS_API_BASE': 'https://api.kimi.com/coding/v1', "
                "'GIT_TOOLS_MODEL_SUPPORT': 'follow-main', 'GIT_TOOLS_OPENROUTER_PROVIDER': '', "
                "'GIT_TOOLS_REASONING_EFFORT': '', 'GIT_TOOLS_KIMI_THINKING': ''}",
            ],
        )
        self.assertEqual(state["provider"], "kimicli")
        self.assertEqual(state["model"], "kimi-k2.5")
        self.assertTrue(state["api_configured"])

    def test_interactive_provider_flow_does_not_switch_when_model_is_cancelled(self) -> None:
        from git_tools.settings import settings as settings_module

        state = {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "api_configured": True,
        }
        answers = iter(["kimicli", "new-kimi-key", None, None, None])
        original_key = os.environ.get("KIMICODE_API_KEY")
        original_models = mappings.PROVIDERS["kimicli"]["models"].copy()

        def refresh(_provider: str, *, force: bool = False) -> bool:
            self.assertTrue(force)
            mappings.PROVIDERS["kimicli"]["models"] = {
                "candidate-only": {"model_name": "candidate-only"}
            }
            return True

        with (
            patch("git_tools.cli._ask_with_back", side_effect=lambda _q: next(answers)),
            patch.object(settings_module, "save_settings") as save,
            patch("git_tools.cli.refresh_live_models", side_effect=refresh),
            patch("git_tools.cli._print_model_catalog_status"),
            patch.dict(os.environ, {}, clear=False),
        ):
            _edit_provider(state)
            self.assertEqual(os.environ.get("KIMICODE_API_KEY"), original_key)
            self.assertEqual(mappings.PROVIDERS["kimicli"]["models"], original_models)

        # Key, provider, model, and process environment are transactional when
        # the model picker is cancelled.
        save.assert_not_called()
        self.assertEqual(os.environ.get("KIMICODE_API_KEY"), original_key)
        self.assertEqual(state["provider"], "openrouter")
        self.assertEqual(state["model"], "anthropic/claude-sonnet-4.6")

    def test_interactive_provider_flow_restores_key_when_atomic_save_fails(self) -> None:
        from git_tools.settings import settings as settings_module

        state = {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4.6",
            "api_configured": True,
        }
        answers = iter(["kimicli", "new-kimi-key", "kimi-k2.5"])
        original_models = mappings.PROVIDERS["kimicli"]["models"].copy()

        def refresh(_provider: str, *, force: bool = False) -> bool:
            self.assertTrue(force)
            mappings.PROVIDERS["kimicli"]["models"] = {
                "kimi-k2.5": {"model_name": "kimi-k2.5"},
                "candidate-only": {"model_name": "candidate-only"},
            }
            return True

        with (
            patch("git_tools.cli._ask_with_back", side_effect=lambda _q: next(answers)),
            patch.object(
                settings_module,
                "save_settings",
                side_effect=OSError("disk full"),
            ),
            patch("git_tools.cli.refresh_live_models", side_effect=refresh),
            patch("git_tools.cli._print_model_catalog_status"),
            patch.dict(os.environ, {"KIMICODE_API_KEY": "old-kimi-key"}, clear=False),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                _edit_provider(state)
            self.assertEqual(os.environ["KIMICODE_API_KEY"], "old-kimi-key")
            self.assertEqual(mappings.PROVIDERS["kimicli"]["models"], original_models)

        self.assertEqual(state["provider"], "openrouter")
        self.assertEqual(state["model"], "anthropic/claude-sonnet-4.6")

    def test_settings_direct_value_rejects_out_of_range(self) -> None:
        result = self.runner.invoke(app, ["settings", "temperature", "9"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Temperature must be between", result.output)

    def test_settings_unknown_name_errors(self) -> None:
        result = self.runner.invoke(app, ["settings", "bogus"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("Unknown setting: bogus", result.output)
        self.assertIn("provider", result.output)

    def test_init_uses_defaults_in_direct_mode(self) -> None:
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.chdir(tmpdir)
                result = self.runner.invoke(app, ["init"])
            finally:
                os.chdir(original_cwd)

            self.assertEqual(result.exit_code, 0)
            self.assertTrue((Path(tmpdir) / ".cz.toml").exists())
            self.assertIn("Wrote Commitizen config", result.output)

    def test_init_help_is_available(self) -> None:
        result = self.runner.invoke(app, ["init", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Create a Commitizen-compatible config", result.output)
        self.assertIn("--defaults", result.output)
        self.assertIn(".cz.toml", result.output)
        self.assertNotIn("cz.toml", result.output.replace(".cz.toml", ""))
        self.assertNotIn("pyproject.toml", result.output)

    def test_pr_help_shows_release_pr_flag(self) -> None:
        result = self.runner.invoke(app, ["pr", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--release-pr", result.output)
        self.assertIn("--hotfix-pr", result.output)
        self.assertIn("--start-pr", result.output)
        self.assertIn("--backmerge-release-pr", result.output)
        self.assertIn("--backmerge-hotfix-pr", result.output)
        self.assertIn("--no-release-pr", result.output)

    def test_commit_help_shows_workflow_flags(self) -> None:
        result = self.runner.invoke(app, ["commit", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("--workflow-kind", result.output)
        self.assertIn("open-release", result.output)

    def test_bump_help_does_not_offer_alternate_version_sources(self) -> None:
        result = self.runner.invoke(app, ["bump", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("--version-source", result.output)

    def test_commit_body_flags_preserve_tristate_and_forward_enum_values(self) -> None:
        cases = [([], None, None), (["--body"], True, None), (["--no-body"], False, None),
                 (["--body-style", "bullets"], None, "bullets"),
                 (["--body-style", "prose"], None, "prose"),
                 (["--no-body", "--body-style", "prose"], False, "prose")]
        for arguments, body, style in cases:
            with self.subTest(arguments=arguments), \
                 patch("git_tools.generators.commitgen.CommitGenerator") as generator:
                result = self.runner.invoke(app, ["commit", *arguments])
                self.assertEqual(result.exit_code, 0, result.output)
                options = generator.call_args.kwargs
                self.assertIs(options["include_body"], body)
                self.assertEqual(options["body_style"], style)
                self.assertIsNone(options["include_scope"])
                self.assertIsNone(options["include_footer"])
                generator.return_value.generate_commit.assert_called_once_with()

    def test_commit_rejects_invalid_body_style_before_generator_construction(self) -> None:
        with patch("git_tools.generators.commitgen.CommitGenerator") as generator:
            result = self.runner.invoke(app, ["commit", "--body-style", "paragraphs"])
        self.assertNotEqual(result.exit_code, 0)
        generator.assert_not_called()

    def test_commit_and_settings_help_explain_body_and_grouped_keys(self) -> None:
        import re

        commit_help = re.sub(r"\x1b\[[0-9;]*m", "", self.runner.invoke(app, ["commit", "--help"]).output)
        compact = " ".join(commit_help.replace("│", " ").split())
        self.assertIn("--body", compact)
        self.assertIn("--no-body", compact)
        self.assertIn("--body-style", compact)
        self.assertIn("multiline description", compact)
        self.assertIn("summary is always required", compact)
        settings_help = self.runner.invoke(app, ["settings", "--help"]).output
        for key in ("commit-format", "commit-scope", "commit-body", "commit-body-style", "commit-footer"):
            self.assertIn(key, settings_help)

    def test_settings_choices_group_commit_format_and_keep_direct_aliases(self) -> None:
        from git_tools.cli import _SETTINGS_EDITORS

        state = {"provider": "openai", "model": "gpt-4.1", "temperature": 0.6,
                 "max_tokens": 32000, "max_retries": 1, "api_configured": False}
        rows = {row.value: plain_title(row.title) for row in _build_settings_choices(state)}
        self.assertEqual(rows["commit-format"], "Commit format: scope off · body on · Point form · footer off")
        for key in ("commit-scope", "commit-body", "commit-body-style", "commit-footer"):
            self.assertNotIn(key, rows)
            self.assertIn(key, _SETTINGS_EDITORS)

    def test_settings_choices_show_provider_model_effort_then_api_key(self) -> None:
        state = {
            "provider": "cliproxyapi",
            "model": "gpt-5.5",
            "reasoning_effort": None,
            "temperature": 0.2,
            "max_tokens": 32000,
            "max_retries": 1,
            "api_configured": False,
        }

        titles = [plain_title(choice.title) for choice in _build_settings_choices(state)]

        self.assertEqual(
            titles[:3],
            [
                "Provider: cliproxyapi",
                "Main Model: gpt-5.5",
                "API Endpoint: not configured (provider default)",
            ],
        )
        self.assertEqual(titles[-1], "Done")

    def test_settings_choices_omit_effort_when_model_has_none(self) -> None:
        state = {
            "provider": "kimicli",
            "model": "kimi-k2.5",
            "reasoning_effort": "high",
            "temperature": 0.2,
            "max_tokens": 32000,
            "max_retries": 1,
            "api_configured": True,
        }

        titles = [plain_title(choice.title) for choice in _build_settings_choices(state)]

        # Kimi's tier lives in the combined thinking row (agent-cli's picker);
        # there is no separate effort row for it.
        self.assertIn("Kimi thinking: high", titles)
        self.assertFalse([title for title in titles if title.startswith("Effort:")])
        self.assertEqual(
            titles[:3],
            [
                "Provider: kimicli",
                "Main Model: kimi-k2.5",
                "API Endpoint: not configured (provider default)",
            ],
        )

    def test_settings_choices_last_row_uses_done_label(self) -> None:
        state = {
            "provider": "kimicli",
            "model": "kimi-k2.5",
            "reasoning_effort": None,
            "temperature": 0.2,
            "max_tokens": 32000,
            "max_retries": 1,
            "api_configured": True,
        }

        titles = [
            plain_title(choice.title)
            for choice in _build_settings_choices(state, done_label="← Back")
        ]

        self.assertEqual(titles[-1], "← Back")

    def test_provider_choices_are_built_from_registry_metadata(self) -> None:
        choices = _build_provider_choices("kimicli")
        titles = [plain_title(choice.title) for choice in choices]
        values = [choice.value for choice in choices]

        self.assertEqual(set(values), {"openrouter", "kimicli", "cliproxyapi", "acrc", "copilot", "qwen", "openai", "anthropic"})
        self.assertIn(
            "OpenRouter [openrouter] — https://openrouter.ai/api/v1", titles[0]
        )
        self.assertIn("Kimi Code [kimicli]", titles[values.index("kimicli")])
        self.assertIn("(current)", titles[values.index("kimicli")])
        self.assertIn("CLIProxyAPI [cliproxyapi]", titles[values.index("cliproxyapi")])

    def test_model_choices_mark_and_reorder_listed_current_model(self) -> None:
        choices = _build_model_choices(
            "kimicode",
            current_model="kimi-k2.5",
        )

        self.assertEqual(choices[0].title, "kimi-k2.5 (current)")
        self.assertEqual(choices[0].value, "kimi-k2.5")

    def test_model_choices_insert_unlisted_current_model_above_fallbacks(self) -> None:
        # A provider with a curated list (Kimi's catalog is live-only now).
        choices = _build_model_choices(
            "anthropic",
            current_model="account-only-claude",
        )

        self.assertEqual(choices[0].title, "account-only-claude (current)")
        self.assertEqual(choices[0].value, "account-only-claude")
        self.assertEqual(choices[1].title, "Claude Opus 5.5 (claude-opus-5-5)")

    def test_model_catalog_auth_failure_names_the_key_to_fix(self) -> None:
        from git_tools.settings.mappings import LiveModelRefreshError

        with (
            patch(
                "git_tools.cli.get_live_model_refresh_error",
                return_value=LiveModelRefreshError(
                    kind="auth",
                    message="model catalog request failed with HTTP 401",
                    status=401,
                ),
            ),
            patch.dict(os.environ, {"KIMICODE_API_KEY": "invalid"}, clear=False),
            patch("git_tools.cli.warning") as warn,
        ):
            _print_model_catalog_status("kimicode", False)

        message = warn.call_args.args[0]
        self.assertIn("Kimi Code model auto-detection failed (HTTP 401)", message)
        self.assertIn("KIMICODE_API_KEY in the process environment", message)
        self.assertIn("showing available saved/fallback models", message)

    def test_model_catalog_failure_reports_retained_live_catalog(self) -> None:
        from git_tools.settings.mappings import LiveModelRefreshError

        with (
            patch(
                "git_tools.cli.get_live_model_refresh_error",
                return_value=LiveModelRefreshError(
                    kind="network",
                    message="timed out",
                    retained_live_catalog=True,
                ),
            ),
            patch("git_tools.cli.warning") as warn,
        ):
            _print_model_catalog_status("openrouter", False)

        self.assertIn("showing the last successful catalog", warn.call_args.args[0])

    def test_model_choices_show_effort_and_manual_entry_for_all_providers(self) -> None:
        cliproxy_titles = [
            choice.title for choice in _build_model_choices("cliproxyapi")
        ]
        kimi_titles = [choice.title for choice in _build_model_choices("kimicode")]
        openrouter_titles = [
            choice.title for choice in _build_model_choices("openrouter")
        ]

        # Live-only providers (as in agent-cli) ship no static rows; the saved
        # model leads and manual entry closes every list.
        for titles in (cliproxy_titles, kimi_titles, openrouter_titles):
            self.assertEqual(titles[-1], "Enter a model ID manually…")
        self.assertEqual(
            _build_model_choices("cliproxyapi", current_model="gpt-6-astra")[0].title,
            "gpt-6-astra (current)",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.cli import (
    app,
    _build_model_choices,
    _build_provider_choices,
    _build_settings_choices,
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

        titles = [choice.title for choice in _build_settings_choices(state)]

        self.assertEqual(
            titles[:4],
            [
                "Provider: cliproxyapi",
                "Model: gpt-5.5",
                "Effort: xhigh (model default)",
                "API Key (cliproxyapi): not set",
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

        titles = [choice.title for choice in _build_settings_choices(state)]

        self.assertNotIn("Effort:", "\n".join(titles))
        self.assertEqual(
            titles[:3],
            [
                "Provider: kimicli",
                "Model: kimi-k2.5",
                "API Key (kimicli): configured",
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
            choice.title
            for choice in _build_settings_choices(state, done_label="← Back")
        ]

        self.assertEqual(titles[-1], "← Back")

    def test_provider_choices_are_built_from_registry_metadata(self) -> None:
        choices = _build_provider_choices("kimicli")
        titles = [choice.title for choice in choices]
        values = [choice.value for choice in choices]

        self.assertEqual(values, ["openrouter", "kimicli", "cliproxyapi"])
        self.assertIn(
            "OpenRouter [openrouter] — https://openrouter.ai/api/v1", titles[0]
        )
        self.assertIn("Kimi Code [kimicli]", titles[1])
        self.assertIn("(current)", titles[1])
        self.assertIn("CLIProxyAPI [cliproxyapi]", titles[2])

    def test_model_choices_show_effort_and_manual_entry_for_all_providers(self) -> None:
        cliproxy_titles = [
            choice.title for choice in _build_model_choices("cliproxyapi")
        ]
        kimi_titles = [choice.title for choice in _build_model_choices("kimicode")]
        openrouter_titles = [
            choice.title for choice in _build_model_choices("openrouter")
        ]

        self.assertIn("gpt-5.5 (effort: xhigh)", cliproxy_titles)
        for titles in (cliproxy_titles, kimi_titles, openrouter_titles):
            self.assertEqual(titles[-1], "Enter a model ID manually…")
        self.assertEqual(kimi_titles[0], "kimi-k2.5")


if __name__ == "__main__":
    unittest.main()

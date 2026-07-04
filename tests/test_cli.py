from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.cli import app, _build_config_choices, _build_model_choices


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

    def test_config_requires_interactive_terminal(self) -> None:
        with patch("git_tools.cli.questionary.select") as select_mock:
            result = self.runner.invoke(app, ["config"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("git-tools config requires an interactive terminal.", result.output)
        select_mock.assert_not_called()

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

    def test_config_choices_show_provider_model_effort_then_api_key(self) -> None:
        current = {
            "provider": "cliproxyapi",
            "model": "gpt-5.5",
            "reasoning_effort": None,
            "temperature": 0.2,
            "max_tokens": 32000,
            "max_retries": 1,
        }

        titles = [choice.title for choice in _build_config_choices(current, False)]

        self.assertEqual(
            titles[:4],
            [
                "Provider: cliproxyapi",
                "Model: gpt-5.5",
                "Effort: xhigh (model default)",
                "API Key (cliproxyapi): not set",
            ],
        )

    def test_config_choices_omit_effort_when_model_has_none(self) -> None:
        current = {
            "provider": "kimicli",
            "model": "kimi-k2.5",
            "reasoning_effort": "high",
            "temperature": 0.2,
            "max_tokens": 32000,
            "max_retries": 1,
        }

        titles = [choice.title for choice in _build_config_choices(current, True)]

        self.assertNotIn("Effort:", "\n".join(titles))
        self.assertEqual(
            titles[:3],
            [
                "Provider: kimicli",
                "Model: kimi-k2.5",
                "API Key (kimicli): configured",
            ],
        )

    def test_model_choices_show_effort_only_when_declared(self) -> None:
        cliproxy_titles = [
            choice.title for choice in _build_model_choices("cliproxyapi")
        ]
        kimi_titles = [choice.title for choice in _build_model_choices("kimicli")]

        self.assertIn("gpt-5.5 (effort: xhigh)", cliproxy_titles)
        self.assertEqual(kimi_titles, ["kimi-k2.5"])


if __name__ == "__main__":
    unittest.main()

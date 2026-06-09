from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from git_tools.cli import app


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
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(app, ["init"])

            self.assertEqual(result.exit_code, 0)
            self.assertTrue(Path(".cz.toml").exists())
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


if __name__ == "__main__":
    unittest.main()

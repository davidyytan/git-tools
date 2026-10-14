"""Saved Azure PR preferences, CLI editors, and runtime precedence."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError
from typer.testing import CliRunner
from git_tools.cli import app, _edit_azure_pr_limit
from git_tools.settings import settings as config
from git_tools.settings.settings import GitToolsSettings
from git_tools.generators.issueprgen import IssuePullRequestGenerator


class AzurePrSettingsTests(unittest.TestCase):
    def test_defaults_and_validation(self):
        fresh = GitToolsSettings(_env_file=None)
        self.assertEqual(fresh.azure_pr_limit, "auto")
        self.assertEqual(fresh.azure_pr_max_chars, 4000)
        for mode in ("auto", "false"):
            self.assertEqual(GitToolsSettings(_env_file=None, azure_pr_limit=mode).azure_pr_limit, mode)
        for mode in ("true", "unknown"):
            with self.assertRaises(ValidationError):
                GitToolsSettings(_env_file=None, azure_pr_limit=mode)
        for number in (0, 4001):
            with self.assertRaises(ValidationError):
                GitToolsSettings(_env_file=None, azure_pr_max_chars=number)

    def test_direct_settings_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            with patch.object(config, "DEFAULT_SETTINGS_PATH", path):
                runner = CliRunner()
                for args in (("azure-pr-limit", "false"), ("azure-pr-max-chars", "2000")):
                    result = runner.invoke(app, ["settings", *args])
                    self.assertEqual(result.exit_code, 0, result.output)
            fresh = GitToolsSettings(_env_file=path)
            self.assertEqual(fresh.azure_pr_limit, "false")
            self.assertEqual(fresh.azure_pr_max_chars, 2000)
            self.assertIn('GIT_TOOLS_AZURE_PR_MAX_CHARS="2000"', path.read_text())

    def test_invalid_direct_values_do_not_save(self):
        with patch.object(config, "save_setting") as save:
            runner = CliRunner()
            for name, value in (("azure-pr-limit", "true"), ("azure-pr-max-chars", "0"),
                                ("azure-pr-max-chars", "4001"), ("azure-pr-max-chars", "abc")):
                self.assertNotEqual(runner.invoke(app, ["settings", name, value]).exit_code, 0)
            save.assert_not_called()

    def test_interactive_mode_save_and_cancel(self):
        state = {"azure_pr_limit": "auto"}
        with patch("git_tools.cli._ask_with_back", return_value="false"), patch.object(config, "save_setting") as save:
            _edit_azure_pr_limit(state)
            save.assert_called_once_with("GIT_TOOLS_AZURE_PR_LIMIT", "false")
        with patch("git_tools.cli._ask_with_back", return_value=None), patch.object(config, "save_setting") as save:
            _edit_azure_pr_limit(state)
            save.assert_not_called()

    def test_saved_false_skips_detection_but_cli_overrides(self):
        with patch.object(config.settings, "azure_pr_limit", "false"):
            generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
            with patch.object(generator, "_get_origin_url") as origin, patch.object(generator, "prompt_confirm") as prompt:
                self.assertFalse(generator._should_apply_azure_limit())
                origin.assert_not_called()
                prompt.assert_not_called()
            forced = IssuePullRequestGenerator(generation_type="pr", azure_limit=True)
            self.assertTrue(forced._should_apply_azure_limit())

    def test_custom_limit_counts_utf16_and_retries(self):
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        with patch.object(config.settings, "azure_pr_max_chars", 2000), patch.object(generator, "generate_content", return_value={"content": "```\nshort\n```"}) as generate:
            self.assertEqual(generator._enforce_azure_pr_description_limit("x" * 2000, "input", "system"), "x" * 2000)
            generate.assert_not_called()
            self.assertEqual(generator._enforce_azure_pr_description_limit("😀" * 1001, "input", "system"), "short")
            self.assertIn("2000 characters", generate.call_args.args[1])

    def test_custom_limit_changes_interactive_prompt(self):
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
        with patch.object(config.settings, "azure_pr_limit", "auto"), patch.object(config.settings, "azure_pr_max_chars", 2000), patch.object(generator, "_get_origin_url", return_value="https://dev.azure.com/org/proj/_git/repo"), patch.object(generator, "prompt_confirm", return_value=True) as prompt:
            self.assertTrue(generator._should_apply_azure_limit())
            prompt.assert_called_once_with("Apply the 2000-character PR description limit?", default=True)

    def test_generic_cli_flags_and_legacy_aliases(self):
        runner = CliRunner()
        for flag, expected in (("--pr-limit", True), ("--no-pr-limit", False),
                               ("--azure-limit", True), ("--no-azure-limit", False)):
            with self.subTest(flag=flag), patch("git_tools.generators.issueprgen.IssuePullRequestGenerator") as generator:
                result = runner.invoke(app, ["pr", flag])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(generator.call_args.kwargs["azure_limit"], expected)
        with patch("git_tools.generators.issueprgen.IssuePullRequestGenerator") as generator:
            self.assertEqual(runner.invoke(app, ["pr"]).exit_code, 0)
            self.assertIsNone(generator.call_args.kwargs["azure_limit"])

    def test_auto_origin_matrix_and_explicit_github_limit(self):
        with patch.object(config.settings, "azure_pr_limit", "auto"):
            for url, expected in (("https://dev.azure.com/org/proj/_git/repo", True),
                                  ("https://github.com/owner/repo", False),
                                  ("https://example.com/repo.git", False), (None, False)):
                generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
                with self.subTest(url=url), patch.object(generator, "_get_origin_url", return_value=url):
                    self.assertEqual(generator._should_apply_azure_limit(), expected)
            generator = IssuePullRequestGenerator(generation_type="pr", azure_limit=True)
            with patch.object(generator, "_get_origin_url") as origin:
                self.assertTrue(generator._should_apply_azure_limit())
                origin.assert_not_called()

    def test_generic_settings_names_use_existing_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.env"
            with patch.object(config, "DEFAULT_SETTINGS_PATH", path):
                runner = CliRunner()
                self.assertEqual(runner.invoke(app, ["settings", "pr-limit", "auto"]).exit_code, 0)
                self.assertEqual(runner.invoke(app, ["settings", "pr-max-chars", "2000"]).exit_code, 0)
            fresh = GitToolsSettings(_env_file=path)
            self.assertEqual(fresh.azure_pr_limit, "auto")
            self.assertEqual(fresh.azure_pr_max_chars, 2000)

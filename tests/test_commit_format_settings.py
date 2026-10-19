"""Commit-format settings use isolated files and never discover providers."""
from __future__ import annotations

import copy
from io import StringIO
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError
from rich.console import Console
from typer.testing import CliRunner

from git_tools import cli
from git_tools.generators.base import plain_title
from git_tools.settings import settings as config


class CommitFormatSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.user = self.root / "settings.env"
        self.local = self.root / "git-tools.env"
        for patcher in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "DEFAULT_SETTINGS_PATH", self.user),
            patch.object(config, "_get_env_file_paths", return_value=[self.local, self.user]),
            patch.object(cli, "refresh_live_models", side_effect=AssertionError("provider discovery")),
            patch.object(cli, "console"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runner = CliRunner()

    def test_defaults_and_source_precedence(self):
        fresh = config.GitToolsSettings()
        self.assertEqual((fresh.commit_include_scope, fresh.commit_include_body,
                          fresh.commit_body_style, fresh.commit_include_footer),
                         (False, True, "bullets", False))
        self.local.write_text('GIT_TOOLS_COMMIT_INCLUDE_BODY="false"\nGIT_TOOLS_COMMIT_BODY_STYLE="prose"\n')
        self.user.write_text('GIT_TOOLS_COMMIT_INCLUDE_BODY="true"\nGIT_TOOLS_COMMIT_BODY_STYLE="bullets"\n')
        self.assertTrue(config.GitToolsSettings().commit_include_body)
        self.assertEqual(config.GitToolsSettings().commit_body_style, "bullets")
        with patch.dict(os.environ, {"GIT_TOOLS_COMMIT_INCLUDE_BODY": "false", "GIT_TOOLS_COMMIT_BODY_STYLE": "prose"}):
            fresh = config.GitToolsSettings()
            self.assertFalse(fresh.commit_include_body)
            self.assertEqual(fresh.commit_body_style, "prose")
            explicit = config.GitToolsSettings(commit_include_body=True, commit_body_style="bullets")
            self.assertTrue(explicit.commit_include_body)
            self.assertEqual(explicit.commit_body_style, "bullets")

    def test_direct_editors_persist_only_requested_keys(self):
        self.user.write_text('GIT_TOOLS_DEFAULT_TEMPERATURE="0.37"\nOPENAI_API_KEY="fixture-key"\n')
        for name, value in (("commit-body", "off"), ("commit-body-style", "prose"),
                            ("commit-scope", "true"), ("commit-footer", "true")):
            result = self.runner.invoke(cli.app, ["settings", name, value])
            self.assertEqual(result.exit_code, 0, result.output)
        fresh = config.GitToolsSettings()
        self.assertFalse(fresh.commit_include_body)
        self.assertEqual(fresh.commit_body_style, "prose")
        self.assertTrue(fresh.commit_include_scope)
        self.assertTrue(fresh.commit_include_footer)
        self.assertEqual(fresh.default_temperature, 0.37)
        self.assertEqual(len(self.user.read_text().splitlines()), 6)
        self.assertIn('OPENAI_API_KEY="fixture-key"', self.user.read_text())

    def test_invalid_boolean_style_and_group_value_never_write(self):
        self.user.write_text('GIT_TOOLS_COMMIT_BODY_STYLE="prose"\n')
        before = self.user.read_bytes()
        for name, value in (("commit-body", "maybe"), ("commit-body", ""),
                            ("commit-body-style", "paragraph"), ("commit-body-style", ""),
                            ("commit-format", "prose")):
            with self.subTest(name=name, value=value):
                result = self.runner.invoke(cli.app, ["settings", name, value])
                self.assertNotEqual(result.exit_code, 0)
                self.assertEqual(self.user.read_bytes(), before)
        for field, value in (("commit_include_body", "maybe"), ("commit_body_style", "paragraph")):
            with self.assertRaises(ValidationError):
                config.GitToolsSettings(**{field: value})

    def test_submenu_rows_and_missing_body_default(self):
        rows = cli._build_commit_format_choices({})
        self.assertEqual([plain_title(row.title) for row in rows], [
            "Scope: off", "Description (body): on", "Description style: Point form", "Footer: off", "← Back",
        ])
        self.assertEqual(rows[-1].value, cli._BACK)
        self.assertIn("body on", cli._commit_format_summary({}))

    def test_boolean_and_style_preselect_values_and_cancel_without_saving(self):
        for editor, state, expected in (
            (cli._edit_commit_body, {}, "true"),
            (cli._edit_commit_body, {"commit_include_body": False}, "false"),
            (cli._edit_commit_scope, {"commit_include_scope": True}, "true"),
            (cli._edit_commit_footer, {}, "false"),
            (cli._edit_commit_body_style, {}, "bullets"),
            (cli._edit_commit_body_style, {"commit_body_style": "prose"}, "prose"),
        ):
            for cancel in (None, cli._BACK):
                before = copy.deepcopy(state)
                with patch.object(cli, "_ask_with_back", return_value=cancel), \
                     patch.object(cli.questionary, "select") as select, \
                     patch.object(config, "save_setting") as save:
                    editor(state)
                self.assertEqual(select.call_args.kwargs["default"], expected)
                self.assertEqual(state, before)
                save.assert_not_called()
        self.assertFalse(self.user.exists())

    def test_submenu_repeated_saves_cancel_back_reentry(self):
        state = cli._load_settings_state()
        answers = ["commit-scope", "true", "commit-body", "false",
                   "commit-body-style", "prose", "commit-footer", None, cli._BACK]
        with patch.object(cli, "_ask_with_back", side_effect=answers), \
             patch.object(cli, "_load_settings_state", side_effect=AssertionError("full reload")):
            cli._edit_commit_format(state)
        self.assertEqual((state["commit_include_scope"], state["commit_include_body"],
                          state["commit_body_style"], state["commit_include_footer"]),
                         (True, False, "prose", False))
        self.assertNotIn("FOOTER", self.user.read_text())
        fresh = cli._load_settings_state()
        with patch.object(cli, "_ask_with_back", side_effect=[None]), \
             patch.object(cli, "_build_commit_format_choices", wraps=cli._build_commit_format_choices) as rows:
            cli._edit_commit_format(fresh)
        self.assertFalse(rows.call_args.args[0]["commit_include_body"])
        self.assertEqual(rows.call_args.args[0]["commit_body_style"], "prose")

    def test_top_level_returns_after_nested_back_and_reenters(self):
        answers = ["commit-format", "commit-body", "false", cli._BACK,
                   "commit-format", "commit-body-style", "prose", None, "done"]
        with patch.object(cli, "_ask_with_back", side_effect=answers) as ask:
            cli._run_settings_menu()
        self.assertEqual(ask.call_count, len(answers))
        fresh = config.GitToolsSettings()
        self.assertFalse(fresh.commit_include_body)
        self.assertEqual(fresh.commit_body_style, "prose")

    def test_submenu_displays_effective_env_after_saved_edit(self):
        state = cli._load_settings_state()
        snapshots = []
        original = cli._build_commit_format_choices

        def capture(current):
            snapshots.append(copy.deepcopy(current))
            return original(current)

        with patch.dict(os.environ, {"GIT_TOOLS_COMMIT_INCLUDE_BODY": "true", "GIT_TOOLS_COMMIT_BODY_STYLE": "bullets"}), \
             patch.object(cli, "_ask_with_back", side_effect=["commit-body", "false", "commit-body-style", "prose", cli._BACK]), \
             patch.object(cli, "_build_commit_format_choices", side_effect=capture):
            cli._edit_commit_format(state)
        self.assertTrue(snapshots[-1]["commit_include_body"])
        self.assertEqual(snapshots[-1]["commit_body_style"], "bullets")
        self.assertIn('GIT_TOOLS_COMMIT_INCLUDE_BODY="false"', self.user.read_text())
        self.assertIn('GIT_TOOLS_COMMIT_BODY_STYLE="prose"', self.user.read_text())

    def test_group_requires_terminal_and_esc_never_saves(self):
        with patch.object(cli, "_has_interactive_terminal", return_value=False), \
             patch.object(cli, "_ask_with_back") as ask:
            result = self.runner.invoke(cli.app, ["settings", "commit-format"])
        self.assertEqual(result.exit_code, 1)
        ask.assert_not_called()
        with patch.object(cli, "_has_interactive_terminal", return_value=True), \
             patch.object(cli, "_ask_with_back", return_value=None):
            result = self.runner.invoke(cli.app, ["settings", "commit-format"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.user.exists())

    def test_submenu_rendered_save_status_has_one_gap_at_narrow_and_wide_widths(self):
        for width in (48, 120):
            with self.subTest(width=width):
                output = StringIO()
                console = Console(file=output, width=width, force_terminal=False)
                answers = iter(("commit-body-style", "prose", cli._BACK))
                def select(message, **kwargs):
                    answer = next(answers)
                    def ask():
                        for row in kwargs["choices"]:
                            console.print(plain_title(row.title), markup=False)
                        console.print(f"❯ {message}", markup=False)
                        return answer
                    return SimpleNamespace(unsafe_ask=ask)
                state = {"commit_body_style": "bullets"}
                with patch.object(cli, "console", console), \
                     patch("git_tools.generators.base.terminal.console", console), \
                     patch.object(cli.questionary, "select", side_effect=select), \
                     patch.object(cli, "_ask_with_back", side_effect=lambda q: q.unsafe_ask()):
                    cli._edit_commit_format(state)
                rendered = output.getvalue()
                self.assertNotIn("\n\n\n", rendered)
                self.assertIn("Description style saved as Prose\n\nScope: off", rendered)
                self.assertIn("Description style: Prose", rendered)
                self.assertNotIn("?:", rendered)
                self.assertEqual(state["commit_body_style"], "prose")

    def test_keyboard_interrupt_before_selection_never_writes(self):
        with patch.object(cli, "_ask_with_back", side_effect=KeyboardInterrupt), \
             patch.object(config, "save_setting") as save:
            with self.assertRaises(KeyboardInterrupt):
                cli._edit_commit_format({})
        save.assert_not_called()
        self.assertFalse(self.user.exists())

    def test_reload_singleton_in_place_reads_new_fields(self):
        original = copy.deepcopy(config.settings.__dict__)
        self.addCleanup(lambda: (config.settings.__dict__.clear(), config.settings.__dict__.update(original)))
        singleton = config.settings
        self.user.write_text('GIT_TOOLS_COMMIT_INCLUDE_BODY="false"\nGIT_TOOLS_COMMIT_BODY_STYLE="prose"\n')
        config.reload_settings()
        self.assertIs(config.settings, singleton)
        self.assertFalse(singleton.commit_include_body)
        self.assertEqual(singleton.commit_body_style, "prose")


if __name__ == "__main__":
    unittest.main()

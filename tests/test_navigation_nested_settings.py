"""Real-key Back/Esc checks for manual-entry children of settings pickers.

Run with isolated HOME/config before imports, as for test_navigation. Catalog
and persistence boundaries are mocked; real Questionary keybindings are used.
"""
from __future__ import annotations

import copy
import os
import unittest
from unittest.mock import patch

from questionary import Choice
from typer.testing import CliRunner

from git_tools import cli
from test_navigation import keyed_questions

DOWN = "\x1b[B"
ESC = "\x1b"


def state(provider="zcode", model="glm-5.3-flash"):
    return {
        "provider": provider, "model": model, "reasoning_effort": None,
        "openrouter_provider": None, "kimi_thinking": None,
        "api_configured": True, "temperature": 1.0, "max_tokens": 32000,
        "max_retries": 1,
    }


class NestedSettingsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.saved_state = state()
        self.endpoints = [cli.OpenRouterEndpoint(tag="fixture", provider_name="Fixture")]
        patches = (
            patch.dict(os.environ, {}, clear=True),
            patch("git_tools.settings.settings._get_env_file_paths", return_value=[]),
            patch("git_tools.settings.settings.check_api_key_configured", return_value=(True, "fixture-key")),
            patch("git_tools.settings.settings.save_settings"),
            patch("git_tools.settings.settings.save_setting"),
            patch.object(cli, "refresh_live_models", return_value=True),
            patch.object(cli, "_list_openrouter_endpoints", return_value=self.endpoints),
            patch.object(cli, "_current_api_base", return_value="https://fixture.invalid/v1"),
        )
        started = []
        for patcher in patches:
            started.append(patcher.start())
            self.addCleanup(patcher.stop)
        self.save_settings = started[3]
        self.save_setting = started[4]
        self.refresh = started[5]
        self.upstreams = started[6]

    def manual_model_keys(self, current):
        choices = cli._build_model_choices("zcode", current_model=current)
        start = next(i for i, row in enumerate(choices) if row.value == current)
        manual = next(i for i, row in enumerate(choices) if row.value == cli.ADD_MODEL_SENTINEL)
        return DOWN * (manual - start) + "\r"

    def assert_no_save(self):
        self.save_settings.assert_not_called()
        self.save_setting.assert_not_called()

    def test_settings_model_manual_escape_reopens_picker_then_picker_back_leaves(self):
        current = self.saved_state["model"]
        rows = cli._build_model_choices("zcode", current_model=current)
        # Picker choices append Back after the model/manual rows.
        picker_back = DOWN * len(rows) + "\r"
        for cancel_picker in (ESC, picker_back):
            with self.subTest(cancel_picker=cancel_picker), keyed_questions([
                "\r", self.manual_model_keys(current), ESC, cancel_picker, ESC,
            ]) as messages, patch.object(cli, "_load_settings_state", return_value=self.saved_state), patch.object(
                cli, "_build_settings_choices", return_value=[Choice("Model", value="model"), Choice("Done", value="done")],
            ):
                cli._run_settings_menu()
            self.assertEqual(messages[0], "Select setting to edit:")
            self.assertTrue(messages[1].startswith("Select model"))
            self.assertEqual(messages[2], "Enter zcode model ID:")
            self.assertEqual(messages[3], messages[1])
            self.assertEqual(messages[4], "Select setting to edit:")
            self.assert_no_save()
            self.assertEqual(self.saved_state["model"], current)
        self.assertEqual(self.refresh.call_count, 2)  # one discovery per editor, not per redisplay

    def test_settings_upstream_manual_escape_reopens_picker_then_picker_back_leaves(self):
        routing_state = state("openrouter", "vendor/current")
        for cancel_picker in (ESC, DOWN * 3 + "\r"):
            with self.subTest(cancel_picker=cancel_picker), keyed_questions([
                "\r", DOWN * 2 + "\r", ESC, cancel_picker, ESC,
            ]) as messages, patch.object(cli, "_load_settings_state", return_value=routing_state), patch.object(
                cli, "_build_settings_choices", return_value=[Choice("Routing", value="openrouter-provider"), Choice("Done", value="done")],
            ):
                cli._run_settings_menu()
            self.assertEqual(messages, [
                "Select setting to edit:", "OpenRouter upstream for vendor/current:",
                "Upstream slug:", "OpenRouter upstream for vendor/current:", "Select setting to edit:",
            ])
            self.assert_no_save()
            self.assertIsNone(routing_state["openrouter_provider"])
        self.assertEqual(self.upstreams.call_count, 2)

    def test_provider_wizard_manual_model_escape_keeps_draft_then_picker_escape_goes_key(self):
        original = copy.deepcopy(self.saved_state)
        with keyed_questions([
            "temporary-fixture\r", self.manual_model_keys(original["model"]), ESC, ESC, ESC, ESC,
        ]) as messages:
            cli._edit_provider(self.saved_state, "zcode", interactive=True)
        self.assertEqual(len(messages), 6)
        self.assertIn("API key", messages[0])
        self.assertTrue(messages[1].startswith("Select model"))
        self.assertEqual(messages[2], "Enter zcode model ID:")
        self.assertEqual(messages[3], messages[1])
        self.assertIn("API key", messages[4])
        self.assertEqual(messages[5], "Select provider:")
        self.assertEqual(self.saved_state, original)
        self.assertNotIn("ZCODE_API_KEY", os.environ)
        self.assertNotIn("GIT_TOOLS_API_BASE", os.environ)
        self.assert_no_save()

    def test_provider_wizard_manual_upstream_escape_reopens_upstream_before_model(self):
        routing_state = state("openrouter", "vendor/current")
        original = copy.deepcopy(routing_state)
        with keyed_questions([
            "temporary-fixture\r", "\r", DOWN * 2 + "\r", ESC, ESC, ESC, ESC, ESC,
        ]) as messages:
            cli._edit_provider(routing_state, "openrouter", interactive=True)
        self.assertEqual(len(messages), 8)
        self.assertIn("API key", messages[0])
        self.assertTrue(messages[1].startswith("Select model"))
        self.assertEqual(messages[2:5], [
            "OpenRouter upstream for vendor/current:", "Upstream slug:",
            "OpenRouter upstream for vendor/current:",
        ])
        self.assertEqual(messages[5], messages[1])
        self.assertIn("API key", messages[6])
        self.assertEqual(messages[7], "Select provider:")
        self.assertEqual(routing_state, original)
        self.assertNotIn("OPENROUTER_API_KEY", os.environ)
        self.assertNotIn("GIT_TOOLS_API_BASE", os.environ)
        self.assert_no_save()

    def test_manual_model_unchanged_enter_preserves_configured_nondefault(self):
        current = self.saved_state["model"]
        self.assertNotEqual(current, cli._provider_default_model("zcode"))
        with keyed_questions([self.manual_model_keys(current), ESC, self.manual_model_keys(current), "\r"]) as messages:
            selected = cli._choose_provider_model("zcode", current)
        self.assertEqual(selected, current)
        self.assertEqual(messages[0], messages[2])
        self.assertEqual(messages[1::2], ["Enter zcode model ID:"] * 2)
        self.assertEqual(self.refresh.call_count, 1)
        self.assert_no_save()

    def test_manual_upstream_can_be_selected_after_return_without_save(self):
        with keyed_questions([DOWN * 2 + "\r", ESC, DOWN * 2 + "\r", "Manual/Route\r"]) as messages:
            selected = cli._prompt_openrouter_upstream("vendor/current", None)
        self.assertEqual(selected, "manual/route")
        self.assertEqual(messages, ["OpenRouter upstream for vendor/current:", "Upstream slug:"] * 2)
        self.assertEqual(self.upstreams.call_count, 1)
        self.assert_no_save()

    def test_ctrl_c_in_manual_children_still_exits_direct_invocation(self):
        cases = (
            ("model", self.saved_state, [self.manual_model_keys(self.saved_state["model"]), "\x03"]),
            ("openrouter-provider", state("openrouter", "vendor/current"), [DOWN * 2 + "\r", "\x03"]),
        )
        for setting, current, keys in cases:
            with self.subTest(setting=setting), keyed_questions(keys) as messages, patch.object(
                cli, "_has_interactive_terminal", return_value=True,
            ), patch.object(cli, "_load_settings_state", return_value=current):
                result = CliRunner().invoke(cli.app, ["settings", setting])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(len(messages), 2)
            self.assertIn("Operation cancelled by user.", result.output)
            self.assertNotIn("Select command:", messages)
            self.assert_no_save()

    def test_ctrl_c_in_manual_wizard_children_restores_typed_key_without_save(self):
        cases = (
            ("zcode", self.saved_state, ["temporary-fixture\r", self.manual_model_keys(self.saved_state["model"]), "\x03"]),
            ("openrouter", state("openrouter", "vendor/current"), ["temporary-fixture\r", "\r", DOWN * 2 + "\r", "\x03"]),
        )
        for provider, current, keys in cases:
            with self.subTest(provider=provider), keyed_questions(keys), patch.object(
                cli, "_has_interactive_terminal", return_value=True,
            ), patch.object(cli, "_load_settings_state", return_value=current):
                result = CliRunner().invoke(cli.app, ["settings", "provider", provider, "--interactive"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Operation cancelled by user.", result.output)
            self.assertNotIn(cli.provider_api_key_env(provider), os.environ)
            self.assertNotIn("GIT_TOOLS_API_BASE", os.environ)
            self.assert_no_save()


if __name__ == "__main__":
    unittest.main()

"""Coding Plan effort UI and its Back semantics, without provider calls."""

from io import StringIO
import os
from unittest.mock import patch
import unittest

from rich.console import Console

from git_tools import cli
from git_tools.generators.base.terminal import plain_title
from test_navigation import keyed_questions


def state(effort=None):
    return {
        'provider': 'zcode', 'model': 'glm-5.3', 'reasoning_effort': effort,
        'api_configured': False, 'temperature': 0.6, 'max_tokens': 32000,
        'max_retries': 3,
    }


class CodingPlanEffortUITests(unittest.TestCase):
    def test_picker_has_only_native_tiers_and_explicit_server_default(self):
        choices = cli._build_effort_choices('zcode', 'glm-5.3', 'none')
        self.assertEqual([choice.value for choice in choices], ['', 'low', 'high', 'max'])
        self.assertIn('max', plain_title(choices[0].title))
        self.assertIn('thinking always enabled', plain_title(choices[0].title))
        self.assertIn('current', plain_title(choices[1].title))
        self.assertEqual(cli._effort_picker_default('zcode', 'none', choices), 'low')
        self.assertEqual(cli._effort_picker_default('zcode', None, choices), '')

    def test_effective_values_match_upstream_mapping_not_thinking_off(self):
        for configured, expected in ((None, 'max'), ('', 'max'), ('none', 'low'),
                                     ('minimal', 'low'), ('medium', 'high'), ('xhigh', 'max')):
            with self.subTest(configured=configured):
                self.assertEqual(cli._effective_effort('zcode', 'glm-5.3', configured), expected)

    def test_settings_row_explains_none_mapping_and_enabled_thinking(self):
        choices = cli._build_settings_choices(state('none'))
        row = next(choice for choice in choices if choice.value == 'effort')
        title = plain_title(row.title)
        self.assertIn('low', title)
        self.assertIn('none → low', title)
        self.assertIn('thinking always enabled', title)
        self.assertNotIn('off', title)

    def test_direct_legacy_none_is_persisted_but_reported_as_low(self):
        output = StringIO()
        saved_state = state()
        with patch.object(cli, 'console', Console(file=output, force_terminal=False)), patch('git_tools.settings.settings.save_setting') as save, patch.object(cli, 'success', side_effect=lambda message: cli.console.print(message)):
            cli._edit_effort(saved_state, 'none')
        save.assert_called_once_with('GIT_TOOLS_REASONING_EFFORT', 'none')
        self.assertEqual(saved_state['reasoning_effort'], 'none')
        self.assertIn('none → low', output.getvalue())
        self.assertIn('thinking always enabled', output.getvalue())

    def test_real_picker_escape_keeps_legacy_value_without_write(self):
        saved_state = state('none')
        with keyed_questions(['\x1b']) as messages, patch('git_tools.settings.settings.save_setting') as save:
            cli._edit_effort(saved_state)
        save.assert_not_called()
        self.assertEqual(saved_state['reasoning_effort'], 'none')
        self.assertIn('thinking always enabled', messages[0])
        self.assertIn('current: low', messages[0])

    def test_real_picker_server_default_clears_override_and_reports_max(self):
        saved_state = state()
        with keyed_questions(['\r']), patch('git_tools.settings.settings.save_setting') as save, patch.object(cli, 'success') as success:
            cli._edit_effort(saved_state)
        save.assert_called_once_with('GIT_TOOLS_REASONING_EFFORT', '')
        self.assertIsNone(saved_state['reasoning_effort'])
        self.assertIn('server default max', success.call_args.args[0])

    def test_wizard_effort_back_returns_model_then_key_then_provider_without_save(self):
        saved_state = state('none')
        original_key = os.environ.get('ZCODE_API_KEY')
        # Typed key -> model -> effort Esc -> model Esc -> key Esc -> provider Esc.
        with keyed_questions(['temporary-test-key\r', '\r', '\x1b', '\x1b', '\x1b', '\x1b']) as messages, patch.object(cli, '_current_api_base', return_value='https://api.z.ai/api/coding/paas/v4'), patch.object(cli, 'refresh_live_models', return_value=True), patch('git_tools.settings.settings.check_api_key_configured', return_value=(False, None)), patch('git_tools.settings.settings.save_settings') as save:
            cli._edit_provider(saved_state, 'zcode', interactive=True)
        save.assert_not_called()
        self.assertEqual(os.environ.get('ZCODE_API_KEY'), original_key)
        self.assertEqual(saved_state['reasoning_effort'], 'none')
        self.assertEqual(len(messages), 6)
        self.assertIn('API key', messages[0])
        self.assertTrue(messages[1].startswith('Select model'))
        self.assertIn('thinking always enabled', messages[2])
        self.assertTrue(messages[3].startswith('Select model'))
        self.assertIn('API key', messages[4])
        self.assertEqual(messages[5], 'Select provider:')

    def test_wizard_ctrl_c_after_masked_key_never_persists_draft(self):
        original_key = os.environ.get('ZCODE_API_KEY')
        with keyed_questions(['temporary-test-key\r', '\x03']), patch.object(cli, '_current_api_base', return_value='https://api.z.ai/api/coding/paas/v4'), patch.object(cli, 'refresh_live_models', return_value=True), patch('git_tools.settings.settings.check_api_key_configured', return_value=(False, None)), patch('git_tools.settings.settings.save_settings') as save:
            with self.assertRaises(KeyboardInterrupt):
                cli._edit_provider(state(), 'zcode', interactive=True)
        save.assert_not_called()
        self.assertEqual(os.environ.get('ZCODE_API_KEY'), original_key)

    def test_curated_provider_and_model_rows_include_zcode(self):
        self.assertIn('zcode', [choice.value for choice in cli._build_provider_choices('zcode')])
        models = cli._build_model_choices('zcode')
        self.assertIn('glm-5.3', [choice.value for choice in models])
        self.assertIn(cli.ADD_MODEL_SENTINEL, [choice.value for choice in models])


if __name__ == '__main__':
    unittest.main()

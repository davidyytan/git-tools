"""Executable Back/Esc/Ctrl+C checks with real Questionary key bindings."""

from __future__ import annotations

from contextlib import ExitStack, chdir, contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from git_tools import cli
from git_tools.navigation import NavigationBack, ask_with_back
from git_tools.generators.base.generator import BaseGenerator
from git_tools.generators.commitgen.generator import CommitGenerator
from git_tools.generators.issueprgen.generator import IssuePullRequestGenerator
from git_tools.generators.initgen.generator import CommitizenInitGenerator
from git_tools.generators.bumpgen.generator import BumpGenerator


@contextmanager
def keyed_questions(keys):
    """Each real prompt gets its own input pipe, avoiding cross-prompt buffering."""
    answers = iter(keys)
    messages = []
    factories = {name: getattr(questionary, name) for name in ('select', 'text', 'password')}
    with ExitStack() as stack:
        def factory(name):
            def build(message, **kwargs):
                messages.append(message)
                pipe = stack.enter_context(create_pipe_input())
                question = factories[name](message, input=pipe, output=DummyOutput(), **kwargs)
                pipe.send_text(next(answers))
                return question
            return build
        for name in factories:
            stack.enter_context(patch.object(questionary, name, side_effect=factory(name)))
        yield messages


class PromptKeyTests(unittest.TestCase):
    def test_escape_cancels_select_text_password_and_confirm_without_default(self):
        generator = BaseGenerator(interactive=True)
        calls = (
            lambda: generator.prompt_select('Choose', ['first', 'second'], default='first'),
            lambda: generator.prompt_text('Context', default='must not accept'),
            lambda: generator.prompt_password('Secret'),
            lambda: generator.prompt_confirm('Consent', default=True),
        )
        for call in calls:
            with self.subTest(call=call), keyed_questions(['\x1b']):
                with self.assertRaises(NavigationBack):
                    call()

    def test_back_row_is_selectable_and_does_not_mutate_callers_choices(self):
        generator = BaseGenerator(interactive=True)
        choices = ['one', 'two']
        with keyed_questions(['\x1b[B\x1b[B\r']):
            with self.assertRaises(NavigationBack):
                generator.prompt_select('Choose', choices)
        self.assertEqual(choices, ['one', 'two'])
        with keyed_questions(['\x1b[B\x1b[B\r']):
            with self.assertRaises(NavigationBack):
                generator.prompt_confirm('Consent')

    def test_ctrl_c_is_not_back_on_select_text_password_or_confirmation(self):
        generator = BaseGenerator(interactive=True)
        calls = (
            lambda: generator.prompt_select('Choose', ['first']),
            lambda: generator.prompt_text('Context'),
            lambda: generator.prompt_password('Secret'),
            lambda: generator.prompt_confirm('Consent'),
        )
        for call in calls:
            with self.subTest(call=call), keyed_questions(['\x03']):
                with self.assertRaises(KeyboardInterrupt):
                    call()
        self.assertFalse(issubclass(NavigationBack, KeyboardInterrupt))
        self.assertFalse(issubclass(NavigationBack, Exception))

    def test_normal_answers_and_no_still_work(self):
        generator = BaseGenerator(interactive=True)
        with keyed_questions(['\r', 'hello\r', 'secret\r', '\x1b[B\r']):
            self.assertEqual(generator.prompt_select('Choose', ['one', 'two'], default='two'), 'two')
            self.assertEqual(generator.prompt_text('Context'), 'hello')
            self.assertEqual(generator.prompt_password('Secret'), 'secret')
            self.assertFalse(generator.prompt_confirm('Consent'))

    def test_settings_escape_returns_none_and_ctrl_c_still_raises(self):
        with keyed_questions(['\x1b']):
            self.assertIsNone(cli._ask_with_back(questionary.text('Edit:')))
        with keyed_questions(['\x03']):
            with self.assertRaises(KeyboardInterrupt):
                cli._ask_with_back(questionary.text('Edit:'))

    def test_searchable_list_preserves_search_and_escape(self):
        with keyed_questions(['tw\r']):
            answer = ask_with_back(questionary.select('Search:', choices=['one', 'two', 'three'], use_search_filter=True, use_jk_keys=False))
            self.assertEqual(answer, 'two')
        with keyed_questions(['tw\x1b']):
            self.assertIsNone(ask_with_back(questionary.select('Search:', choices=['one', 'two', 'three'], use_search_filter=True, use_jk_keys=False)))


class RootRoutingTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_root_escape_exits_without_dispatch(self):
        with keyed_questions(['\x1b']) as messages, patch.object(cli, '_has_interactive_terminal', return_value=True):
            result = self.runner.invoke(cli.app, [])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ['Select command:'])

    def test_root_command_escape_and_back_row_return_root_without_generation(self):
        # Enter commit, cancel its first prompt, then Escape at root.
        for cancel in ('\x1b', '\x1b[B\x1b[B\r'):
            with self.subTest(cancel=cancel), keyed_questions(['\r', cancel, '\x1b']) as messages, patch.object(cli, '_has_interactive_terminal', return_value=True), patch.object(CommitGenerator, '_get_and_validate_diff') as diff, patch.object(CommitGenerator, '_generate_with_provider') as generate:
                result = self.runner.invoke(cli.app, [])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(messages, ['Select command:', 'Select commit mode:', 'Select command:'])
            diff.assert_not_called()
            generate.assert_not_called()
            self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())

    def test_other_root_commands_escape_back_to_root(self):
        for name, downs in (('pr', 2), ('bump', 3), ('init', 4)):
            with self.subTest(command=name), tempfile.TemporaryDirectory() as tmp, chdir(tmp), keyed_questions(['\x1b[B' * downs + '\r', '\x1b', '\x1b']) as messages, patch.object(cli, '_has_interactive_terminal', return_value=True):
                result = self.runner.invoke(cli.app, [])
                self.assertEqual(list(Path.cwd().iterdir()), [])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(messages[0], 'Select command:')
            self.assertEqual(messages[-1], 'Select command:')
            self.assertEqual(len(messages), 3)

    def test_ctrl_c_inside_root_command_exits_instead_of_returning_root(self):
        with keyed_questions(['\r', '\x03']) as messages, patch.object(cli, '_has_interactive_terminal', return_value=True):
            result = self.runner.invoke(cli.app, [])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ['Select command:', 'Select commit mode:'])
        self.assertIn('Operation cancelled by user.', result.output)
        self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())

    def test_direct_interactive_command_escape_exits_without_root(self):
        for args in (['commit', '-i'], ['pr', '-i'], ['bump', '-i']):
            with self.subTest(args=args), keyed_questions(['\x1b']) as messages:
                result = self.runner.invoke(cli.app, args)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(len(messages), 1)
            self.assertNotIn('Select command:', messages)
            self.assertNotIn('Unexpected error', result.output)

    def test_settings_escape_still_returns_one_level_then_root(self):
        # Select settings in root; enter a child; cancel child; cancel settings;
        # the root is shown again and Esc exits it.
        def choices(_state, **_kwargs):
            return [questionary.Choice('Child', value='child'), questionary.Choice('Back', value='done')]
        with keyed_questions(['\x1b[B' * 5 + '\r', '\r', '\x1b', '\x1b', '\x1b']) as messages, patch.object(cli, '_has_interactive_terminal', return_value=True), patch.object(cli, '_load_settings_state', return_value={}), patch.object(cli, '_build_settings_choices', side_effect=choices), patch.object(cli, '_SETTINGS_EDITORS', {'child': lambda _s: cli._ask_with_back(questionary.text('Child:'))}), patch.object(cli, 'reload_settings') as reload:
            result = self.runner.invoke(cli.app, [])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ['Select command:', 'Select setting to edit:', 'Child:', 'Select setting to edit:', 'Select command:'])
        reload.assert_called_once()

    def test_all_command_boundaries_route_back_and_ctrl_c_differently(self):
        targets = (
            ('commit', 'git_tools.generators.commitgen.CommitGenerator', 'generate_commit'),
            ('issue', 'git_tools.generators.issueprgen.IssuePullRequestGenerator', 'generate_issue_pullrequest'),
            ('pr', 'git_tools.generators.issueprgen.IssuePullRequestGenerator', 'generate_issue_pullrequest'),
            ('bump', 'git_tools.generators.bumpgen.BumpGenerator', 'generate_bump'),
            ('init', 'git_tools.generators.initgen.CommitizenInitGenerator', 'generate_init'),
        )
        for name, target, method in targets:
            for signal in (NavigationBack, KeyboardInterrupt):
                with self.subTest(name=name, signal=signal), patch(target) as generator:
                    getattr(generator.return_value, method).side_effect = signal
                    result = self.runner.invoke(cli.app, [name, '-i'])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertNotIn('unexpected error', result.output.lower())


class CancellationBoundaryTests(unittest.TestCase):
    def test_init_escape_before_write_has_no_config_side_effect(self):
        with tempfile.TemporaryDirectory() as tmp, keyed_questions(['\x1b']):
            root = Path(tmp)
            generator = CommitizenInitGenerator(interactive=True)
            with self.assertRaises(NavigationBack):
                generator.generate_init(cwd=root)
            self.assertEqual(list(root.iterdir()), [])

    def test_init_final_confirmation_back_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, keyed_questions(['\x1b']):
            root = Path(tmp)
            generator = CommitizenInitGenerator(version='1.0.0', tag_format='$version', interactive=True)
            with self.assertRaises(NavigationBack):
                generator.generate_init(cwd=root)
            self.assertFalse((root / '.cz.toml').exists())

    def test_bump_action_escape_never_applies_plan(self):
        generator = BumpGenerator(increment='PATCH', prerelease='alpha', yes=True, interactive=True)
        plan = SimpleNamespace(tag_behavior='test preview')
        with keyed_questions(['\x1b']), patch.object(generator, '_print_repo_context'), patch.object(generator, '_print_summary'), patch('git_tools.generators.bumpgen.generator.plan_bump', return_value=plan), patch('git_tools.generators.bumpgen.generator.print_bump_plan'), patch('git_tools.generators.bumpgen.generator.apply_bump_plan') as apply:
            with self.assertRaises(NavigationBack):
                generator.generate_bump()
        apply.assert_not_called()

    def test_generation_consent_back_never_generates_or_falls_back(self):
        generator = CommitGenerator(interactive=True)
        with keyed_questions(['\x1b']), patch.object(generator, '_build_system_message', return_value='system'), patch.object(generator, 'display_generation_settings'), patch.object(generator, '_generate_with_provider') as generate, patch.object(generator, '_handle_local_mode') as local:
            with self.assertRaises(NavigationBack):
                generator._handle_external_provider_workflow('diff')
        generate.assert_not_called()
        local.assert_not_called()

    def test_commit_confirmation_back_never_commits_or_copies(self):
        generator = CommitGenerator(interactive=True)
        with keyed_questions(['\x1b']), patch.object(generator, 'parse_commit_message', return_value='fix: navigation'), patch('git_tools.generators.commitgen.generator.subprocess.run') as commit, patch('pyperclip.copy') as copy:
            with self.assertRaises(NavigationBack):
                generator._handle_commit_action({'content': 'fix: navigation'})
        commit.assert_not_called()
        copy.assert_not_called()

    def test_clipboard_confirmation_back_never_copies(self):
        generator = BaseGenerator(interactive=True)
        with keyed_questions(['\x1b']), patch('pyperclip.copy') as copy:
            with self.assertRaises(NavigationBack):
                generator.ask_to_copy_to_clipboard('content')
        copy.assert_not_called()

    def test_key_entry_back_or_ctrl_c_never_saves_or_falls_back(self):
        for key, signal in (('\x1b', NavigationBack), ('\x03', KeyboardInterrupt)):
            generator = CommitGenerator(interactive=True, copy_clipboard=True)
            with self.subTest(key=key), keyed_questions(['\r', 'do-not-save' + key]), patch.object(generator, 'select_provider', return_value='openrouter'), patch('git_tools.settings.settings.check_api_key_configured', return_value=(False, None)), patch('git_tools.settings.settings.save_setting') as save, patch.object(generator, '_handle_local_mode') as local, patch.object(generator, '_initialize_service') as initialize, patch.object(generator, 'generate_commit_message') as generate, patch('pyperclip.copy') as copy:
                with self.assertRaises(signal):
                    generator._generate_with_provider('diff', 'system')
            for effect in (save, local, initialize, generate, copy):
                effect.assert_not_called()

    def test_issue_context_escape_never_initializes_or_generates(self):
        generator = IssuePullRequestGenerator(generation_type='issue', interactive=True)
        info = {'commit_count': 1}
        with keyed_questions(['\x1b']), patch.object(generator, 'get_default_branch', return_value='origin/develop'), patch.object(generator, 'get_commit_info', return_value=info), patch.object(generator, 'show_commit_summary'), patch.object(generator, '_collect_generation_content', return_value=('c', 'input')), patch.object(generator, '_initialize_service') as initialize, patch.object(generator, 'generate_content') as generate, patch('pyperclip.copy') as copy:
            with self.assertRaises(NavigationBack):
                generator.generate_issue_pullrequest()
        for effect in (initialize, generate, copy):
            effect.assert_not_called()

    def test_model_back_is_navigation_not_keyboard_interrupt(self):
        generator = BaseGenerator(interactive=True)
        with patch.object(generator, '_get_default_model', return_value='model'), patch('git_tools.cli._ask_model_choice', return_value=None):
            with self.assertRaises(NavigationBack):
                generator._interactive_model_selection({})

    def test_manual_model_text_escape_is_back_not_default(self):
        generator = BaseGenerator(interactive=True)
        with keyed_questions(['\x1b']), patch.object(generator, '_get_default_model', return_value='existing-model'), patch('git_tools.cli._ask_model_choice', return_value=cli.ADD_MODEL_SENTINEL):
            with self.assertRaises(NavigationBack):
                generator._interactive_model_selection({}, provider='openrouter')

    def test_stdlib_bump_and_navigation_import_without_ui_dependencies(self):
        code = '''
import importlib.abc
import sys
class BlockUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'questionary', 'rich', 'tiktoken', 'prompt_toolkit'}:
            raise ModuleNotFoundError("blocked UI", name=fullname.split('.')[0])
sys.meta_path.insert(0, BlockUI())
from git_tools.navigation import NavigationBack
from git_tools.generators.bumpgen import decide_version_strategy
assert not issubclass(NavigationBack, KeyboardInterrupt)
'''
        result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True, env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()

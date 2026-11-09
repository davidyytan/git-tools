"""Focused read-only log CLI, navigation, and backend-boundary checks."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import call, patch

import questionary
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from git_tools import cli, history
from git_tools.history import HistoryError, HistorySnapshot, LogView
from git_tools.navigation import BACK, NavigationBack


def snapshot(**updates):
    return replace(HistorySnapshot(
        branch="feature/log[red]", head="a" * 40,
        base_ref="develop", base_sha="b" * 40,
        ahead=3, behind=2, local_branches=4, remote_branches=5,
    ), **updates)


@contextmanager
def keyed_questions(keys):
    answers = iter(keys)
    messages = []
    factories = {name: getattr(questionary, name) for name in ("select", "text")}
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


class LogCliTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.current = snapshot()
        self.load = self.enterContext(patch.object(history, "history_snapshot", return_value=self.current))
        self.render = self.enterContext(patch.object(history, "render_log", return_value="* abc123 [red]literal[/red] :smile:"))
        self.terminal = self.enterContext(patch.object(cli, "_has_interactive_terminal", return_value=False))
        self.ask = self.enterContext(patch.object(cli, "_ask_with_back", return_value=BACK))
        self.select = self.enterContext(patch.object(questionary, "select", return_value=object()))
        self.text = self.enterContext(patch.object(questionary, "text", return_value=object()))

    def invoke(self, *args):
        return self.runner.invoke(cli.app, ["log", *args])

    def test_redirected_default_prints_once_without_prompts(self):
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.load.assert_called_once_with(None)
        self.render.assert_called_once_with(self.current, LogView.BRANCH, limit=30, first_parent=True)
        self.select.assert_not_called()
        self.text.assert_not_called()
        self.ask.assert_not_called()
        self.assertIn("Branch: feature/log[red]", result.output)
        self.assertIn("Base: develop (bbbbbbb)", result.output)
        self.assertIn("Ahead: 3 commits · Behind: 2 commits", result.output)
        self.assertIn("Ahead/behind counts include merged commits.", result.output)
        self.assertIn("4 local · 5 remote-tracking (cached; no fetch)", result.output)
        self.assertIn("* abc123 [red]literal[/red] :smile:", result.output)

    def test_redirected_output_has_no_console_color_even_when_forced(self):
        with patch.object(cli, "console", cli.Console(force_terminal=True, color_system="standard")):
            for args, expected in (([], 0), (["-i"], 1)):
                with self.subTest(args=args):
                    result = self.runner.invoke(cli.app, ["log", *args], color=True)
                    self.assertEqual(result.exit_code, expected, result.output)
                    self.assertNotIn(b"\x1b[", result.stdout_bytes)

    def test_single_commit_counts_use_singular(self):
        self.load.return_value = snapshot(ahead=1, behind=1)
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Ahead: 1 commit · Behind: 1 commit", result.output)

    def test_flags_forward_to_backend_without_prompts(self):
        for args, base, view, limit, parents in (
            (["--base", "main", "--limit", "7", "--all-parents"], "main", LogView.BRANCH, 7, False),
            (["-b", "origin/main", "-n", "2", "--all"], "origin/main", LogView.ALL, 2, True),
            (["--compare", "--all-parents", "--first-parent"], None, LogView.COMPARE, 30, True),
        ):
            with self.subTest(args=args):
                self.load.reset_mock()
                self.render.reset_mock()
                result = self.invoke(*args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.load.assert_called_once_with(base)
                self.render.assert_called_once_with(self.current, view, limit=limit, first_parent=parents)
                if view == LogView.COMPARE:
                    self.assertIn("< base-only commits · > current-branch-only commits", result.output)
        self.ask.assert_not_called()

    def test_option_errors_do_not_reach_backend(self):
        for args in (["--all", "--compare"], ["--limit", "0"], ["-n", "-1"], ["--limit", "oops"]):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.exit_code, 2, result.output)
        self.load.assert_not_called()
        self.render.assert_not_called()
        self.ask.assert_not_called()

    def test_explicit_interactive_requires_both_terminal_streams(self):
        for args in (["-i"], ["--interactive"]):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("requires an interactive terminal", result.output)
                self.assertIn("--no-interactive", result.output)
        self.load.assert_not_called()
        self.ask.assert_not_called()

    def test_terminal_default_and_short_interactive_override(self):
        self.terminal.return_value = True
        for args in ([], ["-i"], ["--interactive"], ["--no-interactive", "-i"]):
            with self.subTest(args=args):
                self.ask.reset_mock()
                result = self.invoke(*args)
                self.assertEqual(result.exit_code, 0, result.output)
                self.ask.assert_called_once()

    def test_no_interactive_overrides_terminal_and_preceding_flag(self):
        self.terminal.return_value = True
        for args in (["--no-interactive"], ["--interactive", "--no-interactive"]):
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.exit_code, 0, result.output)
        self.ask.assert_not_called()
        self.select.assert_not_called()

    def test_missing_default_base_is_successful_with_na_counts_and_hint(self):
        self.load.return_value = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Ahead: N/A commits · Behind: N/A commits", result.output)
        self.assertIn("use --base REF", result.output)
        self.render.assert_called_once()

    def test_direct_compare_without_base_is_actionable_error(self):
        self.load.return_value = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        result = self.invoke("--compare")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Compare view requires a base", result.output)
        self.assertIn("--base REF", result.output)
        self.render.assert_not_called()

    def test_empty_and_no_matching_results_are_successful(self):
        self.render.return_value = ""
        for head, expected in ((None, "No commits yet."), ("a" * 40, "No matching commits.")):
            with self.subTest(head=head):
                self.load.return_value = snapshot(head=head)
                result = self.invoke()
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(expected, result.output)

    def test_backend_errors_are_literal_and_do_not_prompt(self):
        for failing in (self.load, self.render):
            with self.subTest(failing=failing):
                failing.side_effect = HistoryError("Invalid ref [red]missing[/red]")
                result = self.invoke("--base", "missing")
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("Invalid ref [red]missing[/red]", result.output)
                failing.side_effect = None
        self.ask.assert_not_called()

    def test_log_does_not_initialize_clients_or_discover_models(self):
        with (
            patch.object(cli, "refresh_live_models") as discovery,
            patch("git_tools.generators.base.BaseGenerator.__init__") as generator,
            patch("requests.sessions.Session.request") as request,
        ):
            result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        discovery.assert_not_called()
        generator.assert_not_called()
        request.assert_not_called()

    def test_view_switch_more_and_parent_toggle_keep_initial_increment(self):
        self.terminal.return_value = True
        self.ask.side_effect = [LogView.COMPARE, LogView.ALL, LogView.BRANCH, "more", "more", "parents", "parents", BACK]
        result = self.invoke("--limit", "2")
        self.assertEqual(result.exit_code, 0, result.output)
        expected = [
            (LogView.BRANCH, 2, True), (LogView.COMPARE, 2, True), (LogView.ALL, 2, True),
            (LogView.BRANCH, 2, True), (LogView.BRANCH, 4, True), (LogView.BRANCH, 6, True),
            (LogView.BRANCH, 6, False), (LogView.BRANCH, 6, True),
        ]
        self.assertEqual(self.render.call_args_list, [
            call(self.current, view, limit=limit, first_parent=parents)
            for view, limit, parents in expected
        ])
        self.load.assert_called_once_with(None)

    def test_bad_base_retries_and_only_successful_edit_replaces_snapshot(self):
        self.terminal.return_value = True
        updated = snapshot(base_ref="main", base_sha="c" * 40, ahead=1, behind=4)
        self.load.side_effect = [self.current, HistoryError("Unknown ref [red]bad[/red]"), updated]
        self.ask.side_effect = ["base", "bad", "main", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Unknown ref [red]bad[/red]", result.output)
        self.assertIn("Base: main (ccccccc)", result.output)
        self.assertEqual(self.load.call_args_list, [call(None), call("bad"), call("main")])
        self.assertEqual([args.args[0] for args in self.render.call_args_list], [self.current, updated])
        self.assertEqual([args.kwargs["default"] for args in self.text.call_args_list], ["develop", "develop"])

    def test_bad_base_then_text_escape_keeps_previous_base_and_returns_to_log(self):
        self.terminal.return_value = True
        self.load.side_effect = [self.current, HistoryError("Unknown ref")]
        self.ask.side_effect = ["base", "bad", None, BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([args.args[0] for args in self.render.call_args_list], [self.current, self.current])
        self.assertEqual(self.select.call_count, 2)

    def test_compare_with_missing_base_can_select_a_base(self):
        self.terminal.return_value = True
        missing = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        self.load.side_effect = [missing, self.current]
        self.ask.side_effect = [LogView.COMPARE, "develop", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Compare view requires a base", result.output)
        self.assertEqual([args.args[1] for args in self.render.call_args_list], [LogView.BRANCH, LogView.COMPARE])

    def test_compare_base_prompt_escape_does_not_change_view(self):
        self.terminal.return_value = True
        self.load.return_value = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        self.ask.side_effect = [LogView.COMPARE, None, BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual([args.args[1] for args in self.render.call_args_list], [LogView.BRANCH, LogView.BRANCH])

    def test_initial_interactive_compare_missing_base_explains_fallback(self):
        self.terminal.return_value = True
        self.load.return_value = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        result = self.invoke("--compare")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Showing the current branch", result.output)
        self.assertEqual(self.render.call_args.args[1], LogView.BRANCH)

    def test_compare_base_reset_without_default_keeps_previous_valid_base(self):
        self.terminal.return_value = True
        self.load.side_effect = [self.current, snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)]
        self.ask.side_effect = ["base", "", None, BACK]
        result = self.invoke("--compare")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Compare view requires a base", result.output)
        self.assertEqual([args.args[0] for args in self.render.call_args_list], [self.current, self.current])

    def test_cancellation_signals_exit_cleanly_in_direct_mode(self):
        self.terminal.return_value = True
        for signal in (KeyboardInterrupt, EOFError, NavigationBack):
            with self.subTest(signal=signal):
                self.ask.side_effect = signal
                result = self.invoke("-i")
                self.assertEqual(result.exit_code, 0, result.output)
                if signal != NavigationBack:
                    self.assertIn("Operation cancelled by user.", result.output)
                self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())

    def test_root_menu_order_and_back_routing(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["log", BACK, None]
        result = self.runner.invoke(cli.app, [])
        self.assertEqual(result.exit_code, 0, result.output)
        rows = self.select.call_args_list[0].kwargs["choices"]
        self.assertEqual([row.value for row in rows], ["commit", "issue", "pr", "bump", "init", "settings", "log", "exit"])
        self.assertEqual([args.args[0] for args in self.select.call_args_list], ["Select command:", "Log options:", "Select command:"])
        self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())

    def test_root_ctrl_c_exits_without_reopening_root(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["log", KeyboardInterrupt]
        result = self.runner.invoke(cli.app, [])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.select.call_count, 2)
        self.assertIn("Operation cancelled by user.", result.output)
        self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())


class LogRealKeyTests(unittest.TestCase):
    def test_escape_and_back_route_to_root_but_ctrl_c_exits(self):
        for cancel in ("\x1b", "\x1b[B" * 6 + "\r", "\x03"):
            keys = ["\x1b[B" * 6 + "\r", cancel]
            if cancel != "\x03":
                keys.append("\x1b")
            with (
                self.subTest(cancel=cancel),
                patch.object(cli, "_has_interactive_terminal", return_value=True),
                patch.object(history, "history_snapshot", return_value=snapshot()),
                patch.object(history, "render_log", return_value="* abc subject"),
                keyed_questions(keys) as messages,
            ):
                result = CliRunner().invoke(cli.app, [])
            self.assertEqual(result.exit_code, 0, result.output)
            expected = ["Select command:", "Log options:"]
            if cancel != "\x03":
                expected.append("Select command:")
            self.assertEqual(messages, expected)
            self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())

    def test_text_escape_returns_to_log_options(self):
        with (
            patch.object(cli, "_has_interactive_terminal", return_value=True),
            patch.object(history, "history_snapshot", return_value=snapshot()) as load,
            patch.object(history, "render_log", return_value="* abc subject"),
            keyed_questions(["\x1b[B" * 5 + "\r", "\x1b", "\x1b"]) as messages,
        ):
            result = CliRunner().invoke(cli.app, ["log", "-i"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ["Log options:", "Base ref (blank uses develop):", "Log options:"])
        load.assert_called_once_with(None)


class LogImportAndTerminalTests(unittest.TestCase):
    def test_terminal_detection_requires_stdin_and_stdout(self):
        for stdin, stdout in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(stdin=stdin, stdout=stdout), patch.object(cli.sys.stdin, "isatty", return_value=stdin), patch.object(cli.sys.stdout, "isatty", return_value=stdout):
                self.assertEqual(cli._has_interactive_terminal(), stdin and stdout)

    def test_help_and_version_do_not_import_history(self):
        code = '''
import importlib.abc
import sys
from unittest.mock import patch
from typer.testing import CliRunner
class BlockHistory(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "git_tools.history":
            raise AssertionError("history imported for help/version")
sys.meta_path.insert(0, BlockHistory())
from git_tools import cli
with patch.object(cli, "_version_line", return_value="git-tools test"):
    for args in (["--version"], ["--help"], ["log", "--help"]):
        result = CliRunner().invoke(cli.app, args)
        assert result.exit_code == 0, result.output
assert "git_tools.history" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])})
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

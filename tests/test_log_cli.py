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
from git_tools.generators.base import plain_title
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
        self.render.assert_called_once_with(self.current, LogView.BRANCH, limit=30, first_parent=True, color=False)
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
                self.render.assert_called_once_with(self.current, view, limit=limit, first_parent=parents, color=False)
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
        self.ask.side_effect = ["view", LogView.COMPARE, "view", LogView.ALL, "view", LogView.BRANCH, "more", "more", "parents", "all-parents", "parents", "first-parent", BACK]
        result = self.invoke("--limit", "2")
        self.assertEqual(result.exit_code, 0, result.output)
        expected = [
            (LogView.BRANCH, 2, True), (LogView.COMPARE, 2, True), (LogView.ALL, 2, True),
            (LogView.BRANCH, 2, True), (LogView.BRANCH, 4, True), (LogView.BRANCH, 6, True),
            (LogView.BRANCH, 6, False), (LogView.BRANCH, 6, True),
        ]
        self.assertEqual(self.render.call_args_list, [
            call(self.current, view, limit=limit, first_parent=parents, color=False)
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
        self.render.assert_called_once()
        self.assertEqual(self.select.call_count, 2)
        self.assertEqual(result.output.count("Branch:"), 1)

    def test_compare_with_missing_base_can_select_a_base(self):
        self.terminal.return_value = True
        missing = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        self.load.side_effect = [missing, self.current]
        self.ask.side_effect = ["view", LogView.COMPARE, "develop", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Compare view requires a base", result.output)
        self.assertEqual([args.args[1] for args in self.render.call_args_list], [LogView.BRANCH, LogView.COMPARE])

    def test_compare_base_prompt_escape_does_not_change_view(self):
        self.terminal.return_value = True
        self.load.return_value = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        self.ask.side_effect = ["view", LogView.COMPARE, None, BACK, BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.render.assert_called_once()
        self.assertEqual([args.args[0] for args in self.select.call_args_list], ["Log options:", "Log view:", "Log view:", "Log options:"])
        self.assertEqual(self.select.call_args_list[2].kwargs["default"], LogView.COMPARE)
        self.assertEqual(result.output.count("Branch:"), 1)

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
        self.render.assert_called_once()
        self.assertEqual(result.output.count("Branch:"), 1)

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

    def test_menu_separates_settings_actions_and_shows_current_values(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["view", None, "parents", None, BACK]
        result = self.invoke("--all", "--all-parents")
        self.assertEqual(result.exit_code, 0, result.output)
        menu = self.select.call_args_list[0]
        rows = menu.kwargs["choices"]
        self.assertEqual([row.title for row in rows if isinstance(row, questionary.Separator)], ["Display settings", "Actions"])
        selectable = [row for row in rows if not isinstance(row, questionary.Separator)]
        self.assertEqual([row.value for row in selectable], ["view", "parents", "base", "more", "refresh", BACK])
        self.assertEqual([plain_title(row.title) for row in selectable[:3]], ["View: All branches", "History mode: All parents", "Base: develop"])
        self.assertEqual(plain_title(selectable[3].title), "Show more (30 → 60 commits)")
        view_picker = self.select.call_args_list[1]
        mode_picker = self.select.call_args_list[3]
        self.assertEqual(view_picker.kwargs["default"], LogView.ALL)
        self.assertIn("All branches (current)", [plain_title(row.title) for row in view_picker.kwargs["choices"]])
        self.assertEqual(mode_picker.kwargs["default"], "all-parents")
        mode_labels = [plain_title(row.title) for row in mode_picker.kwargs["choices"]]
        self.assertIn("First-parent — mainline; hide merged side commits", mode_labels)
        self.assertIn("All parents (current) — include merged branches", mode_labels)
        self.render.assert_called_once()

    def test_top_level_focus_stays_on_last_selected_row(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["more", "more", "parents", "all-parents", "view", LogView.ALL, "base", None, "refresh", BACK]
        result = self.invoke("-n", "2")
        self.assertEqual(result.exit_code, 0, result.output)
        menus = [args for args in self.select.call_args_list if args.args[0] == "Log options:"]
        self.assertEqual([args.kwargs["default"] for args in menus], ["view", "more", "more", "parents", "view", "base", "refresh"])
        more_labels = [plain_title(next(row.title for row in args.kwargs["choices"] if row.value == "more")) for args in menus]
        self.assertEqual(more_labels[:3], ["Show more (2 → 4 commits)", "Show more (4 → 6 commits)", "Show more (6 → 8 commits)"])
        self.assertEqual([args.kwargs["limit"] for args in self.render.call_args_list], [2, 4, 6, 6, 6, 6])
        self.assertEqual([args.kwargs["first_parent"] for args in self.render.call_args_list], [True, True, True, False, False, False])
        self.assertEqual(self.load.call_count, 2)  # Only initial capture and explicit Refresh.

    def test_nested_cancel_and_noop_settings_do_not_reprint_graph(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["view", None, "view", LogView.BRANCH, "parents", BACK, "parents", "first-parent", "base", None, "base", "develop", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output.count("Branch:"), 1)
        self.assertEqual(self.load.call_args_list, [call(None), call("develop")])
        self.assertEqual(self.render.call_count, 2)  # Validated base no-op, but no extra graph output.

    def test_base_render_failure_is_transactional_and_allows_back(self):
        self.terminal.return_value = True
        updated = snapshot(base_ref="main", head="d" * 40)
        self.load.side_effect = [self.current, updated]
        self.render.side_effect = ["* original", HistoryError("Commit disappeared"), "* original expanded"]
        self.ask.side_effect = ["base", "main", None, "more", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Commit disappeared", result.output)
        self.assertEqual([args.args[0] for args in self.render.call_args_list], [self.current, updated, self.current])
        self.assertNotIn("Base: main", result.output)
        self.assertEqual(result.output.count("Branch:"), 2)

    def test_refresh_retains_view_parent_mode_limit_and_explicit_base(self):
        self.terminal.return_value = True
        updated = snapshot(head="d" * 40, ahead=9)
        self.load.side_effect = [self.current, updated]
        self.ask.side_effect = ["more", "parents", "all-parents", "view", LogView.COMPARE, "refresh", "more", BACK]
        result = self.invoke("-b", "develop", "-n", "2")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.load.call_args_list, [call("develop"), call("develop")])
        self.assertEqual(self.render.call_args_list[-2:], [
            call(updated, LogView.COMPARE, limit=4, first_parent=False, color=False),
            call(updated, LogView.COMPARE, limit=6, first_parent=False, color=False),
        ])
        self.assertIn("Ahead: 9 commits", result.output)

    def test_refresh_failures_and_lost_compare_base_keep_prior_snapshot(self):
        self.terminal.return_value = True
        missing = snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)
        for updated, render_error in ((HistoryError("Repository unavailable"), False), (missing, False), (snapshot(head="d" * 40), True)):
            with self.subTest(updated=updated, render_error=render_error):
                self.load.reset_mock()
                self.render.reset_mock()
                self.load.side_effect = [self.current, updated]
                self.render.side_effect = ["* original", HistoryError("Cannot render refresh"), "* expanded"] if render_error else None
                self.ask.side_effect = ["refresh", "more", BACK]
                result = self.invoke("--compare")
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn("Refresh failed; keeping previous history.", result.output)
                self.assertEqual(self.render.call_args_list[-1], call(self.current, LogView.COMPARE, limit=60, first_parent=True, color=False))
                self.assertEqual(result.output.count("Branch:"), 2)

    def test_refresh_re_resolves_default_base_without_pinning_its_name(self):
        self.terminal.return_value = True
        updated = snapshot(base_ref="origin/develop", base_sha="d" * 40)
        self.load.side_effect = [self.current, updated]
        self.ask.side_effect = ["refresh", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.load.call_args_list, [call(None), call(None)])
        self.assertIn("Base: origin/develop", result.output)

    def test_refresh_same_snapshot_can_update_all_refs_graph(self):
        self.terminal.return_value = True
        self.render.side_effect = ["* old tagged commit", "* new tagged commit"]
        self.ask.side_effect = ["refresh", BACK]
        result = self.invoke("--all")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("* new tagged commit", result.output)
        self.assertEqual(result.output.count("Branch:"), 2)
        self.assertTrue(all(args.args[1] == LogView.ALL for args in self.render.call_args_list))

    def test_unchanged_refresh_does_not_reprint_graph(self):
        self.terminal.return_value = True
        self.ask.side_effect = ["refresh", BACK]
        result = self.invoke()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.load.call_count, 2)
        self.assertEqual(self.render.call_count, 2)
        self.assertEqual(result.output.count("Branch:"), 1)

    def test_native_ansi_becomes_styled_text_without_interpreting_subject_markup(self):
        self.render.return_value = "\x1b[31m*\x1b[m \x1b[33mabc123\x1b[m \x1b[32m(HEAD -> feature)\x1b[m [red]literal[/red] :smile:"
        colored = cli.Console(force_terminal=True, color_system="standard", no_color=False, width=120)
        with patch.object(cli, "console", colored), patch.object(cli, "_log_color_enabled", return_value=True), patch.object(cli.Text, "from_ansi", wraps=cli.Text.from_ansi) as decoded:
            result = self.runner.invoke(cli.app, ["log"], color=True)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(b"\x1b[", result.stdout_bytes)
        decoded.assert_called_once_with(self.render.return_value)
        plain = cli.Text.from_ansi(result.output).plain
        self.assertIn("* abc123 (HEAD -> feature) [red]literal[/red] :smile:", plain)
        self.assertIn("Branch: feature/log[red]", plain)
        self.render.assert_called_once_with(self.current, LogView.BRANCH, limit=30, first_parent=True, color=True)
        self.ask.assert_not_called()  # Output-only TTY color does not force interaction.

    def test_force_color_environment_and_console_cannot_color_pipe_or_errors(self):
        with patch.dict(os.environ, {"FORCE_COLOR": "1", "TERM": "xterm-256color"}), patch.object(cli, "console", cli.Console(force_terminal=True, color_system="standard", no_color=False)):
            for args in ([], ["--base", "bad"]):
                with self.subTest(args=args):
                    self.load.side_effect = HistoryError("Invalid ref [red]bad[/red]") if args else None
                    result = self.runner.invoke(cli.app, ["log", *args], color=True)
                    self.assertEqual(result.exit_code, 1 if args else 0, result.output)
                    self.assertNotIn(b"\x1b[", result.stdout_bytes)
        self.assertFalse(self.render.call_args.kwargs["color"])

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
        for cancel in ("\x1b", "\x1b[B" * 5 + "\r", "\x03"):
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
            keyed_questions(["\x1b[B" * 2 + "\r", "\x1b", "\x1b"]) as messages,
        ):
            result = CliRunner().invoke(cli.app, ["log", "-i"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ["Log options:", "Base ref (blank uses develop):", "Log options:"])
        load.assert_called_once_with(None)

    def test_view_and_history_cancel_return_one_level_without_redraw(self):
        for enter, cancel, child in (("\r", "\x1b", "Log view:"), ("\r", "\x1b[B" * 3 + "\r", "Log view:"), ("\x1b[B\r", "\x1b", "History mode:"), ("\x1b[B\r", "\x1b[B" * 2 + "\r", "History mode:")):
            with (
                self.subTest(child=child, cancel=cancel),
                patch.object(cli, "_has_interactive_terminal", return_value=True),
                patch.object(history, "history_snapshot", return_value=snapshot()),
                patch.object(history, "render_log", return_value="* abc subject") as render,
                keyed_questions([enter, cancel, "\x1b"]) as messages,
            ):
                result = CliRunner().invoke(cli.app, ["log", "-i"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(messages, ["Log options:", child, "Log options:"])
            render.assert_called_once()
            self.assertEqual(result.output.count("Branch:"), 1)

    def test_compare_base_escape_returns_to_view_picker_before_parent(self):
        with (
            patch.object(cli, "_has_interactive_terminal", return_value=True),
            patch.object(history, "history_snapshot", return_value=snapshot(base_ref=None, base_sha=None, ahead=None, behind=None)),
            patch.object(history, "render_log", return_value="* abc subject") as render,
            keyed_questions(["\r", "\x1b[B\r", "\x1b", "\x1b", "\x1b"]) as messages,
        ):
            result = CliRunner().invoke(cli.app, ["log", "-i"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ["Log options:", "Log view:", "Base ref (blank uses develop):", "Log view:", "Log options:"])
        render.assert_called_once()

    def test_repeated_enter_stays_on_show_more_without_changing_ancestry(self):
        with (
            patch.object(cli, "_has_interactive_terminal", return_value=True),
            patch.object(history, "history_snapshot", return_value=snapshot()) as load,
            patch.object(history, "render_log", return_value="* abc subject") as render,
            keyed_questions(["\x1b[B" * 3 + "\r", "\r", "\x1b"]) as messages,
        ):
            result = CliRunner().invoke(cli.app, ["log", "-i", "--all-parents"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(messages, ["Log options:"] * 3)
        self.assertEqual([args.kwargs["limit"] for args in render.call_args_list], [30, 60, 90])
        self.assertTrue(all(not args.kwargs["first_parent"] for args in render.call_args_list))
        load.assert_called_once_with(None)

    def test_ctrl_c_in_any_nested_setting_exits_entire_root_command(self):
        for enter, child in (("\r", "Log view:"), ("\x1b[B\r", "History mode:"), ("\x1b[B" * 2 + "\r", "Base ref (blank uses develop):")):
            with (
                self.subTest(child=child),
                patch.object(cli, "_has_interactive_terminal", return_value=True),
                patch.object(history, "history_snapshot", return_value=snapshot()),
                patch.object(history, "render_log", return_value="* abc subject"),
                keyed_questions(["\x1b[B" * 6 + "\r", enter, "\x03"]) as messages,
            ):
                result = CliRunner().invoke(cli.app, [])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(messages, ["Select command:", "Log options:", child])
            self.assertIn("Operation cancelled by user.", result.output)
            self.assertFalse(cli._ROOT_COMMAND_ACTIVE.get())


class LogImportAndTerminalTests(unittest.TestCase):
    def test_color_gate_requires_real_supported_stdout_and_respects_opt_outs(self):
        for tty, terminal, colors, no_color, env, expected in (
            (True, True, "standard", False, {"TERM": "xterm"}, True),
            (False, True, "standard", False, {"TERM": "xterm", "FORCE_COLOR": "1"}, False),
            (True, False, "standard", False, {"TERM": "xterm"}, False),
            (True, True, None, False, {"TERM": "xterm"}, False),
            (True, True, "standard", True, {"TERM": "xterm"}, False),
            (True, True, "standard", False, {"TERM": "dumb", "FORCE_COLOR": "1"}, False),
            (True, True, "standard", False, {"TERM": "xterm", "NO_COLOR": "1"}, False),
            (True, True, "standard", False, {"TERM": "xterm", "CLICOLOR": "0", "FORCE_COLOR": "1"}, False),
            (True, True, "standard", False, {"TERM": "xterm", "NO_COLOR": "", "FORCE_COLOR": "1"}, False),
        ):
            with (
                self.subTest(tty=tty, terminal=terminal, colors=colors, no_color=no_color, env=env),
                patch.object(cli.sys.stdout, "isatty", return_value=tty),
                patch.object(cli.sys.stdin, "isatty", return_value=False),
                patch.object(cli, "console") as console,
                patch.dict(os.environ, env, clear=True),
            ):
                console.is_terminal = terminal
                console.color_system = colors
                console.no_color = no_color
                self.assertEqual(cli._log_color_enabled(), expected)

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

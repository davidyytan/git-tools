from __future__ import annotations

import contextlib
import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import typer
from typer.testing import CliRunner
from rich.console import Console

from git_tools.cli import app
from git_tools.generators.base import BaseGenerator
from git_tools.generators.commitgen import CommitGenerator
from git_tools.generators.issueprgen import IssuePullRequestGenerator


COMMIT_INFO = {
    "base_branch": "origin/develop",
    "commit_count": 1,
    "first_hash": "abc1234",
    "first_message": "feat: first",
    "last_hash": "abc1234",
    "last_message": "feat: first",
}
PR_RESPONSE = {"content": "```markdown\n## Title: feat: preserve output\n\nBody [kept]\n```"}


class SavedGenerationSettingsTests(unittest.TestCase):
    def test_models_and_sampling_reuse_settings_and_cli_overrides_in_both_modes(self):
        models = {"saved": {"model_name": "vendor/saved"}, "cli": {"model_name": "vendor/cli"}}
        saved = SimpleNamespace(
            effective_main_model="saved", default_temperature=0.7, default_max_tokens=4321
        )
        providers = {"openrouter": {"models": models, "allow_manual_model": True}}
        for interactive in (False, True):
            for overrides, expected in (
                ({}, ("vendor/saved", 0.7, 4321)),
                ({"model": "cli", "temperature": 0.0, "max_tokens": 123}, ("vendor/cli", 0.0, 123)),
                ({"model": "vendor/cli"}, ("vendor/cli", 0.7, 4321)),
            ):
                with self.subTest(interactive=interactive, overrides=overrides):
                    generator = BaseGenerator(interactive=interactive, **overrides)
                    with contextlib.ExitStack() as stack:
                        stack.enter_context(patch("git_tools.generators.base.models.settings", saved))
                        stack.enter_context(patch("git_tools.generators.base.models.PROVIDERS", providers))
                        stack.enter_context(patch("git_tools.generators.base.models.refresh_live_models", return_value=True))
                        stack.enter_context(patch("git_tools.cli._print_model_catalog_status"))
                        stack.enter_context(patch.object(generator, "get_provider_config"))
                        for name in ("_interactive_model_selection", "_get_temperature_input", "_get_max_tokens_input", "prompt_select", "prompt_text"):
                            stack.enter_context(patch.object(generator, name, side_effect=AssertionError(name)))
                        self.assertEqual(generator.select_model_params("openrouter"), expected)

    def test_effective_summary_respects_overrides_without_discovery_or_credentials(self):
        saved = SimpleNamespace(effective_main_model="saved/model", default_temperature=0.7,
                                default_max_tokens=4321, default_provider="openrouter")
        for interactive in (False, True):
            with self.subTest(interactive=interactive):
                generator = BaseGenerator(interactive=interactive, model="cli/model", temperature=0.0, max_tokens=123)
                with (
                    patch("git_tools.generators.base.models.settings", saved),
                    patch("git_tools.generators.base.models.print_panel") as panel,
                    patch("git_tools.generators.base.models.refresh_live_models", side_effect=AssertionError("discovery")),
                    patch.object(generator, "get_provider_config", side_effect=AssertionError("credentials")),
                ):
                    generator.display_generation_settings(input_budget=987, details="Scope: off")
                if interactive:
                    text = panel.call_args.args[0]
                    for value in ("cli/model", "Temperature: 0.0", "Output token budget: 123", "Input diff budget: 987", "Scope: off"):
                        self.assertIn(value, text)
                    self.assertNotIn("saved/model", text)
                else:
                    panel.assert_not_called()

    def test_input_budgets_use_saved_default_without_routine_prompt(self):
        for interactive in (False, True):
            for override, expected in ((None, 7654), (123, 123)):
                with self.subTest(interactive=interactive, override=override):
                    generator = BaseGenerator(interactive=interactive, token_limit=override)
                    with patch.object(generator, "get_token_limit", side_effect=AssertionError("routine budget prompt")):
                        self.assertEqual(generator.get_diff_processing_params(7654), expected)

    def test_commit_scope_and_footer_use_saved_preferences_with_explicit_false_override(self):
        for interactive in (False, True):
            for cli_value, expected in ((None, True), (False, False), (True, True)):
                with self.subTest(interactive=interactive, cli_value=cli_value):
                    generator = CommitGenerator(interactive=interactive, include_scope=cli_value, include_footer=cli_value)
                    saved = SimpleNamespace(commit_include_scope=True, commit_include_footer=True,
                                            commit_include_body=True, commit_body_style="bullets",
                                            default_token_limit=200000)
                    with (
                        patch("git_tools.generators.commitgen.generator.settings", saved),
                        patch.object(generator, "_build_system_message", return_value="system") as build,
                        patch.object(generator, "prompt_confirm", return_value=True) as confirm,
                        patch.object(generator, "_generate_with_provider", return_value=True),
                    ):
                        generator._handle_external_provider_workflow("diff")
                    build.assert_called_once_with(expected, expected, True, "bullets")
                    if interactive:
                        confirm.assert_called_once_with("Generate commit message using external providers?", default=True)
                    else:
                        confirm.assert_not_called()

    def test_saved_source_reused_and_explicit_invalid_source_keeps_documented_fallback(self):
        for interactive in (False, True):
            for saved_source, cli_source, expected in (("c", None, "c"), ("d", None, "d"), ("b", None, "b"), ("c", "d", "d"), ("d", "C", "c"), ("c", "invalid", "b")):
                with self.subTest(interactive=interactive, saved_source=saved_source, cli_source=cli_source):
                    generator = IssuePullRequestGenerator(input_source=cli_source, interactive=interactive)
                    with (
                        patch("git_tools.generators.issueprgen.content.settings", SimpleNamespace(issue_pr_source=saved_source, default_issue_pr_token_limit=321)),
                        patch.object(generator, "get_commit_messages", return_value="feat: first"),
                        patch.object(generator, "get_branch_diffs", return_value=("diff", [])),
                        patch.object(generator, "display_quota_breakdown"),
                        patch.object(generator, "prompt_select", side_effect=AssertionError("routine source prompt")),
                    ):
                        source, _ = generator._collect_generation_content(COMMIT_INFO, None)
                    self.assertEqual(source, expected)

    def test_saved_azure_auto_uses_detection_without_extra_consent(self):
        for interactive in (False, True):
            for origin, expected in (("https://dev.azure.com/org/project/_git/repo", True), ("https://github.com/org/repo", False), (None, False)):
                with self.subTest(interactive=interactive, origin=origin):
                    generator = IssuePullRequestGenerator(generation_type="pr", interactive=interactive)
                    with (
                        patch("git_tools.generators.issueprgen.azure.settings", SimpleNamespace(azure_pr_limit="auto")),
                        patch.object(generator, "_get_origin_url", return_value=origin),
                        patch.object(generator, "prompt_confirm", side_effect=AssertionError("routine limit prompt")),
                    ):
                        self.assertEqual(generator._should_apply_azure_limit(), expected)

    def test_saved_azure_disable_and_cli_override_avoid_origin_detection(self):
        for cli_value, saved_value, expected in ((None, "false", False), (True, "false", True), (False, "auto", False)):
            with self.subTest(cli_value=cli_value, saved_value=saved_value):
                generator = IssuePullRequestGenerator(generation_type="pr", azure_limit=cli_value, interactive=True)
                with (
                    patch("git_tools.generators.issueprgen.azure.settings", SimpleNamespace(azure_pr_limit=saved_value)),
                    patch.object(generator, "_get_origin_url", side_effect=AssertionError("unnecessary origin lookup")),
                ):
                    self.assertEqual(generator._should_apply_azure_limit(), expected)


class FlowBoundaries:
    def _commit_boundaries(self, stack, generator):
        stack.enter_context(patch.object(generator, "get_staged_diff", return_value="diff"))
        stack.enter_context(patch.object(generator, "_check_sensitive_files", return_value=True))
        enhanced = stack.enter_context(patch.object(generator, "get_staged_diff_enhanced", return_value=("diff", [])))
        stack.enter_context(patch.object(generator, "select_provider", return_value="openrouter"))
        stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=True))
        stack.enter_context(patch.object(generator, "select_model_params", return_value=("model", 0.0, 100)))
        initialize = stack.enter_context(patch.object(generator, "_initialize_service", return_value=True))
        generate = stack.enter_context(patch.object(generator, "generate_commit_message", return_value={"content": "```\nfix: preserve consent\n```"}))
        stack.enter_context(patch.object(generator, "display_reasoning"))
        stack.enter_context(patch.object(generator, "display_token_usage"))
        return enhanced, initialize, generate

    def _issue_boundaries(self, stack, generator, *, credentials=True, response=PR_RESPONSE):
        stack.enter_context(patch.object(generator, "get_default_branch", return_value="origin/develop"))
        stack.enter_context(patch.object(generator, "get_commit_info", return_value=COMMIT_INFO))
        stack.enter_context(patch.object(generator, "show_commit_summary"))
        collected = stack.enter_context(patch.object(generator, "_collect_generation_content", return_value=("b", "input content")))
        stack.enter_context(patch.object(generator, "_should_apply_azure_limit", return_value=False))
        stack.enter_context(patch.object(generator, "select_provider", return_value="openrouter"))
        stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=credentials))
        stack.enter_context(patch.object(generator, "select_model_params", return_value=("model", 0.0, 100)))
        initialize = stack.enter_context(patch.object(generator, "_initialize_service", return_value=True))
        generate = stack.enter_context(patch.object(generator, "generate_content", return_value=response))
        stack.enter_context(patch.object(generator, "display_reasoning"))
        stack.enter_context(patch.object(generator, "display_token_usage"))
        return collected, initialize, generate


class GenerationFlowTests(FlowBoundaries, unittest.TestCase):
    def test_normal_commit_prompt_sequence_keeps_send_and_final_commit_consent(self):
        generator = CommitGenerator(interactive=True)
        questions = []
        answers = iter(("Conventional Commit", "Yes", "No", "No"))

        def select(message, **kwargs):
            questions.append(message)
            return SimpleNamespace(ask=lambda: next(answers))

        with contextlib.ExitStack() as stack:
            enhanced, _, _ = self._commit_boundaries(stack, generator)
            stack.enter_context(patch("git_tools.generators.base.interaction.questionary.select", side_effect=select))
            stack.enter_context(patch("git_tools.generators.base.interaction.questionary.text", side_effect=AssertionError("routine settings prompt")))
            clipboard = stack.enter_context(patch("pyperclip.copy"))
            commit = stack.enter_context(patch("git_tools.generators.commitgen.generator.subprocess.run"))
            stack.enter_context(patch("git_tools.generators.commitgen.generator.settings", SimpleNamespace(default_token_limit=6543, commit_include_scope=False, commit_include_footer=False,
                                                                                                    commit_include_body=True, commit_body_style="bullets")))
            generator.generate_commit()
        self.assertEqual(questions, ["Select commit mode:", "Generate commit message using external providers?", "Commit changes directly?", "Copy to clipboard?"])
        enhanced.assert_called_once_with(6543)
        clipboard.assert_not_called()
        commit.assert_not_called()

    def test_normal_pr_prompt_sequence_and_exact_content_handoff(self):
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
        questions = []
        answers = iter(("Ordinary PR", "Yes", "No"))

        def select(message, **kwargs):
            questions.append(message)
            return SimpleNamespace(ask=lambda: next(answers))

        def text(message, **kwargs):
            questions.append(message)
            return SimpleNamespace(ask=lambda: "  user intent  ")

        with contextlib.ExitStack() as stack:
            collected, _, generate = self._issue_boundaries(stack, generator)
            # Exercise the real source collector; only Git/diff/token boundaries are mocked.
            collected.side_effect = lambda info, fixed: generator.__class__._collect_generation_content(generator, info, fixed)
            stack.enter_context(patch.object(generator, "get_commit_messages", return_value="feat: first"))
            diffs = stack.enter_context(patch.object(generator, "get_branch_diffs", return_value=("diff content", [])))
            stack.enter_context(patch.object(generator, "display_quota_breakdown"))
            stack.enter_context(patch("git_tools.generators.issueprgen.content.settings", SimpleNamespace(issue_pr_source="b", default_issue_pr_token_limit=7654)))
            stack.enter_context(patch("git_tools.generators.base.interaction.questionary.select", side_effect=select))
            stack.enter_context(patch("git_tools.generators.base.interaction.questionary.text", side_effect=text))
            clipboard = stack.enter_context(patch("pyperclip.copy"))
            generator.generate_issue_pullrequest()
        self.assertEqual(questions, ["Select PR mode:", "Additional context (optional; leave blank to skip):", "Generate content using external providers?", "Copy to clipboard?"])
        diffs.assert_called_once_with("origin/develop", 7654)
        self.assertIn("user intent", generate.call_args.args[0])
        self.assertIn("Context is user intent but diffs and commit messages are the actual code changes.", generate.call_args.args[0])
        clipboard.assert_not_called()

    def test_cli_context_including_empty_string_skips_context_prompt(self):
        for context in ("", "explicit context"):
            with self.subTest(context=context):
                generator = IssuePullRequestGenerator(generation_type="issue", interactive=True, context=context, copy_clipboard=False)
                with contextlib.ExitStack() as stack:
                    _, _, generate = self._issue_boundaries(stack, generator)
                    stack.enter_context(patch.object(generator, "prompt_confirm", return_value=True))
                    text = stack.enter_context(patch.object(generator, "prompt_text"))
                    generator.generate_issue_pullrequest()
                text.assert_not_called()
                if context:
                    self.assertIn(context, generate.call_args.args[0])
                else:
                    self.assertEqual(generate.call_args.args[0], "input content")

    def test_validation_errors_propagate_unchanged_before_generation(self):
        for source in ("base", "workflow"):
            with self.subTest(source=source):
                generator = IssuePullRequestGenerator(generation_type="pr", start_pr=source == "workflow")
                with (
                    patch.object(generator, "get_default_branch", side_effect=ValueError("invalid base") if source == "base" else None, return_value="origin/develop"),
                    patch.object(generator, "_resolve_start_pr_context", side_effect=ValueError("invalid explicit start version")),
                    patch.object(generator, "generate_content") as generate,
                ):
                    with self.assertRaisesRegex(ValueError, "invalid base" if source == "base" else "invalid explicit start version"):
                        generator.generate_issue_pullrequest()
                generate.assert_not_called()

    def test_cancel_at_external_send_or_final_commit_never_commits_or_copies(self):
        for answers in (("Conventional Commit", None), ("Conventional Commit", "Yes", None)):
            with self.subTest(answers=answers):
                generator = CommitGenerator(interactive=True)
                with contextlib.ExitStack() as stack:
                    _, initialize, generate = self._commit_boundaries(stack, generator)
                    select = stack.enter_context(patch("git_tools.generators.base.interaction.questionary.select"))
                    select.return_value.ask.side_effect = answers
                    copy = stack.enter_context(patch("pyperclip.copy"))
                    commit = stack.enter_context(patch("git_tools.generators.commitgen.generator.subprocess.run"))
                    with self.assertRaises(KeyboardInterrupt):
                        generator.generate_commit()
                copy.assert_not_called()
                commit.assert_not_called()
                if len(answers) == 2:
                    initialize.assert_not_called()
                    generate.assert_not_called()

    def test_cancel_optional_context_never_initializes_provider_or_copies(self):
        generator = IssuePullRequestGenerator(generation_type="issue", interactive=True)
        with contextlib.ExitStack() as stack:
            _, initialize, generate = self._issue_boundaries(stack, generator)
            text = stack.enter_context(patch("git_tools.generators.base.interaction.questionary.text"))
            text.return_value.ask.return_value = None
            copy = stack.enter_context(patch("pyperclip.copy"))
            with self.assertRaises(KeyboardInterrupt):
                generator.generate_issue_pullrequest()
        initialize.assert_not_called()
        generate.assert_not_called()
        copy.assert_not_called()

    def test_declining_external_send_keeps_provider_uninitialized(self):
        for kind in ("commit", "issue"):
            with self.subTest(kind=kind), contextlib.ExitStack() as stack:
                if kind == "commit":
                    generator = CommitGenerator(interactive=True, workflow_kind="normal", copy_clipboard=False)
                    _, initialize, generate = self._commit_boundaries(stack, generator)
                    run = generator.generate_commit
                else:
                    generator = IssuePullRequestGenerator(generation_type="issue", interactive=True, context="", copy_clipboard=False)
                    _, initialize, generate = self._issue_boundaries(stack, generator)
                    run = generator.generate_issue_pullrequest
                stack.enter_context(patch.object(generator, "prompt_confirm", return_value=False))
                credentials = stack.enter_context(patch.object(generator, "ensure_api_key_configured"))
                clipboard = stack.enter_context(patch("pyperclip.copy"))
                run()
                credentials.assert_not_called()
                initialize.assert_not_called()
                generate.assert_not_called()
                clipboard.assert_not_called()

    def test_cancel_key_setup_does_not_fall_back_to_copy(self):
        generator = CommitGenerator(interactive=True, copy_clipboard=True)
        with (
            patch("git_tools.settings.settings.check_api_key_configured", return_value=(False, "")),
            patch.object(generator, "select_provider", return_value="openrouter"),
            patch.object(generator, "prompt_confirm", side_effect=KeyboardInterrupt),
            patch("git_tools.settings.settings.setup_api_key") as setup,
            patch.object(generator, "_initialize_service") as initialize,
            patch.object(generator, "handoff_local_prompt") as local,
            patch("pyperclip.copy") as copy,
        ):
            with self.assertRaises(KeyboardInterrupt):
                generator._generate_with_provider("diff", "system")
        setup.assert_not_called()
        initialize.assert_not_called()
        local.assert_not_called()
        copy.assert_not_called()

    def test_prompt_helper_cancellation_never_accepts_default(self):
        generator = BaseGenerator(interactive=True)
        for method, args, questionary_name in (("prompt_text", ("context", "default"), "text"), ("prompt_select", ("choice", ["first", "second"]), "select"), ("prompt_confirm", ("consent",), "select")):
            with self.subTest(method=method), patch(f"git_tools.generators.base.interaction.questionary.{questionary_name}") as question:
                question.return_value.ask.return_value = None
                with self.assertRaises(KeyboardInterrupt):
                    getattr(generator, method)(*args)


class ClipboardPolicyTests(FlowBoundaries, unittest.TestCase):
    def test_commit_copy_policy_for_success_local_and_missing_credentials(self):
        for path in ("success", "local", "missing-key"):
            for interactive in (False, True):
                for copy_flag in (None, False, True):
                    with self.subTest(path=path, interactive=interactive, copy_flag=copy_flag):
                        generator = CommitGenerator(interactive=interactive, copy_clipboard=copy_flag, auto_commit=False)
                        with contextlib.ExitStack() as stack:
                            ask = stack.enter_context(patch.object(generator, "ask_to_copy_to_clipboard"))
                            auto = stack.enter_context(patch.object(generator, "copy_to_clipboard_auto"))
                            display = stack.enter_context(patch("git_tools.generators.base.interaction.console"))
                            stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=False))
                            stack.enter_context(patch.object(generator, "select_provider", return_value="openrouter"))
                            if path == "success":
                                generator._handle_commit_action({"content": "```\nfix: preserve output\n```"})
                            elif path == "local":
                                generator._handle_local_mode("diff [kept]", "system")
                            else:
                                generator._generate_with_provider("diff [kept]", "system")
                        expected_ask = copy_flag is None and interactive
                        expected_auto = copy_flag is True or (copy_flag is None and not interactive and path != "missing-key")
                        self.assertEqual(ask.call_count, int(expected_ask))
                        self.assertEqual(auto.call_count, int(expected_auto))
                        if path != "success":
                            panels = [call.args[0] for call in display.print.call_args_list if call.args and hasattr(call.args[0], "title")]
                            self.assertEqual(len(panels), 1)
                            self.assertIn("diff", panels[0].renderable)
                            self.assertIn("system", panels[0].renderable)

    def test_issue_pr_copy_policy_for_success_local_and_missing_credentials(self):
        for generation_type in ("pr", "issue", "both"):
            for path in ("success", "local", "missing-key"):
                for interactive in (False, True):
                    if path == "local" and not interactive:
                        continue  # Declining external send is an interactive-only branch.
                    for copy_flag in (None, False, True):
                        with self.subTest(generation_type=generation_type, path=path, interactive=interactive, copy_flag=copy_flag):
                            generator = IssuePullRequestGenerator(generation_type=generation_type, interactive=interactive, context="", copy_clipboard=copy_flag)
                            with contextlib.ExitStack() as stack:
                                self._issue_boundaries(stack, generator, credentials=path != "missing-key")
                                stack.enter_context(patch.object(generator, "resolve_pr_mode"))
                                stack.enter_context(patch.object(generator, "prompt_confirm", return_value=path != "local"))
                                ask = stack.enter_context(patch.object(generator, "ask_to_copy_to_clipboard"))
                                auto = stack.enter_context(patch.object(generator, "copy_to_clipboard_auto"))
                                display = stack.enter_context(patch("git_tools.generators.base.interaction.console"))
                                generator.generate_issue_pullrequest()
                            expected_ask = copy_flag is None and interactive
                            expected_auto = copy_flag is True or (copy_flag is None and not interactive and path != "missing-key")
                            self.assertEqual(ask.call_count, int(expected_ask))
                            self.assertEqual(auto.call_count, int(expected_auto))
                            if path != "success":
                                panels = [call.args[0] for call in display.print.call_args_list if call.args and hasattr(call.args[0], "title")]
                                self.assertEqual(len(panels), 1)
                                self.assertIn("input content", panels[0].renderable)

    def test_pr_preview_matches_copied_content_but_issue_keeps_raw_copy(self):
        for generation_type in ("pr", "issue", "both"):
            with self.subTest(generation_type=generation_type):
                generator = IssuePullRequestGenerator(generation_type=generation_type, copy_clipboard=True)
                with contextlib.ExitStack() as stack:
                    self._issue_boundaries(stack, generator)
                    display = stack.enter_context(patch("git_tools.generators.issueprgen.generator.console"))
                    auto = stack.enter_context(patch.object(generator, "copy_to_clipboard_auto"))
                    generator.generate_issue_pullrequest()
                panels = [call.args[0] for call in display.print.call_args_list if call.args and hasattr(call.args[0], "title")]
                parsed = "## Title: feat: preserve output\n\nBody [kept]"
                self.assertEqual(panels[0].renderable.replace("\\[", "["), parsed)
                auto.assert_called_once_with(parsed if generation_type == "pr" else PR_RESPONSE["content"], leading_space=False)

    def test_generated_previews_wrap_long_lines_without_losing_text(self):
        body = "FIRST " + "long-token " * 30 + "LAST_MARKER"
        for kind in ("commit", "pr"):
            with self.subTest(kind=kind), contextlib.ExitStack() as stack:
                output = io.StringIO()
                narrow_console = Console(file=output, width=40, soft_wrap=True, force_terminal=False)
                if kind == "commit":
                    generator = CommitGenerator(copy_clipboard=False)
                    stack.enter_context(patch("git_tools.generators.commitgen.generator.console", narrow_console))
                    stack.enter_context(patch.object(generator, "display_reasoning"))
                    generator._display_response({"content": f"fix: preserve preview\n\n{body}"})
                else:
                    generator = IssuePullRequestGenerator(generation_type="pr", copy_clipboard=False)
                    self._issue_boundaries(stack, generator, response={"content": f"```\n## Title: fix: preserve preview\n\n{body}\n```"})
                    stack.enter_context(patch("git_tools.generators.issueprgen.generator.console", narrow_console))
                    generator.generate_issue_pullrequest()
                rendered = output.getvalue()
                self.assertIn("FIRST", rendered)
                self.assertIn("LAST_MARKER", rendered)
                self.assertEqual(rendered.count("long-token"), 30)

    def test_local_prompt_wraps_long_lines_without_losing_text(self):
        content = "FIRST " + "long-token " * 30 + "LAST_MARKER"
        output = io.StringIO()
        narrow_console = Console(file=output, width=40, soft_wrap=True, force_terminal=False)
        generator = CommitGenerator(copy_clipboard=False)
        with patch("git_tools.generators.base.interaction.console", narrow_console):
            generator.handoff_local_prompt(content)
        rendered = output.getvalue()
        self.assertIn("FIRST", rendered)
        self.assertIn("LAST_MARKER", rendered)
        self.assertEqual(rendered.count("long-token"), 30)

    def test_local_prompt_survives_declined_unavailable_or_failing_clipboard(self):
        for kind in ("declined", "unavailable", "failure"):
            with self.subTest(kind=kind):
                generator = CommitGenerator(interactive=True)
                with contextlib.ExitStack() as stack:
                    display = stack.enter_context(patch("git_tools.generators.base.interaction.console"))
                    stack.enter_context(patch.object(generator, "prompt_confirm", return_value=kind != "declined"))
                    if kind == "unavailable":
                        stack.enter_context(patch.dict(sys.modules, {"pyperclip": None}))
                        copy = Mock()
                    else:
                        copy = stack.enter_context(patch("pyperclip.copy", side_effect=RuntimeError("no display") if kind == "failure" else None))
                    generator._handle_local_mode("diff [kept]", "system [kept]")
                panels = [call.args[0] for call in display.print.call_args_list if call.args and hasattr(call.args[0], "title")]
                self.assertEqual(len(panels), 1)
                self.assertIn("diff \\[kept]", panels[0].renderable)
                self.assertIn("system \\[kept]", panels[0].renderable)
                self.assertEqual(copy.call_count, int(kind == "failure"))


class CliGenerationContractTests(unittest.TestCase):
    def test_cli_overrides_reach_generators_including_temperature_zero_and_false_preferences(self):
        for command in ("commit", "issue", "pr"):
            with self.subTest(command=command):
                path = "git_tools.generators.commitgen.CommitGenerator" if command == "commit" else "git_tools.generators.issueprgen.IssuePullRequestGenerator"
                args = [command, "--interactive", "--model", "cli-model", "--temp", "0", "--max-tokens", "111", "--token-limit", "222", "--no-copy"]
                if command == "commit":
                    args += ["--no-scope", "--no-footer", "--no-commit"]
                else:
                    args += ["--source", "d", "--context", ""]
                with patch(path) as constructor:
                    result = CliRunner().invoke(app, args)
                self.assertEqual(result.exit_code, 0, result.output)
                values = constructor.call_args.kwargs
                for name, value in (("model", "cli-model"), ("temperature", 0.0), ("max_tokens", 111), ("token_limit", 222), ("copy_clipboard", False), ("interactive", True)):
                    self.assertEqual(values[name], value)
                if command == "commit":
                    self.assertIs(values["include_scope"], False)
                    self.assertIs(values["include_footer"], False)
                    self.assertIs(values["auto_commit"], False)
                else:
                    self.assertEqual(values["input_source"], "d")
                    self.assertEqual(values["context"], "")

    def test_cli_absent_overrides_remain_none_to_reuse_saved_settings(self):
        for command in ("commit", "issue", "pr"):
            with self.subTest(command=command):
                path = "git_tools.generators.commitgen.CommitGenerator" if command == "commit" else "git_tools.generators.issueprgen.IssuePullRequestGenerator"
                with patch(path) as constructor:
                    result = CliRunner().invoke(app, [command])
                self.assertEqual(result.exit_code, 0, result.output)
                values = constructor.call_args.kwargs
                for name in ("model", "temperature", "max_tokens", "token_limit", "copy_clipboard"):
                    self.assertIsNone(values[name])
                if command == "commit":
                    self.assertIsNone(values["include_scope"])
                    self.assertIsNone(values["include_footer"])
                else:
                    self.assertIsNone(values["input_source"])

    def test_cli_expected_validation_and_intentional_exit_are_not_unexpected_errors(self):
        for command in ("commit", "issue", "pr"):
            for exception, code, message in ((ValueError("precise validation failure"), 1, "precise validation failure"), (typer.Exit(7), 7, None), (KeyboardInterrupt(), 0, "Operation cancelled by user.")):
                with self.subTest(command=command, exception=type(exception).__name__):
                    path = "git_tools.generators.commitgen.CommitGenerator" if command == "commit" else "git_tools.generators.issueprgen.IssuePullRequestGenerator"
                    method = "generate_commit" if command == "commit" else "generate_issue_pullrequest"
                    with patch(path) as constructor:
                        getattr(constructor.return_value, method).side_effect = exception
                        result = CliRunner().invoke(app, [command])
                    self.assertEqual(result.exit_code, code, result.output)
                    if message is not None:
                        self.assertIn(message, result.output)
                    self.assertNotIn("unexpected error", result.output.lower())


if __name__ == "__main__":
    unittest.main()

"""Captured presentation checks; providers, persistence, and clipboard stay mocked."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

# Keep the shared presentation layer optional for minimal-engine checkouts.
try:
    import questionary  # noqa: F401
    import rich  # noqa: F401
    import tiktoken  # noqa: F401
    import typer  # noqa: F401
except ImportError as exc:
    raise unittest.SkipTest(f"CLI presentation dependencies unavailable: {exc}") from exc

from rich.console import Console
from rich.panel import Panel

from git_tools import cli
from git_tools.generators.base import display, interaction, models, terminal
from git_tools.generators.base.generator import BaseGenerator
from git_tools.settings import settings as settings_module


WIDTHS = (38, 110)
USAGE = {"response_metadata": {"token_usage": {
    "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
}}}


@contextmanager
def captured_console(width):
    output = StringIO()
    console = Console(file=output, width=width, soft_wrap=True, color_system=None)
    with ExitStack() as stack:
        for module in (cli, display, interaction, models, terminal):
            stack.enter_context(patch.object(module, "console", console))
        yield console, output


def fake_questions(console, answers):
    """Render completed Questionary labels without starting a real terminal."""
    answers = iter(answers)

    def question(message, **_kwargs):
        def ask():
            answer = next(answers)
            console.print(f"❯ {message} {answer if answer is not None else ''}")
            return answer
        return SimpleNamespace(ask=ask, unsafe_ask=ask)

    return question


class PanelSpacingTests(unittest.TestCase):
    def assert_single_panel_gaps(self, text, expected_panels):
        lines = text.splitlines()
        bottoms = [index for index, line in enumerate(lines) if line.startswith("╰")]
        self.assertEqual(len(bottoms), expected_panels, text)
        for index in bottoms:
            self.assertEqual(lines[index + 1], "", text)
            if index + 2 < len(lines):
                self.assertNotEqual(lines[index + 2], "", text)
        self.assertNotIn("\n\n\n", text)

    def test_settings_quota_reasoning_output_usage_and_prompt_have_single_gaps(self):
        saved = SimpleNamespace(default_provider="openrouter", effective_main_model="saved/model",
                                default_temperature=0.6, default_max_tokens=32000)
        generator = BaseGenerator(interactive=True)
        for width in WIDTHS:
            with self.subTest(width=width), captured_console(width) as (console, output):
                question = fake_questions(console, ["Yes", "No"])
                with (
                    patch.object(models, "settings", saved),
                    patch.object(interaction.questionary, "select", side_effect=question),
                ):
                    generator.display_generation_settings(input_budget=200000, details="Scope: off")
                    generator.prompt_confirm("Generate content using external providers?")
                    console.print()  # The front end owns prompt -> next section.
                    generator.display_quota_breakdown([
                        "- path/to/a-long-file.py: Original diff size: 250 tokens, Quota allocated: 200 tokens"
                    ], 200000)
                    generator.display_reasoning({"additional_kwargs": {"reasoning_content": "Reasoning [literal]"}})
                    terminal.print_panel("Generated output [literal]", title="Output")
                    generator.display_token_usage(USAGE)
                    generator.prompt_confirm("Copy to clipboard?")
                text = output.getvalue()
                self.assert_single_panel_gaps(text, 5)
                self.assertNotIn("?:", text)
                self.assertIn("Reasoning [literal]", text)

    def test_each_panel_wraps_within_console_and_owns_its_separator(self):
        generator = BaseGenerator()
        for width in WIDTHS:
            for name, render in (
                ("shared", lambda: terminal.print_panel("word " * 50, title="Output")),
                ("quota", lambda: generator.display_quota_breakdown(["word " * 50], 200000)),
                ("usage", lambda: generator.display_token_usage(USAGE)),
                ("reasoning", lambda: generator.display_reasoning({"additional_kwargs": {"reasoning_content": "word " * 50}})),
                ("local", lambda: generator.handoff_local_prompt("word " * 50)),
            ):
                with self.subTest(width=width, renderer=name), captured_console(width) as (console, output):
                    generator._cli_copy_clipboard = False
                    render()
                    console.print("NEXT")
                    text = output.getvalue()
                    self.assert_single_panel_gaps(text, 1)
                    self.assertTrue(all(len(line) <= width for line in text.splitlines()), text)

    def test_absent_or_empty_diagnostic_panels_emit_nothing(self):
        generator = BaseGenerator()
        with captured_console(80) as (_console, output):
            generator.display_quota_breakdown([], 200000)
            generator.display_quota_breakdown(["   "], 200000)
            for response in ({}, {"response_metadata": None},
                             {"response_metadata": {"token_usage": {}}},
                             {"response_metadata": {"token_usage": {"unknown": 123}}}):
                generator.display_token_usage(response)
            generator.display_reasoning({})
            generator.display_reasoning({"additional_kwargs": {"reasoning_content": "   "}})
        self.assertEqual(output.getvalue(), "")

    def test_panels_disable_console_soft_wrap(self):
        generator = BaseGenerator()
        with patch.object(terminal.console, "print") as printed:
            terminal.print_panel("text")
            generator.display_quota_breakdown(["quota"], 200000)
            generator.display_token_usage(USAGE)
            generator.display_reasoning({"additional_kwargs": {"reasoning_content": "reasoning"}})
            generator._cli_copy_clipboard = False
            generator.handoff_local_prompt("prompt")
        panel_calls = [call for call in printed.call_args_list if call.args and isinstance(call.args[0], Panel)]
        self.assertEqual(len(panel_calls), 5)
        for call in panel_calls:
            self.assertIs(call.kwargs.get("soft_wrap"), False)

    def test_automatic_clipboard_result_does_not_double_panel_separator(self):
        for width in WIDTHS:
            for explicit in (None, True, False):
                with self.subTest(width=width, copy=explicit), captured_console(width) as (_console, output):
                    generator = BaseGenerator(interactive=False)
                    generator._cli_copy_clipboard = explicit
                    with patch("pyperclip.copy") as copied:
                        generator.handoff_local_prompt("local prompt [literal]")
                    self.assert_single_panel_gaps(output.getvalue(), 1)
                    if explicit is False:
                        copied.assert_not_called()
                    else:
                        copied.assert_called_once_with("local prompt [literal]")
                        self.assertIn("\n\n✓ Copied to clipboard!\n", output.getvalue())

    def test_generated_panel_automatic_handoff_and_plain_auto_keep_one_gap(self):
        generator = BaseGenerator(interactive=False)
        for after_panel in (False, True):
            with self.subTest(after_panel=after_panel), captured_console(80) as (console, output):
                with patch("pyperclip.copy") as copied:
                    if after_panel:
                        terminal.print_panel("generated result", title="Output")
                        generator.handoff_to_clipboard("generated result", leading_space=False)
                    else:
                        console.print("plain result")
                        generator.copy_to_clipboard_auto("generated result")
                copied.assert_called_once_with("generated result")
                self.assertIn("\n\n✓ Copied to clipboard!\n", output.getvalue())
                self.assertNotIn("\n\n\n", output.getvalue())

    def test_failed_clipboard_results_keep_one_gap_after_panels_or_answers(self):
        for interactive in (False, True):
            with self.subTest(interactive=interactive), captured_console(80) as (console, output):
                generator = BaseGenerator(interactive=interactive)
                generator.logger = Mock()
                with (
                    patch.object(interaction.questionary, "select", side_effect=fake_questions(console, ["Yes"])),
                    patch("pyperclip.copy", side_effect=RuntimeError("clipboard unavailable")),
                ):
                    generator.handoff_local_prompt("local prompt")
                text = output.getvalue()
                self.assert_single_panel_gaps(text, 1)
                self.assertIn("\n\n✗ Failed to copy content.\n", text)
                self.assertNotIn("\n\n\n", text)

    def test_interactive_local_handoff_keeps_prompt_and_result_separate(self):
        for answer in ("Yes", "No"):
            with self.subTest(answer=answer), captured_console(80) as (console, output):
                generator = BaseGenerator(interactive=True)
                with (
                    patch.object(interaction.questionary, "select", side_effect=fake_questions(console, [answer])),
                    patch("pyperclip.copy") as copied,
                ):
                    generator.handoff_local_prompt("local prompt")
                text = output.getvalue()
                self.assert_single_panel_gaps(text, 1)
                self.assertIn(f"Copy to clipboard? {answer}\n\n✓ ", text)
                self.assertEqual(copied.call_count, int(answer == "Yes"))


class PromptPresentationTests(unittest.TestCase):
    def test_text_and_selection_labels_keep_one_terminal_mark_and_trim_spaces(self):
        generator = BaseGenerator(interactive=True)
        for message, expected in (
            ("Select mode", "Select mode:"), ("Select mode:  ", "Select mode:"),
            ("Select mode::", "Select mode:"), ("Generate now?", "Generate now?"),
            ("Generate now?:  ", "Generate now?"), ("Generate now? :", "Generate now?"),
            ("Continue!!:", "Continue!"),
        ):
            for kind in ("text", "select"):
                with self.subTest(message=message, kind=kind):
                    with patch.object(interaction.questionary, kind) as question:
                        question.return_value.ask.return_value = "answer"
                        if kind == "text":
                            self.assertEqual(generator.prompt_text(message, "default"), "answer")
                            self.assertEqual(question.call_args.kwargs["default"], "default")
                        else:
                            self.assertEqual(generator.prompt_select(message, ["answer", "other"]), "answer")
                    self.assertEqual(question.call_args.args[0], expected)

    def test_related_prompts_stay_compact_and_keep_confirmation_default(self):
        generator = BaseGenerator(interactive=True)
        with captured_console(80) as (console, output):
            question = fake_questions(console, ["mode", "No", "details"])
            with (
                patch.object(interaction.questionary, "select", side_effect=question) as select,
                patch.object(interaction.questionary, "text", side_effect=question),
            ):
                generator.prompt_select("Select mode:", ["mode", "other"])
                self.assertFalse(generator.prompt_confirm("Continue?", default=False))
                generator.prompt_text("Details: ")
        self.assertEqual(output.getvalue(), "❯ Select mode: mode\n❯ Continue? No\n❯ Details: details\n")
        self.assertEqual(select.call_args.kwargs["choices"], ["No", "Yes"])

    def test_cancelled_text_selection_and_confirmation_still_abort(self):
        generator = BaseGenerator(interactive=True)
        with patch.object(interaction.questionary, "text") as text, patch.object(interaction.questionary, "select") as select:
            text.return_value.ask.return_value = None
            select.return_value.ask.return_value = None
            for ask in (lambda: generator.prompt_text("Details"),
                        lambda: generator.prompt_select("Mode", ["mode"]),
                        lambda: generator.prompt_confirm("Continue?")):
                with self.assertRaises(KeyboardInterrupt):
                    ask()


class ModelStatusSpacingTests(unittest.TestCase):
    def test_catalog_separator_is_conditional_on_rendered_status(self):
        saved = SimpleNamespace(effective_main_model="saved/model", default_temperature=0.6,
                                default_max_tokens=32000)
        providers = {"openrouter": {"models": {"saved": {"model_name": "saved/model"}}}}
        for interactive in (False, True):
            for live in (False, True):
                with self.subTest(interactive=interactive, live=live), captured_console(80) as (console, output):
                    generator = BaseGenerator(interactive=interactive)
                    with (
                        patch.object(models, "settings", saved),
                        patch.object(models, "PROVIDERS", providers),
                        patch.object(models, "refresh_live_models", return_value=live),
                        patch.object(generator, "get_provider_config"),
                        patch.object(cli, "_print_model_catalog_status", side_effect=lambda *_a: console.print("catalog status")),
                    ):
                        result = generator.select_model_params("openrouter")
                    self.assertEqual(result, ("saved/model", 0.6, 32000))
                    self.assertEqual(output.getvalue(), "catalog status\n\n" if interactive or not live else "")

    def test_missing_credentials_warning_setup_answer_and_fallback_are_separated(self):
        generator = BaseGenerator(interactive=True)
        with captured_console(80) as (console, output):
            with (
                patch.object(settings_module, "check_api_key_configured", return_value=(False, None)),
                patch.object(settings_module, "setup_api_key") as setup,
                patch.object(interaction.questionary, "select", side_effect=fake_questions(console, ["No"])),
            ):
                console.print("❯ Generate now? Yes")
                console.print()  # Front end owns consent -> diagnostics.
                self.assertFalse(generator.ensure_api_key_configured("openrouter"))
                terminal.info("Falling back to local mode...")
        text = output.getvalue()
        self.assertIn("Yes\n\n⚠ No API key configured.\n\n❯ Set up", text)
        self.assertIn("now? No\n\n• Falling back", text)
        self.assertNotIn("\n\n\n", text)
        setup.assert_not_called()


    def test_successful_key_setup_separates_catalog_without_new_actions(self):
        generator = BaseGenerator(interactive=True)
        for width in WIDTHS:
            with self.subTest(width=width), captured_console(width) as (console, output):
                def setup(_provider):
                    console.print("Enter your OpenRouter API key: ********")
                    return True
                with (
                    patch.object(settings_module, "check_api_key_configured", return_value=(False, None)),
                    patch.object(settings_module, "setup_api_key", side_effect=setup) as saved,
                    patch.object(interaction.questionary, "select", side_effect=fake_questions(console, ["Yes"])),
                ):
                    self.assertTrue(generator.ensure_api_key_configured("openrouter"))
                    console.print("model list: live from the provider")
                text = output.getvalue()
                self.assertNotIn("\n\n\n", text)
                self.assertRegex(text, r"saved to [\s\S]*\n\nmodel list: live")
                saved.assert_called_once_with("openrouter")


class SettingsSpacingTests(unittest.TestCase):
    def test_model_catalog_block_separates_previous_and_next_prompts(self):
        for width in WIDTHS:
            for live in (False, True):
                with self.subTest(width=width, live=live), captured_console(width) as (console, output):
                    def choose(*_args, **_kwargs):
                        console.print("❯ Select model: saved/model")
                        return "saved/model"
                    console.print("❯ Enter API key: ********")
                    with (
                        patch.object(cli, "refresh_live_models", return_value=live) as refresh,
                        patch.object(cli, "get_live_model_refresh_error", return_value=None),
                        patch.object(cli, "_ask_model_choice", side_effect=choose),
                    ):
                        result = cli._choose_provider_model("openrouter", "saved/model")
                    self.assertEqual(result, "saved/model")
                    refresh.assert_called_once_with("openrouter", force=True)
                    text = output.getvalue()
                    self.assertIn("********\n\n", text)
                    self.assertIn("\n\n❯ Select model:", text)
                    self.assertNotIn("\n\n\n", text)
                    self.assertEqual(text.count("model list:") if live else text.count("⚠"), 1)

    def test_warning_fallback_upstreams_and_model_prompts_have_single_gaps(self):
        for width in WIDTHS:
            with self.subTest(width=width), captured_console(width) as (console, output):
                console.print("❯ Select model: saved/model")
                with (
                    patch.object(cli, "_list_openrouter_endpoints", return_value=[]),
                    patch.object(cli.questionary, "select", side_effect=fake_questions(console, ["any"])),
                    patch.object(cli, "_ask_with_back", side_effect=lambda q: q.unsafe_ask()),
                ):
                    self.assertEqual(cli._prompt_openrouter_upstream("saved/model", None), "")
                text = output.getvalue()
                self.assertIn("saved/model\n\n⚠ ", text)
                self.assertIn("\n\n❯ OpenRouter upstream", text)
                self.assertNotIn("\n\n\n", text)

    def test_preference_save_and_return_to_settings_have_single_gaps(self):
        state = {"commit_include_scope": False}
        for width in WIDTHS:
            with self.subTest(width=width), captured_console(width) as (console, output):
                question = fake_questions(console, ["commit-scope", "true", "done"])
                with (
                    patch.object(cli, "_load_settings_state", return_value=state.copy()),
                    patch.object(cli, "_build_settings_choices", return_value=[]),
                    patch.object(cli.questionary, "select", side_effect=question),
                    patch.object(cli, "_ask_with_back", side_effect=lambda q: q.unsafe_ask()),
                    patch.object(settings_module, "save_setting") as saved,
                ):
                    cli._run_settings_menu()
                saved.assert_called_once_with("GIT_TOOLS_COMMIT_INCLUDE_SCOPE", "true")
                text = output.getvalue()
                self.assertIn("commit-scope\n❯ Commit scope by default: true\n\n✓ ", text)
                self.assertIn("\n\n❯ Select setting to edit: done\n", text)
                self.assertNotIn("\n\n\n", text)

    def test_main_settings_detour_and_command_dispatch_have_single_gaps(self):
        for width in WIDTHS:
            with self.subTest(width=width), captured_console(width) as (console, output):
                def settings_menu(**_kwargs):
                    console.print("❯ Select setting to edit: ← Back")
                def invoke(*_args, **_kwargs):
                    console.print("❯ Select commit mode: conventional")
                ctx = SimpleNamespace(invoked_subcommand=None, invoke=Mock(side_effect=invoke))
                with (
                    patch.object(cli, "_has_interactive_terminal", return_value=True),
                    patch.object(cli, "_setup_logging"),
                    patch.object(cli, "reload_settings") as reload,
                    patch.object(cli, "_run_settings_menu", side_effect=settings_menu),
                    patch.object(cli.questionary, "select", side_effect=fake_questions(console, ["settings", "commit"])),
                ):
                    cli.main(ctx)
                reload.assert_called_once_with()
                ctx.invoke.assert_called_once_with(cli.commit, interactive=True)
                text = output.getvalue()
                header = f"git-tools {cli.__version__}"
                self.assertTrue(text.startswith(f"{header}\n❯ Select command: settings\n"), text)
                self.assertEqual(text.splitlines().count(header), 1, text)
                self.assertIn("settings\n\n❯ Select setting to edit:", text)
                self.assertIn("← Back\n\n❯ Select command: commit\n\n❯ Select commit mode:", text)
                self.assertNotIn("\n\n\n", text)

    def test_cancelled_editor_returns_to_menu_with_one_separator(self):
        with captured_console(80) as (console, output):
            with (
                patch.object(cli, "_load_settings_state", return_value={}),
                patch.object(cli, "_build_settings_choices", return_value=[]),
                patch.object(cli, "_SETTINGS_EDITORS", {"cancelled": lambda _state: None}),
                patch.object(cli.questionary, "select", side_effect=fake_questions(console, ["cancelled", "done"])),
                patch.object(cli, "_ask_with_back", side_effect=lambda q: q.unsafe_ask()),
            ):
                cli._run_settings_menu()
        self.assertEqual(output.getvalue(), "❯ Select setting to edit: cancelled\n\n❯ Select setting to edit: done\n")


if __name__ == "__main__":
    unittest.main()

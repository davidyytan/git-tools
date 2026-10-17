"""Offline coverage for settings-driven Conventional Commit prompt structure."""

from contextlib import ExitStack
from itertools import product
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from git_tools.generators.commitgen import CommitGenerator


FORMATS = tuple(product((False, True), (False, True), (False, True), ("bullets", "prose")))


class CommitFormatPromptTests(unittest.TestCase):
    def test_all_formats_reach_local_and_provider_prompts(self):
        for scope, footer, body, style in FORMATS:
            with self.subTest(scope=scope, footer=footer, body=body, style=style):
                generator = CommitGenerator(interactive=False)
                system = generator._build_system_message(scope, footer, body, style)
                template = system.split("```\n", 1)[1].split("\n```", 1)[0]
                expected = "<type>" + ("[optional scope]" if scope else "") + "[!]: <description>"
                if body:
                    expected += "\n\n[optional body]"
                if footer:
                    expected += "\n\n[optional footer(s)]"
                self.assertEqual(template, expected)
                self.assertIn("<description> is REQUIRED", system)
                self.assertIn("short summary in the subject/header, even when the body is disabled", system)
                self.assertIn("Do not use the literal text BREAKING CHANGE anywhere except in the footer.", system)
                self.assertIn("[optional scope] may be provided" if scope else "Do not include the [optional scope].", system)
                if footer:
                    for instruction in ("Include [optional footer(s)] for breaking changes.",
                                        "Never invent breaking changes, issue numbers, or other facts.",
                                        "supplied by the input", "omit them otherwise"):
                        self.assertIn(instruction, system)
                else:
                    for instruction in ("Do not include the [optional footer(s)].",
                                        "retain the ! marker before the header colon",
                                        "do not put BREAKING CHANGE in the body"):
                        self.assertIn(instruction, system)
                if body:
                    self.assertIn("[optional body] MAY provide additional context below the required header", system)
                    if style == "bullets":
                        self.assertIn("Use concise dash (-) bullets for body details.", system)
                        self.assertNotIn("Use concise prose paragraphs", system)
                    else:
                        self.assertIn("Use concise prose paragraphs for body details, not list markers.", system)
                        self.assertIn("Separate paragraphs with blank lines.", system)
                        self.assertNotIn("dash (-)", system)
                else:
                    self.assertIn("Do not include a body. Output only the required subject/header", system)
                    for instruction in ("[optional body]", "dash (-)", "Use concise prose paragraphs"):
                        self.assertNotIn(instruction, system)
                    self.assertEqual("and any permitted, supported footer(s)." in system, footer)

                diff = "diff --git a/example.py b/example.py\n+preserve_format()"
                with patch.object(generator, "handoff_local_prompt") as local:
                    generator._handle_local_mode(diff, system)
                local_prompt = local.call_args.args[0]
                self.assertTrue(local_prompt.startswith(system + "\n\n"))
                self.assertIn(diff, local_prompt)
                local.assert_called_once_with(local_prompt, allow_auto=True)

                response = {"content": "fix: preserve format"}
                with patch.object(generator, "invoke_llm", return_value=response) as invoke:
                    self.assertIs(generator.generate_commit_message(diff, system), response)
                messages = invoke.call_args.args[0]
                self.assertEqual(messages[0], {"role": "system", "content": system})
                self.assertEqual(messages[1]["role"], "user")
                self.assertIn(diff, messages[1]["content"])
                self.assertIn("generate a conventional commit message", messages[1]["content"])

    def test_effective_format_defaults_and_overrides_in_both_modes(self):
        for interactive, values, override in product((False, True), FORMATS, (False, True)):
            scope, footer, body, style = values
            with self.subTest(interactive=interactive, values=values, override=override):
                saved = SimpleNamespace(
                    commit_include_scope=scope, commit_include_footer=footer,
                    commit_include_body=body, commit_body_style=style, default_token_limit=1234,
                )
                effective = (not scope, not footer, not body, "prose" if style == "bullets" else "bullets") if override else values
                kwargs = dict(zip(("include_scope", "include_footer", "include_body", "body_style"), effective)) if override else {}
                generator = CommitGenerator(interactive=interactive, **kwargs)
                expected = generator._build_system_message(*effective)
                with (
                    patch("git_tools.generators.commitgen.generator.settings", saved),
                    patch.object(generator, "display_generation_settings") as display,
                    patch.object(generator, "prompt_confirm", return_value=True) as confirm,
                    patch.object(generator, "_generate_with_provider", return_value=True) as provider,
                ):
                    self.assertTrue(generator._handle_external_provider_workflow("diff"))
                provider.assert_called_once_with("diff", expected)
                if interactive:
                    confirm.assert_called_once_with("Generate commit message using external providers?", default=True)
                    display.assert_called_once_with(
                        input_budget=1234,
                        details=(f"Scope: {'on' if effective[0] else 'off'}; "
                                 f"footer: {'on' if effective[1] else 'off'}; "
                                 f"body: {'on' if effective[2] else 'off'}; style: {effective[3]}"),
                    )
                    self.assertNotIn("  ", display.call_args.kwargs["details"])
                else:
                    confirm.assert_not_called()
                    display.assert_not_called()

    def test_declining_external_generation_hands_off_same_prompt(self):
        for scope, footer, body, style in FORMATS:
            with self.subTest(scope=scope, footer=footer, body=body, style=style):
                generator = CommitGenerator(
                    interactive=True, include_scope=scope, include_footer=footer,
                    include_body=body, body_style=style,
                )
                system = generator._build_system_message(scope, footer, body, style)
                with (
                    patch.object(generator, "display_generation_settings"),
                    patch.object(generator, "prompt_confirm", return_value=False),
                    patch.object(generator, "handoff_local_prompt") as handoff,
                    patch.object(generator, "_generate_with_provider") as provider,
                ):
                    self.assertFalse(generator._handle_external_provider_workflow("local diff"))
                handoff.assert_called_once_with(generator._build_full_prompt("local diff", system), allow_auto=True)
                provider.assert_not_called()

    def test_prompt_defaults_preserve_two_positional_arguments(self):
        generator = CommitGenerator()
        self.assertEqual(generator._build_system_message(False, False),
                         generator._build_system_message(False, False, True, "bullets"))
        with self.assertRaisesRegex(ValueError, "Unsupported commit body style"):
            generator._build_system_message(False, False, True, "invalid")

    def test_constructor_keeps_existing_positional_api(self):
        generator = CommitGenerator("model", 0.2, 111, 222, True, False, False, True, True, "normal", True)
        self.assertTrue(generator._interactive)
        self.assertTrue(generator._cli_include_scope)
        self.assertFalse(generator._cli_include_footer)
        self.assertFalse(generator._cli_auto_commit)
        self.assertTrue(generator._cli_copy_clipboard)
        self.assertTrue(generator._cli_force_sensitive)
        self.assertEqual(generator._cli_workflow_kind, "normal")
        self.assertIsNone(generator._cli_include_body)
        self.assertIsNone(generator._cli_body_style)

    def test_open_release_subject_is_independent_of_format(self):
        for scope, footer, body, style in FORMATS:
            with self.subTest(scope=scope, footer=footer, body=body, style=style):
                generator = CommitGenerator(
                    include_scope=scope, include_footer=footer, include_body=body, body_style=style,
                    workflow_kind="open-release", auto_commit=True,
                )
                with (
                    patch.object(generator, "_get_staged_files", return_value=[]),
                    patch.object(generator, "_handle_external_provider_workflow") as external,
                    patch("git_tools.generators.commitgen.workflow.subprocess.run") as run,
                ):
                    generator.generate_commit()
                run.assert_called_once_with(
                    ["git", "commit", "--allow-empty", "-m", "chore: open release"], check=True, timeout=30,
                )
                external.assert_not_called()

    def test_generation_modes_preserve_payload_and_fallback_in_both_modes(self):
        """Exercise the real flow from effective prompt through preview and action."""
        diff = "diff --git a/cache.py b/cache.py\n+preserve()"
        for interactive, path, action in product((False, True), ("provider", "local", "missing-key"), ("copy", "commit", "neither")):
            if not interactive and path == "local":
                continue  # Direct mode always attempts the configured provider.
            with self.subTest(interactive=interactive, path=path, action=action):
                saved = SimpleNamespace(commit_include_scope=True, commit_include_footer=True,
                                        commit_include_body=True, commit_body_style="prose", default_token_limit=6543)
                generator = CommitGenerator(interactive=interactive, workflow_kind="normal",
                                            auto_commit=action == "commit", copy_clipboard=action == "copy")
                message = "fix(cache): preserve paragraphs\n\nExplain the change.\n\nKeep the second paragraph.\n\nRefs: #42"
                response = {"content": "```text\n" + message + "\n```"}
                with ExitStack() as stack:
                    stack.enter_context(patch("git_tools.generators.commitgen.generator.settings", saved))
                    stack.enter_context(patch.object(generator, "get_staged_diff", return_value=diff))
                    stack.enter_context(patch.object(generator, "_check_sensitive_files", return_value=True))
                    stack.enter_context(patch.object(generator, "get_staged_diff_enhanced", return_value=(diff, [])))
                    stack.enter_context(patch.object(generator, "display_generation_settings"))
                    stack.enter_context(patch.object(generator, "prompt_confirm", return_value=path != "local"))
                    stack.enter_context(patch.object(generator, "select_provider", return_value="openrouter"))
                    stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=path != "missing-key"))
                    model = stack.enter_context(patch.object(generator, "select_model_params", return_value=("model", 0.6, 100)))
                    initialize = stack.enter_context(patch.object(generator, "_initialize_service", return_value=True))
                    invoke = stack.enter_context(patch.object(generator, "invoke_llm", return_value=response))
                    stack.enter_context(patch.object(generator, "display_reasoning"))
                    stack.enter_context(patch.object(generator, "display_token_usage"))
                    console = stack.enter_context(patch("git_tools.generators.commitgen.generator.console"))
                    local = stack.enter_context(patch.object(generator, "handoff_local_prompt"))
                    copied = stack.enter_context(patch.object(generator, "copy_to_clipboard_auto"))
                    run = stack.enter_context(patch("git_tools.generators.commitgen.generator.subprocess.run"))
                    generator.generate_commit()
                system = generator._build_system_message(True, True, True, "prose")
                if path == "provider":
                    self.assertEqual(invoke.call_args.args[0][0], {"role": "system", "content": system})
                    panels = [call.args[0] for call in console.print.call_args_list if call.args and hasattr(call.args[0], "renderable")]
                    self.assertEqual(str(panels[0].renderable), message)
                    local.assert_not_called()
                    if action == "commit":
                        run.assert_called_once_with(["git", "commit", "-m", message], check=True, timeout=30)
                        copied.assert_not_called()
                    elif action == "copy":
                        copied.assert_called_once_with(message, leading_space=False)
                        run.assert_not_called()
                    else:
                        copied.assert_not_called()
                        run.assert_not_called()
                else:
                    local.assert_called_once_with(generator._build_full_prompt(diff, system), allow_auto=path == "local")
                    model.assert_not_called()
                    initialize.assert_not_called()
                    invoke.assert_not_called()
                    copied.assert_not_called()
                    run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

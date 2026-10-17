"""Offline regressions for PR output preservation and explicit Start targets."""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from git_tools.generators.bumpgen import BumpError, Version
from git_tools.generators.issueprgen import IssuePullRequestGenerator
from git_tools.generators.issueprgen.prompts import PromptAssemblyMixin


class PrFenceParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = PromptAssemblyMixin()
        self.body = "## Title: feat: preserve me\n\n## Summary\nImportant final line"

    def test_unfenced_content_is_preserved_exactly(self) -> None:
        for raw in ("", "one line", "first\nlast", self.body, f"\n {self.body}\n\n"):
            with self.subTest(raw=raw):
                self.assertEqual(self.parser.parse_generated_content(raw), raw)

    def test_complete_matching_outer_fences_are_removed(self) -> None:
        for opening, closing in (
            ("```", "```"),
            ("```markdown", "```"),
            ("```md", "````"),
            ("~~~markdown", "~~~"),
            ("````markdown", "````"),
            ("  ```markdown", "   ```  "),
        ):
            with self.subTest(opening=opening, closing=closing):
                raw = f"{opening}\n{self.body}\n{closing}"
                self.assertEqual(self.parser.parse_generated_content(raw), self.body)

    def test_blank_edges_around_verified_fences_are_ignored(self) -> None:
        raw = f"\n \t\n```markdown\n{self.body}\n```\n\n \t\n"
        self.assertEqual(self.parser.parse_generated_content(raw), self.body)

    def test_crlf_content_keeps_body_line_endings(self) -> None:
        body = self.body.replace("\n", "\r\n")
        raw = f"```markdown\r\n{body}\r\n```\r\n"
        self.assertEqual(self.parser.parse_generated_content(raw), body)

    def test_partial_mismatched_or_invalid_fences_are_preserved(self) -> None:
        for raw in (
            f"```markdown\n{self.body}",
            f"{self.body}\n```",
            f"```markdown\n{self.body}\n~~~",
            f"````markdown\n{self.body}\n```",
            f"```markdown\n{self.body}\n``` trailing prose",
            f"```mark`down\n{self.body}\n```",
            f"    ```markdown\n{self.body}\n```",
            f"```markdown\n{self.body}\n    ```",
            "```",
            "```markdown\n",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.parser.parse_generated_content(raw), raw)

    def test_prose_outside_fences_is_preserved(self) -> None:
        for raw in (
            f"Here is the PR:\n```markdown\n{self.body}\n```",
            f"```markdown\n{self.body}\n```\nFinal important detail",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.parser.parse_generated_content(raw), raw)

    def test_shorter_nested_fences_and_all_body_text_are_preserved(self) -> None:
        body = f"{self.body}\n\n```python\nprint('example')\n```\nLast detail"
        raw = f"````markdown\n{body}\n````"
        self.assertEqual(self.parser.parse_generated_content(raw), body)

    def test_same_marker_inner_closing_fence_prevents_unwrapping(self) -> None:
        # The first ``` already closes the block: these are multiple blocks,
        # not a verified outer wrapper around the complete response.
        raw = f"```markdown\n{self.body}\n```\nUnfenced detail\n```"
        self.assertEqual(self.parser.parse_generated_content(raw), raw)

    def test_multiple_separate_fenced_blocks_are_not_treated_as_one(self) -> None:
        raw = "```markdown\nFirst section\n```\n\n```markdown\nLast section\n```"
        self.assertEqual(self.parser.parse_generated_content(raw), raw)

    def test_valid_empty_or_single_line_fenced_body(self) -> None:
        for raw, expected in (
            ("```\n```", ""),
            ("```\n\n```", ""),
            ("```markdown\nOnly line\n```", "Only line"),
            ("```markdown\n\nOnly line\n\n```", "\nOnly line\n"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(self.parser.parse_generated_content(raw), expected)


class ExplicitStartVersionTests(unittest.TestCase):
    def make_generator(self, target: str | None = "1.7.1") -> IssuePullRequestGenerator:
        return IssuePullRequestGenerator(
            generation_type="pr",
            start_pr=True,
            workflow_version=target,
            interactive=False,
        )

    def start_context(
        self, generator, *, base="1.7.0", current="1.7.0", config_error=None
    ):
        """Mock all repo/config reads, without changing the transition validator."""
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            patch.object(generator, "_get_current_branch_name", return_value="develop")
        )
        stack.enter_context(
            patch.object(generator, "_load_version_from_ref", return_value=base)
        )
        config = SimpleNamespace(
            current_version_text=current, current_version=Version.parse(current)
        )
        stack.enter_context(
            patch(
                "git_tools.generators.issueprgen.workflow.load_bump_config",
                return_value=config,
                side_effect=config_error,
            )
        )
        return stack

    def test_explicit_patch_with_missing_base_fails_instead_of_guessing_minor(self) -> None:
        generator = self.make_generator()
        self.start_context(generator, base=None)
        with patch.object(
            generator, "_infer_start_target_version", return_value="1.8.0"
        ) as infer, self.assertRaisesRegex(
            ValueError, r"explicit Start target 1\.7\.1.*base version.*develop:.*cz\.toml"
        ):
            generator._resolve_start_pr_context("develop")
        infer.assert_not_called()

    def test_missing_base_error_propagates_before_generation_or_copy(self) -> None:
        generator = self.make_generator()
        self.start_context(generator, base=None)
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(generator, "get_default_branch", return_value="develop")
            )
            forbidden = [
                stack.enter_context(
                    patch.object(generator, name, side_effect=AssertionError(name))
                )
                for name in (
                    "get_commit_info", "_collect_generation_content", "select_provider",
                    "_initialize_service", "generate_content", "copy_to_clipboard_auto",
                    "ask_to_copy_to_clipboard",
                )
            ]
            stack.enter_context(patch("git_tools.generators.issueprgen.generator.console"))
            with self.assertRaisesRegex(ValueError, r"explicit Start target 1\.7\.1"):
                generator.generate_issue_pullrequest()
        for boundary in forbidden:
            boundary.assert_not_called()

    def test_explicit_target_with_missing_current_config_fails_clearly(self) -> None:
        generator = self.make_generator()
        self.start_context(generator, config_error=BumpError("No managed version"))
        with patch.object(generator, "_infer_start_target_version") as infer:
            with self.assertRaisesRegex(
                ValueError, r"explicit Start target 1\.7\.1.*current \.cz\.toml"
            ):
                generator._resolve_start_pr_context("develop")
        infer.assert_not_called()

    def test_explicit_input_is_validated_even_when_all_context_is_missing(self) -> None:
        for target in ("", "   ", "1.7", "1.7.1-alpha.0", "v1.7.1"):
            with self.subTest(target=target):
                generator = self.make_generator(target)
                self.start_context(
                    generator, base=None, config_error=BumpError("Missing config")
                )
                with self.assertRaisesRegex(ValueError, "exact release tuple X.Y.Z"):
                    generator._resolve_start_pr_context("develop")

    def test_valid_explicit_patch_minor_major_keep_existing_transition_rules(self) -> None:
        for target in ("1.7.1", "1.8.0", "2.0.0"):
            with self.subTest(target=target):
                generator = self.make_generator(f" {target} ")
                self.start_context(generator)
                with patch.object(generator, "_infer_start_target_version") as infer:
                    context = generator._resolve_start_pr_context("develop")
                self.assertIsNotNone(context)
                self.assertEqual(context.target_version, target)
                self.assertEqual(context.fixed_title, f"Start {target}")
                self.assertIn(f"{target}-alpha.0", context.behavior_summary)
                self.assertEqual(context.current_version, "1.7.0")
                self.assertEqual(context.base_version, "1.7.0")
                generator._workflow_pr_context = context
                self.assertEqual(generator._resolve_fixed_pr_title(), f"Start {target}")
                infer.assert_not_called()

    def test_explicit_target_keeps_current_prerelease_scheme(self) -> None:
        for current, expected_alpha in (
            ("1.7.0-a2", "1.7.1-a0"),
            ("1.7.0-alpha.2", "1.7.1-alpha.0"),
        ):
            with self.subTest(current=current):
                generator = self.make_generator()
                self.start_context(generator, current=current)
                context = generator._resolve_start_pr_context("develop")
                self.assertEqual(context.fixed_title, "Start 1.7.1")
                self.assertIn(expected_alpha, context.behavior_summary)

    def test_invalid_explicit_transition_is_not_replaced_by_inference(self) -> None:
        for target in ("1.7.0", "1.7.2", "1.6.9", "1.9.0", "3.0.0"):
            with self.subTest(target=target):
                generator = self.make_generator(target)
                self.start_context(generator)
                with patch.object(generator, "_infer_start_target_version") as infer:
                    with self.assertRaisesRegex(ValueError, "not a valid MAJOR/MINOR/PATCH step"):
                        generator._resolve_start_pr_context("develop")
                infer.assert_not_called()

    def test_explicit_title_without_validated_context_fails_not_infers(self) -> None:
        generator = self.make_generator()
        with patch.object(
            generator, "_infer_start_target_version", return_value="1.8.0"
        ) as infer, self.assertRaisesRegex(
            ValueError, r"explicit Start target 1\.7\.1.*validated"
        ):
            generator._resolve_fixed_pr_title()
        infer.assert_not_called()

    def test_no_override_keeps_missing_context_and_title_fallback_compatibility(self) -> None:
        for base, config_error in (
            (None, None),
            ("1.7.0", BumpError("No managed version")),
        ):
            with self.subTest(base=base, config_error=config_error):
                generator = self.make_generator(None)
                self.start_context(generator, base=base, config_error=config_error)
                self.assertIsNone(generator._resolve_start_pr_context("develop"))
                with patch.object(
                    generator, "_infer_start_target_version", return_value="1.8.0"
                ):
                    self.assertEqual(generator._resolve_fixed_pr_title(), "Start 1.8.0")

    def test_valid_inferred_start_still_builds_same_context(self) -> None:
        generator = self.make_generator(None)
        self.start_context(generator)
        with patch.object(
            generator, "_infer_start_target_version", return_value="1.8.0"
        ):
            context = generator._resolve_start_pr_context("develop")
        self.assertEqual(context.fixed_title, "Start 1.8.0")
        self.assertIn("1.8.0-alpha.0", context.behavior_summary)


class PrOutputHandoffSafetyTests(unittest.TestCase):
    def run_response(self, generation_type: str, raw: str):
        generator = IssuePullRequestGenerator(
            generation_type=generation_type, input_source="c", interactive=False
        )
        with ExitStack() as stack:
            for name, value in (
                ("get_default_branch", "develop"),
                ("get_commit_info", {"base_branch": "develop", "commit_count": 1}),
                ("_collect_generation_content", ("c", "Commit Messages:\nfeat: preserve")),
                ("select_provider", "openrouter"),
                ("ensure_api_key_configured", True),
                ("select_model_params", ("test-model", 0.0, 1000)),
                ("_initialize_service", True),
                ("generate_content", {"content": raw}),
                ("_should_apply_azure_limit", False),
            ):
                stack.enter_context(patch.object(generator, name, return_value=value))
            for name in ("show_commit_summary", "display_reasoning", "display_token_usage"):
                stack.enter_context(patch.object(generator, name))
            copied = stack.enter_context(patch.object(generator, "copy_to_clipboard_auto"))
            printed = stack.enter_context(
                patch("git_tools.generators.issueprgen.generator.console")
            )
            # Any unexpected side effect is an immediate test failure.
            for name in ("subprocess.check_output", "subprocess.run", "pyperclip.copy"):
                stack.enter_context(patch(name, side_effect=AssertionError(name)))
            generator.generate_issue_pullrequest()
        panels = [
            call.args[0] for call in printed.print.call_args_list
            if call.args and hasattr(call.args[0], "renderable")
        ]
        self.assertEqual(len(panels), 1)
        return str(panels[0].renderable), copied.call_args.args[0]

    def test_unfenced_pr_preview_and_copy_keep_title_and_last_detail(self) -> None:
        raw = "## Title: feat: preserve me\n\n## Summary\nImportant final line"
        displayed, copied = self.run_response("pr", raw)
        self.assertEqual(displayed, raw)
        self.assertEqual(copied, raw)

    def test_fenced_pr_preview_and_copy_match_unwrapped_body(self) -> None:
        body = "## Title: feat: preserve me\n\n## Summary\nImportant final line"
        displayed, copied = self.run_response("pr", f"```markdown\n{body}\n```")
        self.assertEqual(displayed, body)
        self.assertEqual(copied, body)

    def test_issue_keeps_raw_copy_compatibility(self) -> None:
        body = "## Title: issue title\n\nImportant final line"
        raw = f"```markdown\n{body}\n```"
        displayed, copied = self.run_response("issue", raw)
        self.assertEqual(displayed, body)
        self.assertEqual(copied, raw)

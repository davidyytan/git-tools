"""Rendered spacing regressions; all external effects are mocked or temporary."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rich.console import Console

from git_tools.generators.bumpgen import BumpGenerator, Version
from git_tools.generators.bumpgen.engine import FileUpdate, print_bump_plan, run_bump
from git_tools.generators.commitgen import CommitGenerator
from git_tools.generators.initgen import CommitizenInitGenerator, CzInitError
from git_tools.generators.issueprgen import IssuePullRequestGenerator
from git_tools.generators.issueprgen.azure import AzureLimitMixin


COMMIT_INFO = {
    "base_branch": "origin/develop", "commit_count": 1,
    "first_hash": "abc1234", "first_message": "feat: first",
    "last_hash": "abc1234", "last_message": "feat: first",
}
QUOTA = ["- demo.py: Original diff size: 20 tokens, Quota allocated: 10 tokens"]
CONSOLES = (
    "git_tools.cli", "git_tools.generators.base.terminal",
    "git_tools.generators.base.interaction", "git_tools.generators.base.display",
    "git_tools.generators.base.models", "git_tools.generators.commitgen.generator",
    "git_tools.generators.commitgen.workflow", "git_tools.generators.commitgen.sensitive",
    "git_tools.generators.issueprgen.generator", "git_tools.generators.issueprgen.commits",
    "git_tools.generators.issueprgen.azure", "git_tools.generators.issueprgen.content",
    "git_tools.generators.initgen.generator",
)


@contextmanager
def captured_console(width, answers=()):
    """Use real renderers and prompt helpers, replacing only terminal input."""
    output = StringIO()
    console = Console(file=output, width=width, force_terminal=False, soft_wrap=True)
    remaining = iter(answers)
    questions = []

    def question(message, **kwargs):
        answer = next(remaining)
        questions.append(message)

        def ask():
            # Completed Questionary prompts leave one answered line, not a gap.
            console.print(f"❯ {message} {answer}", markup=False, soft_wrap=False)
            return answer

        return SimpleNamespace(ask=ask)

    with ExitStack() as stack:
        for module in CONSOLES:
            stack.enter_context(patch(f"{module}.console", console, create=True))
        stack.enter_context(patch("git_tools.generators.base.interaction.questionary.select", side_effect=question))
        stack.enter_context(patch("git_tools.generators.base.interaction.questionary.text", side_effect=question))
        stack.enter_context(redirect_stdout(output))
        yield output, console, questions, stack


class RenderedSpacingTests(unittest.TestCase):
    def assert_panel_gaps(self, output):
        lines = [line.rstrip() for line in output.splitlines()]
        self.assertNotIn("\n\n\n", "\n".join(lines), output)
        bottoms = [index for index, line in enumerate(lines) if line.startswith("╰")]
        self.assertTrue(bottoms, output)
        for index in bottoms:
            self.assertLess(index + 1, len(lines), output)
            self.assertEqual(lines[index + 1], "", output)
            if index + 2 < len(lines):
                self.assertNotEqual(lines[index + 2], "", output)

    def provider_boundaries(self, stack, generator, response, *, live=True):
        stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=True))
        stack.enter_context(patch.object(generator, "select_provider", return_value="openrouter"))
        stack.enter_context(patch.object(generator, "get_provider_config"))
        stack.enter_context(patch("git_tools.generators.base.models.refresh_live_models", return_value=live))
        stack.enter_context(patch("git_tools.cli.get_live_model_refresh_error", return_value=None))
        initialize = stack.enter_context(patch.object(generator, "_initialize_service", return_value=True))
        method = "generate_commit_message" if isinstance(generator, CommitGenerator) else "generate_content"
        generate = stack.enter_context(patch.object(generator, method, return_value=response))
        copy = stack.enter_context(patch("pyperclip.copy"))
        return initialize, generate, copy

    def commit_boundaries(self, stack, generator, quota):
        stack.enter_context(patch.object(generator, "get_staged_diff", return_value="diff [kept]"))
        stack.enter_context(patch.object(generator, "_detect_sensitive_files", return_value=[]))
        stack.enter_context(patch.object(generator, "get_staged_diff_enhanced", return_value=("diff [kept]", quota)))

    def issue_boundaries(self, stack, generator, quota):
        stack.enter_context(patch.object(generator, "get_default_branch", return_value="origin/develop"))
        stack.enter_context(patch.object(generator, "get_commit_info", return_value=COMMIT_INFO))
        stack.enter_context(patch("git_tools.generators.issueprgen.commits.subprocess.check_output", return_value="feature/demo\n"))
        stack.enter_context(patch.object(generator, "get_commit_messages", return_value="feat: first"))
        stack.enter_context(patch.object(generator, "get_branch_diffs", return_value=("diff [kept]", quota)))
        stack.enter_context(patch.object(generator, "_should_apply_azure_limit", return_value=False))

    def test_commit_panels_and_actions_with_optional_diagnostics(self):
        for width in (48, 120):
            for interactive in (False, True):
                for diagnostics in (False, True):
                    with self.subTest(width=width, interactive=interactive, diagnostics=diagnostics):
                        response = {"content": "fix: preserve output [kept]"}
                        if diagnostics:
                            response.update(
                                additional_kwargs={"reasoning_content": "Reasoning [kept]"},
                                response_metadata={"token_usage": {"prompt_tokens": 12, "completion_tokens": 3}},
                            )
                        generator = CommitGenerator(
                            interactive=interactive, copy_clipboard=True,
                            auto_commit=None if interactive else False,
                        )
                        answers = ("Conventional Commit", "Yes", "No") if interactive else ()
                        with captured_console(width, answers) as (output, _, questions, stack):
                            self.commit_boundaries(stack, generator, QUOTA if diagnostics else [])
                            _, generate, copy = self.provider_boundaries(stack, generator, response)
                            commit = stack.enter_context(patch("git_tools.generators.commitgen.generator.subprocess.run"))
                            generator.generate_commit()
                        rendered = output.getvalue()
                        self.assert_panel_gaps(rendered)
                        self.assertIn("[kept]", rendered)
                        self.assertEqual("File Quota" in rendered, diagnostics)
                        self.assertEqual("Token Usage" in rendered, diagnostics)
                        self.assertEqual("╭─ Reasoning" in rendered, diagnostics)
                        if interactive:
                            self.assertIn("providers? Yes\n\n", rendered)
                            self.assertIn("directly? No\n\n✓ Copied", rendered)
                            self.assertEqual(len(questions), 3)
                        generate.assert_called_once()
                        copy.assert_called_once_with("fix: preserve output [kept]")
                        commit.assert_not_called()

    def test_issue_pr_panels_and_copy_questions_with_optional_diagnostics(self):
        for width in (48, 120):
            for kind in ("issue", "pr"):
                for diagnostics in (False, True):
                    with self.subTest(width=width, kind=kind, diagnostics=diagnostics):
                        response = {"content": "```markdown\n## Title: feat: preserve output\n\nBody [kept]\n```"}
                        if diagnostics:
                            response.update(
                                additional_kwargs={"reasoning_content": "Reasoning [kept]"},
                                response_metadata={"token_usage": {"total_tokens": 15}},
                            )
                        generator = IssuePullRequestGenerator(generation_type=kind, input_source="b", interactive=True)
                        answers = ("Ordinary PR", "", "Yes", "No") if kind == "pr" else ("", "Yes", "No")
                        with captured_console(width, answers) as (output, _, questions, stack):
                            self.issue_boundaries(stack, generator, QUOTA if diagnostics else [])
                            _, generate, copy = self.provider_boundaries(stack, generator, response)
                            generator.generate_issue_pullrequest()
                        rendered = output.getvalue()
                        self.assert_panel_gaps(rendered)
                        self.assertIn("Body [kept]", rendered)
                        self.assertEqual("File Quota" in rendered, diagnostics)
                        self.assertEqual("Token Usage" in rendered, diagnostics)
                        self.assertIn("providers? Yes\n\n", rendered)
                        self.assertIn("clipboard? No\n\n✓ Generation complete.", rendered)
                        self.assertFalse(any("?:" in question for question in questions))
                        generate.assert_called_once()
                        copy.assert_not_called()

    def test_real_origin_detection_separates_context_and_settings(self):
        for width in (48, 120):
            for context in (None, "explicit context"):
                for origin in ("https://dev.azure.com/org/project/_git/repo", "https://github.com/org/repo", None):
                    with self.subTest(width=width, context=context, origin=origin):
                        generator = IssuePullRequestGenerator(generation_type="pr", input_source="c",
                                                              context=context, interactive=True, copy_clipboard=False)
                        answers = ("Ordinary PR", "", "No") if context is None else ("Ordinary PR", "No")
                        with captured_console(width, answers) as (output, _, _, stack):
                            self.issue_boundaries(stack, generator, [])
                            generator._should_apply_azure_limit.side_effect = lambda: AzureLimitMixin._should_apply_azure_limit(generator)
                            stack.enter_context(patch("git_tools.generators.issueprgen.azure.settings", SimpleNamespace(azure_pr_limit="auto", azure_pr_max_chars=4000)))
                            stack.enter_context(patch.object(generator, "_get_origin_url", return_value=origin))
                            generator.generate_issue_pullrequest()
                        text = output.getvalue()
                        self.assert_panel_gaps(text)
                        self.assertRegex(text, r"\n\n• Origin remote: (?:Azure DevOps repository|Non-Azure DevOps repository|Not configured)\n\n╭")

    def test_messages_only_fallback_warning_has_one_next_prompt_gap(self):
        generator = IssuePullRequestGenerator(generation_type="pr", input_source="b", interactive=True, copy_clipboard=False)
        with captured_console(120, ("Ordinary PR", "", "No")) as (output, _, _, stack):
            self.issue_boundaries(stack, generator, [])
            generator.get_branch_diffs.return_value = ("", [])
            generator.generate_issue_pullrequest()
        self.assert_panel_gaps(output.getvalue())
        self.assertIn("using commit messages only.\n\n❯ Additional context", output.getvalue())

    def test_direct_catalog_fallback_separates_status_from_generated_panel(self):
        for width in (48, 120):
            with self.subTest(width=width), captured_console(width) as (output, _, _, stack):
                generator = CommitGenerator(auto_commit=False, copy_clipboard=False)
                self.commit_boundaries(stack, generator, [])
                self.provider_boundaries(stack, generator, {"content": "fix: retained output"}, live=False)
                generator.generate_commit()
                rendered = output.getvalue()
                self.assert_panel_gaps(rendered)
                self.assertRegex(rendered, r"(?:models\.|accepted)\n\n╭")

    def test_local_decline_and_missing_credentials_do_not_double_panel_copy_gap(self):
        for width in (48, 120):
            for kind in ("commit", "pr"):
                for path in ("decline", "missing-key"):
                    with self.subTest(width=width, kind=kind, path=path):
                        generator = (CommitGenerator(interactive=True, copy_clipboard=True)
                                     if kind == "commit" else IssuePullRequestGenerator(generation_type="pr", interactive=True, copy_clipboard=True))
                        answers = (["Conventional Commit"] if kind == "commit" else ["Ordinary PR", ""])
                        answers.append("No" if path == "decline" else "Yes")
                        with captured_console(width, answers) as (output, _, _, stack):
                            if kind == "commit":
                                self.commit_boundaries(stack, generator, [])
                                stack.enter_context(patch.object(generator, "_build_full_prompt", return_value="LOCAL [kept]"))
                                execute = generator.generate_commit
                            else:
                                self.issue_boundaries(stack, generator, [])
                                stack.enter_context(patch.object(generator, "_build_system_message", return_value="SYSTEM"))
                                stack.enter_context(patch.object(generator, "_build_full_prompt", return_value="LOCAL [kept]"))
                                execute = generator.generate_issue_pullrequest
                            stack.enter_context(patch.object(generator, "ensure_api_key_configured", return_value=False))
                            initialize = stack.enter_context(patch.object(generator, "_initialize_service"))
                            copy = stack.enter_context(patch("pyperclip.copy"))
                            execute()
                        rendered = output.getvalue()
                        self.assert_panel_gaps(rendered)
                        self.assertIn("LOCAL [kept]", rendered)
                        self.assertIn("✓ Copied to clipboard!", rendered)
                        initialize.assert_not_called()
                        copy.assert_called_once()

    def test_workflow_and_sensitive_panels_own_their_separator(self):
        for width in (48, 120):
            for sensitive in (False, True):
                with self.subTest(width=width, sensitive=sensitive):
                    generator = CommitGenerator(interactive=True, copy_clipboard=True)
                    answers = ("chore: open release", "Yes", "No") if sensitive else ("chore: open release", "No")
                    with captured_console(width, answers) as (output, _, _, stack):
                        stack.enter_context(patch.object(generator, "_get_staged_files", return_value=[".env"] if sensitive else []))
                        stack.enter_context(patch.object(generator, "_detect_sensitive_files", return_value=[".env"] if sensitive else []))
                        commit = stack.enter_context(patch("git_tools.generators.commitgen.workflow.subprocess.run"))
                        copy = stack.enter_context(patch("pyperclip.copy"))
                        generator.generate_commit()
                    self.assert_panel_gaps(output.getvalue())
                    self.assertEqual("WARNING" in output.getvalue(), sensitive)
                    copy.assert_called_once_with("chore: open release")
                    commit.assert_not_called()

    def test_direct_pr_and_workflow_copies_have_one_panel_result_gap(self):
        for width in (48, 120):
            for kind in ("pr", "workflow"):
                with self.subTest(width=width, kind=kind), captured_console(width) as (output, _, _, stack):
                    if kind == "pr":
                        generator = IssuePullRequestGenerator(generation_type="pr", input_source="c", copy_clipboard=True)
                        self.issue_boundaries(stack, generator, [])
                        _, _, copy = self.provider_boundaries(stack, generator, {"content": "## Title: feat: preserved output"})
                        generator.generate_issue_pullrequest()
                    else:
                        generator = CommitGenerator(workflow_kind="open-release", auto_commit=False, copy_clipboard=True)
                        stack.enter_context(patch.object(generator, "_get_staged_files", return_value=[]))
                        copy = stack.enter_context(patch("pyperclip.copy"))
                        generator.generate_commit()
                    self.assert_panel_gaps(output.getvalue())
                    self.assertIn("✓ Copied to clipboard!", output.getvalue())
                    copy.assert_called_once()

    def test_credential_setup_decline_keeps_local_fallback_sections_separate(self):
        generator = CommitGenerator(interactive=True, copy_clipboard=False)
        with captured_console(48, ("Conventional Commit", "Yes", "No")) as (output, _, _, stack):
            self.commit_boundaries(stack, generator, [])
            stack.enter_context(patch("git_tools.settings.settings.check_api_key_configured", return_value=(False, None)))
            setup = stack.enter_context(patch("git_tools.settings.settings.setup_api_key"))
            stack.enter_context(patch.object(generator, "_build_full_prompt", return_value="LOCAL [kept]"))
            generator.generate_commit()
        self.assert_panel_gaps(output.getvalue())
        self.assertIn("now? No\n\n• Falling back to local mode...\n\n╭", output.getvalue())
        setup.assert_not_called()

    def test_fixed_context_without_summary_or_quota_has_one_settings_gap(self):
        generator = IssuePullRequestGenerator(generation_type="pr", context="", interactive=True, copy_clipboard=False)
        fixed = SimpleNamespace(to_prompt_block=lambda: "Fixed workflow context")
        with captured_console(48, ("Release PR", "No")) as (output, _, _, stack):
            stack.enter_context(patch.object(generator, "get_default_branch", return_value="origin/master"))
            stack.enter_context(patch.object(generator, "get_commit_info", return_value=None))
            stack.enter_context(patch.object(generator, "_resolve_release_pr_context", return_value=fixed))
            stack.enter_context(patch.object(generator, "_build_system_message", return_value="SYSTEM"))
            stack.enter_context(patch.object(generator, "_build_full_prompt", return_value="LOCAL [kept]"))
            stack.enter_context(patch.object(generator, "_should_apply_azure_limit", return_value=False))
            generator.generate_issue_pullrequest()
        self.assert_panel_gaps(output.getvalue())
        self.assertIn("Release PR\n\n╭", output.getvalue())
        self.assertNotIn("Commit Range Summary", output.getvalue())
        self.assertNotIn("File Quota", output.getvalue())

    def test_commit_apply_separates_git_output_without_duplicate_panel_gap(self):
        for interactive in (False, True):
            with self.subTest(interactive=interactive):
                generator = CommitGenerator(interactive=interactive)
                answers = ("Conventional Commit", "Yes", "Yes") if interactive else ()
                with captured_console(120, answers) as (output, _, _, stack):
                    self.commit_boundaries(stack, generator, [])
                    self.provider_boundaries(stack, generator, {"content": "fix: preserved output"})
                    commit = stack.enter_context(patch("git_tools.generators.commitgen.generator.subprocess.run", side_effect=lambda *args, **kwargs: print("[branch abc1234] fix: preserved output")))
                    generator.generate_commit()
                self.assert_panel_gaps(output.getvalue())
                self.assertIn("[branch abc1234] fix: preserved output\n\n✓ Committed changes.", output.getvalue())
                commit.assert_called_once()

    def test_sensitive_decline_is_separate_from_cancellation_status(self):
        generator = CommitGenerator(interactive=True)
        with captured_console(48, ("Conventional Commit", "No")) as (output, _, _, stack):
            self.commit_boundaries(stack, generator, [])
            stack.enter_context(patch.object(generator, "_detect_sensitive_files", return_value=[".env"]))
            generate = stack.enter_context(patch.object(generator, "generate_commit_message"))
            generator.generate_commit()
        self.assert_panel_gaps(output.getvalue())
        self.assertIn("No\n\n⚠ Commit cancelled.", output.getvalue())
        generate.assert_not_called()


class ReleaseSpacingTests(unittest.TestCase):
    assert_panel_gaps = RenderedSpacingTests.assert_panel_gaps

    def test_init_direct_interactive_write_and_cancel(self):
        for width in (48, 120):
            for mode in ("direct", "write", "cancel", "explicit"):
                with self.subTest(width=width, mode=mode), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    interactive = mode != "direct"
                    explicit = mode == "explicit"
                    generator = CommitizenInitGenerator(
                        interactive=interactive, version="1.2.3" if explicit else None,
                        tag_format="$version" if explicit else None,
                    )
                    answers = (("Yes",) if explicit else ("0.1.0", "$version", "Yes", "No" if mode == "cancel" else "Yes")) if interactive else ()
                    with captured_console(width, answers) as (output, _, questions, _):
                        if mode == "cancel":
                            with self.assertRaisesRegex(CzInitError, "Init cancelled"):
                                generator.generate_init(cwd=root)
                        else:
                            generator.generate_init(cwd=root)
                    rendered = output.getvalue()
                    self.assertEqual((root / ".cz.toml").exists(), mode != "cancel")
                    if interactive:
                        self.assert_panel_gaps(rendered)
                        self.assertFalse(any("?:" in question for question in questions))
                        if not explicit:
                            self.assertIn("version: 0.1.0\n❯ Enter the tag format:", rendered)
                            self.assertIn("format: $version\n❯ Treat", rendered)
                        else:
                            self.assertTrue(rendered.startswith("╭"), rendered)
                        if mode != "cancel":
                            self.assertIn("now? Yes\n\n✓ Wrote", rendered)
                    else:
                        self.assertTrue(rendered.startswith("✓ Wrote"), rendered)
                        self.assertNotIn("╭", rendered)

    def make_plan(self, root, options):
        return SimpleNamespace(
            config=SimpleNamespace(root=root, current_version_text="0.1.0"),
            options=options, new_version=Version.parse("0.1.1"), increment="PATCH",
            message="bump: version 0.1.0 -> 0.1.1", tag_name="0.1.1",
            tag_behavior="lightweight tag", updates=(FileUpdate(root / ".cz.toml", "version = '0.1.0'\n", "version = '0.1.1'\n"),),
        )

    def test_bump_interactive_preview_cancel_apply_and_dry_run(self):
        for width in (48, 120):
            for actions in (("Cancel",), ("Preview", "Cancel"), ("Preview", "Apply"), ("Apply",), ()):
                with self.subTest(width=width, actions=actions), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    generator = BumpGenerator(interactive=True, yes=True, dry_run=not actions)
                    with captured_console(width, ("PATCH", "Stable release", *actions)) as (output, _, questions, stack):
                        stack.enter_context(patch("git_tools.generators.bumpgen.generator.load_bump_config", return_value=SimpleNamespace(current_version_text="0.1.0")))
                        plan_mock = stack.enter_context(patch("git_tools.generators.bumpgen.generator.plan_bump"))
                        plan_mock.side_effect = lambda options, **kwargs: self.make_plan(root, options)
                        apply = stack.enter_context(patch("git_tools.generators.bumpgen.generator.apply_bump_plan", side_effect=lambda plan: print("Done!")))
                        generator.generate_bump(cwd=root)
                    rendered = output.getvalue()
                    self.assert_panel_gaps(rendered)
                    self.assertIn("Current version: 0.1.0\n\n❯ Select", rendered)
                    self.assertIn("increment: PATCH\n❯ Select release channel:", rendered)
                    self.assertIn("channel: Stable release\n\n╭", rendered)
                    self.assertIn("Version: 0.1.0 -> 0.1.1", rendered)
                    self.assertIn("applying.\n\n", rendered)
                    self.assertEqual(apply.call_count, int(bool(actions) and actions[-1] == "Apply"))
                    self.assertEqual(rendered.count("Version: 0.1.0 -> 0.1.1"), 2 if actions and actions[0] == "Preview" else 1)
                    self.assertFalse(any("?:" in question for question in questions))

    def test_bump_explicit_options_do_not_add_duplicate_context_gap(self):
        generator = BumpGenerator(interactive=True, increment="PATCH", prerelease="rc", yes=True, dry_run=True)
        with tempfile.TemporaryDirectory() as tmp, captured_console(48) as (output, _, _, stack):
            root = Path(tmp)
            stack.enter_context(patch("git_tools.generators.bumpgen.generator.load_bump_config", return_value=SimpleNamespace(current_version_text="0.1.0")))
            stack.enter_context(patch("git_tools.generators.bumpgen.generator.plan_bump", return_value=self.make_plan(root, generator._build_options())))
            generator.generate_bump(cwd=root)
        self.assert_panel_gaps(output.getvalue())
        self.assertIn("Current version: 0.1.0\n\n╭", output.getvalue())

    def test_bump_initial_history_decline_separates_cancellation(self):
        generator = BumpGenerator(interactive=True, increment="PATCH", prerelease="rc")
        config = SimpleNamespace(current_version_text="0.1.0", current_version=Version.parse("0.1.0"), tag_format="$version")
        with tempfile.TemporaryDirectory() as tmp, captured_console(48, ("No",)) as (output, _, _, stack):
            stack.enter_context(patch("git_tools.generators.bumpgen.generator.load_bump_config", return_value=config))
            stack.enter_context(patch("git_tools.generators.bumpgen.generator.get_tag_names", return_value=[]))
            stack.enter_context(patch("git_tools.generators.bumpgen.generator.resolve_version_history_ref", return_value=None))
            plan = stack.enter_context(patch("git_tools.generators.bumpgen.generator.plan_bump"))
            generator.generate_bump(cwd=Path(tmp))
        self.assertIn("history? No\n\n• Bump cancelled.", output.getvalue())
        self.assertNotIn("\n\n\n", output.getvalue())
        plan.assert_not_called()

    def test_direct_bump_and_get_next_keep_engine_stdout(self):
        for get_next in (False, True):
            with self.subTest(get_next=get_next), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                generator = BumpGenerator(get_next=get_next, dry_run=True)
                options = generator._build_options()
                plan = self.make_plan(root, options)
                expected = StringIO()
                with redirect_stdout(expected):
                    if get_next:
                        print(plan.new_version)
                    else:
                        print_bump_plan(plan)
                with captured_console(48) as (output, _, _, stack):
                    # Keep the actual engine renderer/run route; mock computation only.
                    stack.enter_context(patch("git_tools.generators.bumpgen.generator.run_bump", wraps=run_bump))
                    stack.enter_context(patch("git_tools.generators.bumpgen.engine.plan_bump", return_value=plan))
                    stack.enter_context(patch("git_tools.generators.bumpgen.engine._compute_bump", return_value=(plan.config, plan.new_version, plan.increment)))
                    generator.generate_bump(cwd=root)
                self.assertEqual(output.getvalue(), expected.getvalue())
                if get_next:
                    self.assertEqual(output.getvalue(), "0.1.1\n")

    def test_stdlib_only_entry_and_fallback_panel(self):
        source_root = Path(__file__).resolve().parents[1]
        code = (
            "from git_tools.generators.bumpgen.ui import print_panel\n"
            "from git_tools.generators.bumpgen.cli import build_parser\n"
            "print_panel(' body ', title='Title')\n"
            "assert build_parser().parse_args(['--get-next']).get_next\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-S", "-c", code], cwd=tmp,
                env={**os.environ, "PYTHONPATH": str(source_root), "PYTHONDONTWRITEBYTECODE": "1"},
                text=True, capture_output=True, check=True,
            )
        self.assertEqual(result.stdout, "Title\nbody\n\n")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()

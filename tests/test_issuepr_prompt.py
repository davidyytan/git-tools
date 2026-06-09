from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from git_tools.generators.issueprgen import (
    IssuePullRequestGenerator,
    PromotionPrContext,
    WorkflowPrContext,
)


class IssuePullRequestPromptTests(unittest.TestCase):
    def test_process_diff_with_size_limiting_handles_empty_diff(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        diff, quota_breakdown = generator._process_diff_with_size_limiting("", 200000)

        self.assertEqual(diff, "")
        self.assertEqual(quota_breakdown, [])

    def test_get_commit_messages_preserves_multi_paragraph_commit_bodies(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        raw_messages = (
            "feat: first change\n\n"
            "First paragraph.\n\n"
            "Second paragraph.\x1e"
            "fix: second change\n\n"
            "- bullet one\n\n"
            "- bullet two\x1e"
        )

        with patch(
            "git_tools.generators.issueprgen.subprocess.check_output",
            return_value=raw_messages,
        ) as check_output:
            messages = generator.get_commit_messages(2)

        self.assertEqual(
            messages,
            (
                "feat: first change\n\n"
                "First paragraph.\n\n"
                "Second paragraph.\n\n"
                "fix: second change\n\n"
                "- bullet one\n\n"
                "- bullet two"
            ),
        )
        self.assertEqual(
            check_output.call_args.args[0],
            ["git", "log", "-2", "--pretty=format:%B%x1e"],
        )

    def test_load_version_from_ref_reads_only_dot_cz_toml(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch(
            "git_tools.generators.issueprgen.subprocess.check_output",
            return_value="[tool.commitizen]\nversion = \"1.6.0\"\n",
        ) as check_output:
            version = generator._load_version_from_ref("origin/develop")

        self.assertEqual(version, "1.6.0")
        self.assertEqual(
            check_output.call_args.args[0],
            ["git", "show", "origin/develop:.cz.toml"],
        )

    def test_pr_commit_log_prefers_origin_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        def fake_run(*args, **kwargs):
            cmd = args[0]
            ref = cmd[-1]
            if ref == "origin/develop":
                return subprocess.CompletedProcess(cmd, 0)
            raise subprocess.CalledProcessError(1, cmd)

        with patch(
            "git_tools.generators.issueprgen.subprocess.run",
            side_effect=fake_run,
        ), patch(
            "git_tools.generators.issueprgen.subprocess.check_output",
            return_value="## abc123 feat: test\n",
        ) as check_output:
            commit_log = generator.get_pr_commit_log("develop")

        self.assertEqual(commit_log, "## abc123 feat: test")
        self.assertEqual(
            check_output.call_args.args[0][-1],
            "origin/develop..HEAD",
        )

    def test_release_pr_commit_log_uses_title_only_format(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        def fake_run(*args, **kwargs):
            cmd = args[0]
            ref = cmd[-1]
            if ref == "origin/master":
                return subprocess.CompletedProcess(cmd, 0)
            raise subprocess.CalledProcessError(1, cmd)

        with patch(
            "git_tools.generators.issueprgen.subprocess.run",
            side_effect=fake_run,
        ), patch(
            "git_tools.generators.issueprgen.subprocess.check_output",
            return_value="## abc123 feat: test\n\n## def456 fix: next\n",
        ) as check_output:
            commit_log = generator.get_pr_commit_log("master")

        self.assertEqual(commit_log, "## abc123 feat: test\n\n## def456 fix: next")
        self.assertIn("--pretty=format:## %h %s%n%n", check_output.call_args.args[0])
        self.assertNotIn("%b", check_output.call_args.args[0][4])
        self.assertEqual(
            check_output.call_args.args[0][-1],
            "origin/master..HEAD",
        )

    def test_pr_system_message_requires_conventional_commit_title(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        system_message = generator._build_system_message("", "b")

        self.assertIn("must be a valid Conventional Commit header", system_message)
        self.assertIn("must be exactly one Conventional Commit header line", system_message)
        self.assertIn("`style`", system_message)
        self.assertIn("Prefer `style` for formatting-only or text-only changes", system_message)
        self.assertIn("Prefer `chore` for maintenance or operational changes", system_message)
        self.assertIn("feat(auth): add SSO login", system_message)
        self.assertIn("fix(cli): handle empty staged diff", system_message)
        self.assertIn("style: add line to abc.txt", system_message)

    def test_release_pr_system_message_uses_release_title_guidance(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.6.0",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Release 1.6.0", system_message)
        self.assertIn("Release 1.6.0", system_message)
        self.assertIn("frame the PR as a release promotion", system_message)
        self.assertNotIn("Promote release/1.6.0 to master", system_message)
        self.assertNotIn("develop -> master", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_start_pr_system_message_uses_start_title_guidance(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            start_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_infer_start_target_version",
            return_value="1.7.0",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Start 1.7.0", system_message)
        self.assertIn("Treat the body like a normal develop PR", system_message)
        self.assertIn("opens the named alpha line on `develop`", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_hotfix_pr_system_message_uses_hotfix_title_guidance(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_default_release_base_branch",
            return_value="master",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="1.0.0",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Hotfix 1.0.1", system_message)
        self.assertIn("Hotfix 1.0.1", system_message)
        self.assertIn("frame the PR as a hotfix promotion", system_message)
        self.assertNotIn("Promote hotfix/", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_backmerge_release_pr_system_message_uses_backmerge_release_title_guidance(
        self,
    ) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            backmerge_release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.6.0",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Backmerge Release 1.6.0", system_message)
        self.assertIn("syncing release fixes back into `develop`", system_message)
        self.assertIn("if `develop` is already ahead", system_message)
        self.assertIn("catch `develop` up to the target stable version without tagging", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_backmerge_hotfix_pr_system_message_uses_backmerge_hotfix_title_guidance(
        self,
    ) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            backmerge_hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_infer_hotfix_target_version",
            return_value="1.6.1",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Backmerge Hotfix 1.6.1", system_message)
        self.assertIn("syncing hotfix fixes back into `develop`", system_message)
        self.assertIn("if `develop` is already ahead", system_message)
        self.assertIn("catch `develop` up to the target stable version without tagging", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_issue_system_message_keeps_descriptive_title_guidance(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="issue", interactive=False)

        system_message = generator._build_system_message("", "b")

        self.assertIn("keep `## Title:` short, descriptive, and human-readable", system_message)
        self.assertIn("Do not force Issue titles into Conventional Commit format.", system_message)

    def test_pr_output_normalization_overwrites_fixed_title_and_removes_issue_section(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        raw = """
## Title: Something Else

## Related Issue
Issue: #123

## Change Overview
### Overview
- text
""".strip()

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.6.0",
        ):
            normalized = generator._normalize_pr_output(raw)

        self.assertIn("## Title: Release 1.6.0", normalized)
        self.assertNotIn("Something Else", normalized)
        self.assertNotIn("## Related Issue", normalized)
        self.assertNotIn("Issue: #123", normalized)

    def test_interactive_release_pr_prompt_defaults_to_ordinary_mode(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)

        with patch.object(
            generator,
            "prompt_select",
            return_value="Ordinary PR",
        ) as prompt_select:
            generator.resolve_pr_mode()

        self.assertFalse(generator.release_pr)
        prompt_select.assert_called_once_with(
            "Select PR mode",
            [
                "Ordinary PR",
                "Start PR",
                "Release PR",
                "Hotfix PR",
                "Backmerge Release PR",
                "Backmerge Hotfix PR",
            ],
            default="Ordinary PR",
        )

    def test_release_pr_prefers_master_as_default_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_default_release_base_branch",
            return_value="master",
        ) as release_base, patch.object(
            generator,
            "_auto_detect_base_branch",
        ) as auto_detect:
            base_branch = generator.get_default_branch()

        self.assertEqual(base_branch, "master")
        release_base.assert_called_once_with()
        auto_detect.assert_not_called()

    def test_start_pr_prefers_develop_as_default_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            start_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_default_develop_base_branch",
            return_value="develop",
        ) as develop_base, patch.object(
            generator,
            "_auto_detect_base_branch",
        ) as auto_detect:
            base_branch = generator.get_default_branch()

        self.assertEqual(base_branch, "develop")
        develop_base.assert_called_once_with()
        auto_detect.assert_not_called()

    def test_hotfix_pr_prefers_master_as_default_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_default_release_base_branch",
            return_value="master",
        ) as hotfix_base, patch.object(
            generator,
            "_auto_detect_base_branch",
        ) as auto_detect:
            base_branch = generator.get_default_branch()

        self.assertEqual(base_branch, "master")
        hotfix_base.assert_called_once_with()
        auto_detect.assert_not_called()

    def test_release_pr_context_supports_classic_release_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.0.0",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="0.1.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="1.0.0-rc.0",
        ):
            context = generator._resolve_release_pr_context("master")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.target_version, "1.0.0")
        self.assertEqual(
            context.target_source,
            "current branch prerelease line and release branch name",
        )
        self.assertEqual(context.base_version, "0.1.0")
        self.assertEqual(context.current_version, "1.0.0-rc.0")
        self.assertEqual(context.inferred_transition, "MAJOR")

    def test_release_pr_context_supports_variant_release_branch_target(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.0.0",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="0.1.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="0.1.1-alpha.0",
        ):
            context = generator._resolve_release_pr_context("master")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.target_version, "1.0.0")
        self.assertEqual(context.target_source, "release branch name")
        self.assertEqual(context.inferred_transition, "MAJOR")

    def test_release_pr_context_rejects_invalid_branch_target(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="release/1.0.1",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="0.1.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="0.1.1-alpha.0",
        ):
            with self.assertRaises(ValueError):
                generator._resolve_release_pr_context("master")

    def test_release_pr_context_rejects_non_release_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="develop",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="0.1.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="1.0.0-alpha.3",
        ):
            with self.assertRaises(ValueError):
                generator._resolve_release_pr_context("master")

    def test_hotfix_pr_context_supports_next_patch_target(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="hotfix/auth-token-expiry",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="1.0.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="1.0.1-rc.0",
        ):
            context = generator._resolve_hotfix_pr_context("master")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.target_version, "1.0.1")
        self.assertEqual(
            context.target_source,
            "current branch prerelease line and next patch from base branch version",
        )
        self.assertEqual(context.inferred_transition, "PATCH")
        self.assertEqual(context.promotion_kind, "hotfix")

    def test_hotfix_pr_context_rejects_invalid_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="develop",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="1.0.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="1.0.1-rc.0",
        ):
            with self.assertRaises(ValueError):
                generator._resolve_hotfix_pr_context("master")

    def test_hotfix_pr_context_rejects_wrong_version_line(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            hotfix_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="hotfix/auth-token-expiry",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="1.0.0",
        ), patch.object(
            generator,
            "_load_current_branch_version",
            return_value="1.1.0-rc.0",
        ):
            with self.assertRaises(ValueError):
                generator._resolve_hotfix_pr_context("master")

    def test_start_pr_context_rejects_non_develop_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            start_pr=True,
            interactive=False,
        )

        with self.assertRaises(ValueError):
            generator._resolve_start_pr_context("master")

    def test_backmerge_release_pr_context_rejects_non_develop_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            backmerge_release_pr=True,
            interactive=False,
        )

        with self.assertRaises(ValueError):
            generator._resolve_backmerge_release_pr_context("master")

    def test_backmerge_hotfix_pr_context_rejects_non_develop_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            backmerge_hotfix_pr=True,
            interactive=False,
        )

        with self.assertRaises(ValueError):
            generator._resolve_backmerge_hotfix_pr_context("master")

    def test_release_pr_can_generate_from_release_context_without_commits(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            interactive=False,
        )
        release_context = PromotionPrContext(
            current_branch="release/1.0.0",
            base_branch="master",
            target_version="1.0.0",
            target_source="release branch name",
            base_version="0.1.0",
            current_version="1.0.0-rc.0",
            inferred_transition="MAJOR",
            promotion_kind="release",
        )

        with patch.object(
            generator,
            "get_default_branch",
            return_value="master",
        ), patch.object(
            generator,
            "_resolve_release_pr_context",
            return_value=release_context,
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=None,
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=False,
        ), patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        full_prompt = copy_to_clipboard_auto.call_args[0][0]
        self.assertIn("Promotion PR Context", full_prompt)
        self.assertIn("Target version for this promotion PR: 1.0.0", full_prompt)
        self.assertIn("Inferred transition from base branch to target version: MAJOR", full_prompt)

    def test_start_pr_can_generate_from_workflow_context_without_commits(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            start_pr=True,
            interactive=False,
        )
        workflow_context = WorkflowPrContext(
            workflow_kind="develop-start",
            current_branch="feature/open-next-cycle",
            base_branch="develop",
            fixed_title="Start 1.7.0",
            target_version="1.7.0",
            target_source="repo version state and current branch context",
            base_version="1.6.0",
            current_version="1.6.0",
            behavior_summary="Merging this PR should open 1.7.0-alpha.0 on develop.",
        )

        with patch.object(
            generator,
            "get_default_branch",
            return_value="develop",
        ), patch.object(
            generator,
            "_resolve_start_pr_context",
            return_value=workflow_context,
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=None,
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=False,
        ), patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        full_prompt = copy_to_clipboard_auto.call_args[0][0]
        self.assertIn("Workflow PR Context", full_prompt)
        self.assertIn("Fixed PR title for this workflow PR: Start 1.7.0", full_prompt)
        self.assertIn("Target version tuple for this workflow PR: 1.7.0", full_prompt)

    def test_pr_generation_appends_commit_log_to_parsed_output(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            input_source="c",
            interactive=False,
        )
        commit_info = {
            "base_branch": "develop",
            "commit_count": 2,
            "first_hash": "abc1234",
            "first_message": "feat: first",
            "last_hash": "def5678",
            "last_message": "fix: second",
        }
        response = {
            "content": "\n## Title: feat(cli): append commit log\n\n## Summary\nBody\n",
        }

        with patch.object(
            generator,
            "get_default_branch",
            return_value="develop",
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=commit_info,
        ), patch.object(
            generator,
            "show_commit_summary",
        ), patch.object(
            generator,
            "get_commit_messages",
            return_value="feat: first\n\nfix: second",
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=True,
        ), patch.object(
            generator,
            "select_model_params",
            return_value=("test-model", 0.0, 1000),
        ), patch.object(
            generator,
            "_initialize_service",
            return_value=True,
        ), patch.object(
            generator,
            "generate_content",
            return_value=response,
        ), patch.object(
            generator,
            "display_reasoning",
        ), patch.object(
            generator,
            "display_token_usage",
        ), patch.object(
            generator,
            "get_pr_commit_log",
            return_value="## abc123 feat: first\n\nbody",
        ), patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        copied = copy_to_clipboard_auto.call_args[0][0]
        self.assertIn("## Title: feat(cli): append commit log", copied)
        self.assertIn("## Commits\n```sh\n## abc123 feat: first\n\nbody\n```", copied)
        self.assertNotIn("Raw Response", copied)

    def test_release_pr_generation_appends_title_only_commit_log(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            input_source="c",
            interactive=False,
        )
        release_context = PromotionPrContext(
            current_branch="release/1.0.0",
            base_branch="master",
            target_version="1.0.0",
            target_source="release branch name",
            base_version="0.1.0",
            current_version="1.0.0-rc.0",
            inferred_transition="MAJOR",
            promotion_kind="release",
        )
        commit_info = {
            "base_branch": "master",
            "commit_count": 2,
            "first_hash": "abc1234",
            "first_message": "fix: first",
            "last_hash": "def5678",
            "last_message": "fix: second",
        }
        response = {
            "content": "\n## Title: Release 1.0.0\n\n## Change Overview\nBody\n",
        }

        with patch.object(
            generator,
            "get_default_branch",
            return_value="master",
        ), patch.object(
            generator,
            "_resolve_release_pr_context",
            return_value=release_context,
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=commit_info,
        ), patch.object(
            generator,
            "show_commit_summary",
        ), patch.object(
            generator,
            "get_commit_messages",
            return_value="fix: first\n\nfix: second",
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=True,
        ), patch.object(
            generator,
            "select_model_params",
            return_value=("test-model", 0.0, 1000),
        ), patch.object(
            generator,
            "_initialize_service",
            return_value=True,
        ), patch.object(
            generator,
            "generate_content",
            return_value=response,
        ), patch.object(
            generator,
            "display_reasoning",
        ), patch.object(
            generator,
            "display_token_usage",
        ), patch.object(
            generator,
            "get_pr_commit_log",
            return_value="## abc123 fix: first\n\n## def567 fix: second",
        ) as get_pr_commit_log, patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        copied = copy_to_clipboard_auto.call_args[0][0]
        self.assertIn("## Title: Release 1.0.0", copied)
        self.assertIn("## Change Overview", copied)
        self.assertIn(
            "## Commits\n```sh\n## abc123 fix: first\n\n## def567 fix: second\n```",
            copied,
        )
        get_pr_commit_log.assert_called_once_with("master")

    def test_pr_generation_with_both_input_falls_back_to_commit_messages_when_diff_is_empty(
        self,
    ) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            input_source="b",
            interactive=False,
        )
        commit_info = {
            "base_branch": "develop",
            "commit_count": 1,
            "first_hash": "abc1234",
            "first_message": "chore: open release",
            "last_hash": "abc1234",
            "last_message": "chore: open release",
        }
        response = {
            "content": "WRAPPER\n## Title: Backmerge Release 0.2.0\n\nBody\nEND",
        }

        with patch.object(
            generator,
            "get_default_branch",
            return_value="develop",
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=commit_info,
        ), patch.object(
            generator,
            "show_commit_summary",
        ), patch.object(
            generator,
            "get_commit_messages",
            return_value="chore: open release",
        ), patch.object(
            generator,
            "get_branch_diffs",
            return_value=("", []),
        ), patch(
            "git_tools.generators.issueprgen.warning",
        ) as warning_mock, patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=True,
        ), patch.object(
            generator,
            "select_model_params",
            return_value=("test-model", 0.0, 1000),
        ), patch.object(
            generator,
            "_initialize_service",
            return_value=True,
        ), patch.object(
            generator,
            "generate_content",
            return_value=response,
        ) as generate_content, patch.object(
            generator,
            "display_reasoning",
        ), patch.object(
            generator,
            "display_token_usage",
        ), patch.object(
            generator,
            "get_pr_commit_log",
            return_value=None,
        ), patch.object(
            generator,
            "display_quota_breakdown",
        ) as display_quota_breakdown, patch.object(
            generator,
            "copy_to_clipboard_auto",
        ):
            generator.generate_issue_pullrequest()

        content_arg = generate_content.call_args.args[0]
        self.assertIn("Commit Messages:", content_arg)
        self.assertNotIn("Code Diffs:", content_arg)
        warning_mock.assert_any_call(
            "No code diffs found for this range; using commit messages only."
        )
        display_quota_breakdown.assert_not_called()

    def test_pr_generation_falls_back_to_raw_output_and_appends_commit_log(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            input_source="c",
            interactive=False,
        )
        commit_info = {
            "base_branch": "develop",
            "commit_count": 1,
            "first_hash": "abc1234",
            "first_message": "feat: first",
            "last_hash": "abc1234",
            "last_message": "feat: first",
        }
        response = {
            "content": "## Title: raw fallback\n\nRaw body",
        }

        with patch.object(
            generator,
            "get_default_branch",
            return_value="develop",
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=commit_info,
        ), patch.object(
            generator,
            "show_commit_summary",
        ), patch.object(
            generator,
            "get_commit_messages",
            return_value="feat: first",
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=True,
        ), patch.object(
            generator,
            "select_model_params",
            return_value=("test-model", 0.0, 1000),
        ), patch.object(
            generator,
            "_initialize_service",
            return_value=True,
        ), patch.object(
            generator,
            "generate_content",
            return_value=response,
        ), patch.object(
            generator,
            "parse_generated_content",
            return_value="",
        ), patch.object(
            generator,
            "display_reasoning",
        ), patch.object(
            generator,
            "display_token_usage",
        ), patch.object(
            generator,
            "get_pr_commit_log",
            return_value="## abc123 feat: first",
        ), patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        copied = copy_to_clipboard_auto.call_args[0][0]
        self.assertTrue(copied.startswith("## Title: raw fallback"))
        self.assertIn("Raw body", copied)
        self.assertIn("## Commits\n```sh\n## abc123 feat: first\n```", copied)

    def test_issue_generation_keeps_existing_raw_copy_behavior(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="issue",
            input_source="c",
            interactive=False,
        )
        commit_info = {
            "base_branch": "develop",
            "commit_count": 1,
            "first_hash": "abc1234",
            "first_message": "feat: first",
            "last_hash": "abc1234",
            "last_message": "feat: first",
        }
        response = {
            "content": "WRAPPER\n## Title: issue title\n\nIssue body\nEND",
        }

        with patch.object(
            generator,
            "get_default_branch",
            return_value="develop",
        ), patch.object(
            generator,
            "get_commit_info",
            return_value=commit_info,
        ), patch.object(
            generator,
            "show_commit_summary",
        ), patch.object(
            generator,
            "get_commit_messages",
            return_value="feat: first",
        ), patch.object(
            generator,
            "select_provider",
            return_value="openrouter",
        ), patch.object(
            generator,
            "ensure_api_key_configured",
            return_value=True,
        ), patch.object(
            generator,
            "select_model_params",
            return_value=("test-model", 0.0, 1000),
        ), patch.object(
            generator,
            "_initialize_service",
            return_value=True,
        ), patch.object(
            generator,
            "generate_content",
            return_value=response,
        ), patch.object(
            generator,
            "display_reasoning",
        ), patch.object(
            generator,
            "display_token_usage",
        ), patch.object(
            generator,
            "copy_to_clipboard_auto",
        ) as copy_to_clipboard_auto:
            generator.generate_issue_pullrequest()

        copied = copy_to_clipboard_auto.call_args[0][0]
        self.assertEqual(copied, response["content"])


if __name__ == "__main__":
    unittest.main()

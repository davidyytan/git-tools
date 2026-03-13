from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.generators.issueprgen import IssuePullRequestGenerator, PromotionPrContext


class IssuePullRequestPromptTests(unittest.TestCase):
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

    def test_sync_pr_system_message_uses_sync_title_guidance(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            sync_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="sync/back-to-develop",
        ), patch.object(
            generator,
            "_default_release_base_branch",
            return_value="master",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value="1.6.0",
        ):
            system_message = generator._build_system_message("", "b")

        self.assertIn("The Pull Request title is fixed for this mode.", system_message)
        self.assertIn("## Title: Sync 1.6.0", system_message)
        self.assertIn("`sync/* -> develop`", system_message)
        self.assertIn("Sync 1.6.0", system_message)
        self.assertIn("frame the PR as branch synchronization", system_message)
        self.assertNotIn("Issue: #[number]", system_message)

    def test_sync_pr_title_block_uses_fixed_placeholder_when_version_is_unavailable(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            sync_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_get_current_branch_name",
            return_value="sync/back-to-develop",
        ), patch.object(
            generator,
            "_load_version_from_ref",
            return_value=None,
        ):
            title_block = generator._build_pr_title_block()

        self.assertEqual(title_block, "## Title: Sync <x.y.z>")

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

    def test_interactive_release_pr_prompt_defaults_to_develop_mode(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)

        with patch.object(
            generator,
            "prompt_select",
            return_value="Develop PR",
        ) as prompt_select:
            generator.resolve_pr_mode()

        self.assertFalse(generator.release_pr)
        prompt_select.assert_called_once_with(
            "Select PR mode",
            ["Develop PR", "Release PR", "Hotfix PR", "Sync PR"],
            default="Develop PR",
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

    def test_sync_pr_prefers_develop_as_default_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            sync_pr=True,
            interactive=False,
        )

        with patch.object(
            generator,
            "_default_sync_base_branch",
            return_value="develop",
        ) as sync_base, patch.object(
            generator,
            "_auto_detect_base_branch",
        ) as auto_detect:
            base_branch = generator.get_default_branch()

        self.assertEqual(base_branch, "develop")
        sync_base.assert_called_once_with()
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import subprocess
import unittest
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

from git_tools.generators.issueprgen import (
    AZURE_PR_DESCRIPTION_INSTRUCTION,
    IssuePullRequestGenerator,
    PromotionPrContext,
    WorkflowPrContext,
    count_ado_chars,
)
from test_user_prompt_wrapping import assert_user_envelope, request_text


class IssuePullRequestPromptTests(unittest.TestCase):
    def setUp(self):
        self.save = patch("git_tools.generators.issueprgen.generator.save_draft", return_value=None)
        self.save.start()
        self.addCleanup(self.save.stop)

    def test_document_specific_formatting_keeps_numbering_for_pr_overviews(self) -> None:
        with contextlib.ExitStack() as stack:
            forbidden = []
            for target in ("subprocess.run", "subprocess.check_output", "socket.socket.connect", "socket.create_connection", "pyperclip.copy"):
                forbidden.append(stack.enter_context(patch(target, side_effect=AssertionError(f"Prompt assembly attempted {target}"))))
            forbidden.append(stack.enter_context(patch.object(IssuePullRequestGenerator, "invoke_llm", side_effect=AssertionError("Prompt assembly called an LLM"))))
            for kind in ("pr", "issue", "both"):
                generator = IssuePullRequestGenerator(generation_type=kind, interactive=False)
                for source in ("d", "c", "b"):
                    with self.subTest(kind=kind, source=source):
                        prompt = generator._build_system_message("Sample input", source)
                        self.assertNotIn("{document_rules}", prompt)
                        self.assertNotIn("{generation_type_instruction}", prompt)
                        self.assertNotIn("{template_content}", prompt)
                        self.assertNotIn("{title_instruction}", prompt)
                        self.assertNotIn("{focus_instruction}", prompt)
                        self.assertNotIn("In `Problem Statement`, use Markdown numbered lists", prompt)
                        self.assertNotIn("Apply numbered-list formatting only to the high-level content", prompt)
                        if kind in ("pr", "both"):
                            self.assertIn("write the main `Overview` as a Markdown numbered list", prompt)
                            self.assertIn("Do not add a `## Related Issue` section", prompt)
                        else:
                            self.assertNotIn("Pull Request", prompt)
                            self.assertNotIn("`Change Overview`", prompt)
                        if kind in ("issue", "both"):
                            self.assertIn("use concise paragraphs or unordered bullets rather than numbered lists", prompt)
                            self.assertIn("Use ordered steps only for genuinely sequential instructions", prompt)
                        else:
                            self.assertNotIn("Issue writing rules:", prompt)
                            self.assertNotIn("Issue Template:", prompt)
                            self.assertNotIn("`Problem Statement`", prompt)
            for action in forbidden:
                action.assert_not_called()

    def test_user_requests_are_task_specific_and_only_the_selected_file_is_loaded(self) -> None:
        tasks = {
            "pr": "Write the complete pull request in your next reply, without an outer wrapper or introductory text.",
            "issue": "Write the complete issue in your next reply, without an outer wrapper or introductory text.",
            "both": "Write the complete pull request followed by the issue in your next reply, without an outer wrapper or introductory text.",
        }
        for kind, task in tasks.items():
            with self.subTest(kind=kind):
                generator = IssuePullRequestGenerator(generation_type=kind, interactive=False)
                with patch.object(generator, "_load_prompt_template", wraps=generator._load_prompt_template) as load:
                    prompt = generator._build_full_prompt("Sample input")
                root = assert_user_envelope(self, prompt, task)
                self.assertEqual(root.tag, "sources")
                self.assertEqual([node.tag for node in root], ["evidence"])
                self.assertEqual(request_text(prompt), task)
                self.assertEqual(prompt, "<evidence>Sample input</evidence>\n\n" + task)
                self.assertEqual(root.findtext("evidence"), "Sample input")
                self.assertFalse((root.text or "").strip())
                self.assertTrue(all(not (node.tail or "").strip() for node in root))
                self.assertTrue(all(len(node) == 0 for node in root))
                load.assert_called_once_with(f"issuepr_user_prompt_{kind}.txt")

    def test_system_prompt_selection_uses_current_mode_not_constructor_default(self) -> None:
        generator = IssuePullRequestGenerator(interactive=False)
        prefixes = {
            "pr": "Task: Write a review-ready Pull Request",
            "issue": "Task: Write an Issue",
            "both": "Task: Write a coordinated Pull Request and Issue",
        }
        for kind in ("pr", "both", "issue"):
            with self.subTest(kind=kind):
                generator.generation_type = kind
                with patch.object(generator, "_load_prompt_template", wraps=generator._load_prompt_template) as load:
                    prompt = generator._build_system_message("Sample input", "b")
                root = ET.fromstring(prompt)
                self.assertTrue(root.findtext("rules").startswith(prefixes[kind]))
                self.assertEqual([node.attrib["kind"] for node in root.findall("template")], ["pr", "issue"] if kind == "both" else [kind])
                generation_files = [call.args[0] for call in load.call_args_list if call.args[0].startswith("issuepr_generation_")]
                self.assertEqual(generation_files, [f"issuepr_generation_{kind}.txt"])
        generator.generation_type = "other"
        with self.assertRaisesRegex(ValueError, "Unsupported generation type"):
            generator._build_system_message("Sample input", "b")

    def test_issue_assembly_does_not_consult_pr_template_or_title_helpers(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="issue", interactive=False)
        with contextlib.ExitStack() as stack:
            helpers = []
            for name in ("_build_pr_template", "_build_pr_title_instruction", "_build_both_title_instruction"):
                helpers.append(stack.enter_context(patch.object(generator, name, side_effect=AssertionError(f"Issue assembly used {name}"))))
            prompt = generator._build_system_message("Sample input", "d")
            self.assertIn("Issue writing rules:", prompt)
            for helper in helpers:
                helper.assert_not_called()

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
            "subprocess.check_output",
            return_value=raw_messages,
        ) as check_output:
            messages = generator.get_commit_messages({"commit_range": "base-sha..head-sha"})

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
            ["git", "log", "--pretty=format:%B%x1e", "base-sha..head-sha", "--"],
        )

    def test_load_version_from_ref_reads_only_dot_cz_toml(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch(
            "subprocess.check_output",
            return_value="[tool.commitizen]\nversion = \"1.6.0\"\n",
        ) as check_output:
            version = generator._load_version_from_ref("origin/develop")

        self.assertEqual(version, "1.6.0")
        self.assertEqual(
            check_output.call_args.args[0],
            ["git", "show", "origin/develop:.cz.toml"],
        )

    def test_pr_commit_log_uses_resolved_remote_only_base_branch(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        def fake_run(*args, **kwargs):
            cmd = args[0]
            ref = cmd[-1].removesuffix("^{commit}")
            if ref in {"origin/develop", "refs/remotes/origin/develop"}:
                return subprocess.CompletedProcess(cmd, 0, stdout="base-sha\n")
            raise subprocess.CalledProcessError(1, cmd)

        with patch(
            "subprocess.run",
            side_effect=fake_run,
        ), patch(
            "subprocess.check_output",
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
            ref = cmd[-1].removesuffix("^{commit}")
            if ref in {"origin/master", "refs/remotes/origin/master"}:
                return subprocess.CompletedProcess(cmd, 0, stdout="base-sha\n")
            raise subprocess.CalledProcessError(1, cmd)

        with patch(
            "subprocess.run",
            side_effect=fake_run,
        ), patch(
            "subprocess.check_output",
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
        self.assertIn("Prefer `style` for formatting-only or generic text-only changes outside documentation", system_message)
        self.assertIn("Prefer `chore` for maintenance, repo housekeeping, or release metadata changes not covered by a more specific type", system_message)
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
            workflow_version="1.6.1",
            interactive=False,
        )

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
            copy_clipboard=True,
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
            copy_clipboard=True,
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

    def test_pr_generation_does_not_append_commit_log(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            input_source="c",
            interactive=False,
            copy_clipboard=True,
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
        self.assertNotIn("## Commits", copied)
        self.assertNotIn("Raw Response", copied)

    def test_release_pr_generation_does_not_append_commit_log(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            release_pr=True,
            input_source="c",
            interactive=False,
            copy_clipboard=True,
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
        self.assertNotIn("## Commits", copied)
        get_pr_commit_log.assert_not_called()

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
            "git_tools.generators.issueprgen.content.warning",
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
        prompt = generator._build_full_prompt(content_arg)
        request = generator._load_prompt_template("issuepr_user_prompt_pr.txt").strip()
        root = assert_user_envelope(self, prompt, request)
        self.assertEqual(root.tag, "sources")
        self.assertEqual(request_text(prompt), request)
        self.assertEqual(root.find("commit_messages").get("boundaries"), "unknown")
        self.assertEqual(root.findtext("commit_messages/commit_group"), "chore: open release")
        self.assertEqual(root.findall("diffs"), [])
        self.assertEqual(root.findall("evidence"), [])
        self.assertFalse((root.text or "").strip())
        self.assertTrue(all(not (node.tail or "").strip() for node in root))
        warning_mock.assert_any_call(
            "No code diffs found for this range; using commit messages only."
        )
        display_quota_breakdown.assert_not_called()

    def test_pr_generation_falls_back_to_raw_output_without_commit_log(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr",
            input_source="c",
            interactive=False,
            copy_clipboard=True,
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
        self.assertNotIn("## Commits", copied)

    def test_issue_generation_keeps_existing_raw_copy_behavior(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="issue",
            input_source="c",
            interactive=False,
            copy_clipboard=True,
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


class AzurePrDescriptionLimitTests(unittest.TestCase):
    """Azure DevOps PR description limit: detection, counting, and flow."""

    def setUp(self):
        self.save = patch("git_tools.generators.issueprgen.generator.save_draft", return_value=None)
        self.save.start()
        self.addCleanup(self.save.stop)

    # -- count_ado_chars (UTF-16 code units) ---------------------------

    def test_count_ado_chars_counts_ascii_as_one_unit(self) -> None:
        self.assertEqual(count_ado_chars(""), 0)
        self.assertEqual(count_ado_chars("abc"), 3)
        self.assertEqual(count_ado_chars("a\nb"), 3)

    def test_count_ado_chars_counts_non_bmp_chars_as_two_units(self) -> None:
        self.assertEqual(count_ado_chars("\u00e9"), 1)
        self.assertEqual(count_ado_chars("\u4e2d"), 1)
        self.assertEqual(count_ado_chars("\U0001f600"), 2)
        self.assertEqual(count_ado_chars("a\U0001f600b"), 4)

    def test_count_ado_chars_boundary_at_4000(self) -> None:
        self.assertEqual(count_ado_chars("x" * 4000), 4000)
        self.assertEqual(count_ado_chars("x" * 4001), 4001)

    # -- Azure DevOps URL detection ------------------------------------

    def test_azure_devops_urls_are_detected(self) -> None:
        urls = [
            "https://dev.azure.com/org/project/_git/repo",
            "https://org@dev.azure.com/org/project/_git/repo",
            "https://org@dev.azure.com:443/org/project/_git/repo",
            "git@ssh.dev.azure.com:v3/org/project/repo",
            "ssh://git@ssh.dev.azure.com/v3/org/project/repo",
            "https://org.visualstudio.com/project/_git/repo",
            "https://DEV.AZURE.COM/org/project/_git/repo",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(IssuePullRequestGenerator._is_azure_devops_url(url))

    def test_non_azure_urls_are_not_detected(self) -> None:
        urls = [
            "",
            None,
            "   ",
            "not a url",
            "https://github.com/owner/repo",
            "git@github.com:owner/repo.git",
            "ssh://git@github.com/owner/repo.git",
            "https://gitlab.com/owner/repo",
            "https://dev.azure.com.evil.com/org/project/_git/repo",
            "https://evil.com/?host=dev.azure.com",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(IssuePullRequestGenerator._is_azure_devops_url(url))

    # -- Origin lookup --------------------------------------------------

    def test_get_origin_url_returns_trimmed_url(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch(
            "subprocess.check_output",
            return_value="https://dev.azure.com/org/proj/_git/repo\n",
        ) as check_output:
            origin_url = generator._get_origin_url()

        self.assertEqual(origin_url, "https://dev.azure.com/org/proj/_git/repo")
        self.assertEqual(
            check_output.call_args.args[0],
            ["git", "remote", "get-url", "origin"],
        )

    def test_get_origin_url_returns_none_when_git_fails(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch(
            "subprocess.check_output",
            side_effect=subprocess.CalledProcessError(128, ["git"]),
        ):
            self.assertIsNone(generator._get_origin_url())

    def test_get_origin_url_returns_none_when_output_is_empty(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)

        with patch(
            "subprocess.check_output",
            return_value="\n",
        ):
            self.assertIsNone(generator._get_origin_url())

    # -- Limit resolution: CLI param > interactive prompt > detection ---

    def test_cli_azure_limit_flag_overrides_detection_and_prompt(self) -> None:
        generator = IssuePullRequestGenerator(
            generation_type="pr", azure_limit=True, interactive=True
        )
        with patch.object(generator, "_get_origin_url") as get_origin, patch.object(
            generator, "prompt_confirm"
        ) as prompt_confirm:
            self.assertTrue(generator._should_apply_azure_limit())
        get_origin.assert_not_called()
        prompt_confirm.assert_not_called()

        generator = IssuePullRequestGenerator(
            generation_type="pr", azure_limit=False, interactive=True
        )
        with patch.object(generator, "_get_origin_url") as get_origin, patch.object(
            generator, "prompt_confirm"
        ) as prompt_confirm:
            self.assertFalse(generator._should_apply_azure_limit())
        get_origin.assert_not_called()
        prompt_confirm.assert_not_called()

    def test_non_interactive_mode_uses_detection_without_prompt(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        with patch.object(
            generator,
            "_get_origin_url",
            return_value="https://dev.azure.com/org/proj/_git/repo",
        ), patch.object(generator, "prompt_confirm") as prompt_confirm:
            self.assertTrue(generator._should_apply_azure_limit())
        prompt_confirm.assert_not_called()

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=False)
        with patch.object(
            generator,
            "_get_origin_url",
            return_value="https://github.com/owner/repo",
        ), patch.object(generator, "prompt_confirm") as prompt_confirm:
            self.assertFalse(generator._should_apply_azure_limit())
        prompt_confirm.assert_not_called()

    def test_interactive_saved_auto_applies_detection_without_prompt(self) -> None:
        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
        with patch.object(
            generator,
            "_get_origin_url",
            return_value="https://dev.azure.com/org/proj/_git/repo",
        ), patch.object(
            generator, "prompt_confirm", return_value=True
        ) as prompt_confirm:
            self.assertTrue(generator._should_apply_azure_limit())
        prompt_confirm.assert_not_called()

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
        with patch.object(
            generator,
            "_get_origin_url",
            return_value="https://github.com/owner/repo",
        ), patch.object(
            generator, "prompt_confirm", return_value=False
        ) as prompt_confirm:
            self.assertFalse(generator._should_apply_azure_limit())
        prompt_confirm.assert_not_called()

        generator = IssuePullRequestGenerator(generation_type="pr", interactive=True)
        with patch.object(generator, "_get_origin_url", return_value=None), patch.object(
            generator, "prompt_confirm", return_value=False
        ) as prompt_confirm:
            self.assertFalse(generator._should_apply_azure_limit())
        prompt_confirm.assert_not_called()

    def test_interactive_detection_prints_origin_remote_line(self) -> None:
        cases = [
            (
                "https://dev.azure.com/org/proj/_git/repo",
                "Origin remote: Azure DevOps repository",
            ),
            (
                "https://github.com/owner/repo",
                "Origin remote: Non-Azure DevOps repository",
            ),
            (None, "Origin remote: Not configured"),
        ]
        for origin_url, expected_message in cases:
            with self.subTest(origin_url=origin_url):
                generator = IssuePullRequestGenerator(
                    generation_type="pr", interactive=True
                )
                with patch.object(
                    generator, "_get_origin_url", return_value=origin_url
                ), patch.object(
                    generator, "prompt_confirm", return_value=True
                ), patch("git_tools.generators.issueprgen.azure.info") as info:
                    generator._should_apply_azure_limit()
                info.assert_called_once_with(expected_message)

    # -- Generation flow -------------------------------------------------

    def _make_generator(
        self,
        generation_type: str = "pr",
        azure_limit: bool | None = None,
    ) -> IssuePullRequestGenerator:
        return IssuePullRequestGenerator(
            generation_type=generation_type,
            input_source="c",
            azure_limit=azure_limit,
            interactive=False,
            copy_clipboard=True,
        )

    def _run_flow(self, generator, responses, apply_limit):
        commit_info = {
            "base_branch": "develop",
            "commit_count": 1,
            "first_hash": "abc1234",
            "first_message": "feat: first",
            "last_hash": "abc1234",
            "last_message": "feat: first",
        }
        mocks = {}
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(generator, "get_default_branch", return_value="develop")
            )
            stack.enter_context(
                patch.object(generator, "get_commit_info", return_value=commit_info)
            )
            stack.enter_context(patch.object(generator, "show_commit_summary"))
            stack.enter_context(
                patch.object(
                    generator, "get_commit_messages", return_value="feat: first"
                )
            )
            stack.enter_context(
                patch.object(generator, "select_provider", return_value="openrouter")
            )
            stack.enter_context(
                patch.object(generator, "ensure_api_key_configured", return_value=True)
            )
            stack.enter_context(
                patch.object(
                    generator,
                    "select_model_params",
                    return_value=("test-model", 0.0, 1000),
                )
            )
            stack.enter_context(
                patch.object(generator, "_initialize_service", return_value=True)
            )
            mocks["generate_content"] = stack.enter_context(
                patch.object(generator, "generate_content", side_effect=responses)
            )
            stack.enter_context(patch.object(generator, "display_reasoning"))
            stack.enter_context(patch.object(generator, "display_token_usage"))
            stack.enter_context(
                patch.object(
                    generator,
                    "get_pr_commit_log",
                    return_value="## abc123 feat: first",
                )
            )
            mocks["copy_to_clipboard_auto"] = stack.enter_context(
                patch.object(generator, "copy_to_clipboard_auto")
            )
            # The flow warns from several modules; one mock observes them all.
            mocks["warning"] = MagicMock()
            for module in ("azure", "content", "generator"):
                stack.enter_context(
                    patch(f"git_tools.generators.issueprgen.{module}.warning", mocks["warning"])
                )
            mocks["should_apply"] = stack.enter_context(
                patch.object(
                    generator, "_should_apply_azure_limit", return_value=apply_limit
                )
            )
            generator.generate_issue_pullrequest()
        return mocks

    def test_generation_omits_raw_response_panel_for_all_output_types(self) -> None:
        for generation_type, title in (
            ("issue", "Issue Description"),
            ("pr", "PR Description"),
            ("both", "Combined Output"),
        ):
            with self.subTest(generation_type=generation_type):
                generator = self._make_generator(generation_type=generation_type)
                response = {"content": "```\n## Title: fix: avoid duplicate output\n\nBody\n```"}
                with patch("git_tools.generators.issueprgen.generator.console") as console:
                    self._run_flow(generator, [response], apply_limit=False)

                titles = [
                    call.args[0].title
                    for call in console.print.call_args_list
                    if call.args and hasattr(call.args[0], "title")
                ]
                self.assertEqual(titles, [f"[bold]{title}[/bold]"])

    def test_enabled_limit_adds_instruction_to_system_message(self) -> None:
        generator = self._make_generator()
        response = {"content": "\n## Title: feat: small\n\nbody\n"}
        mocks = self._run_flow(generator, [response], apply_limit=True)

        system_msg = mocks["generate_content"].call_args[0][1]
        self.assertIn(AZURE_PR_DESCRIPTION_INSTRUCTION, system_msg)
        self.assertIn("4000 UTF-16 units", system_msg)
        self.assertEqual(mocks["generate_content"].call_count, 1)
        mocks["warning"].assert_not_called()

        copied = mocks["copy_to_clipboard_auto"].call_args[0][0]
        self.assertIn("## Title: feat: small", copied)
        self.assertNotIn("## Commits", copied)

    def test_over_limit_description_retries_once_and_uses_repair(self) -> None:
        generator = self._make_generator()
        over = "## Title: feat: big\n\n" + "x" * 4100
        repaired = "## Title: feat: big\n\ncondensed body"
        responses = [
            {"content": "\n" + over + "\n"},
            {"content": "\n" + repaired + "\n"},
        ]
        mocks = self._run_flow(generator, responses, apply_limit=True)

        self.assertEqual(mocks["generate_content"].call_count, 2)
        retry_system_msg = mocks["generate_content"].call_args_list[1][0][1]
        self.assertIn("Rewrite the PR description", retry_system_msg)
        self.assertNotIn("`## Title:` line exactly", retry_system_msg)
        self.assertIn("exceeding the configured PR limit", retry_system_msg)
        mocks["warning"].assert_not_called()

        copied = mocks["copy_to_clipboard_auto"].call_args[0][0]
        self.assertIn("## Title: feat: big", copied)
        self.assertIn("condensed body", copied)
        self.assertNotIn("## Commits", copied)

    def test_retry_still_over_limit_warns_and_copies_anyway(self) -> None:
        generator = self._make_generator()
        over_one = "## Title: feat: big\n\n" + "x" * 4100
        over_two = "## Title: feat: big\n\n" + "y" * 4200
        responses = [
            {"content": "\n" + over_one + "\n"},
            {"content": "\n" + over_two + "\n"},
        ]
        mocks = self._run_flow(generator, responses, apply_limit=True)

        self.assertEqual(mocks["generate_content"].call_count, 2)
        mocks["warning"].assert_called_once()
        warning_message = mocks["warning"].call_args[0][0]
        self.assertIn("exceeds the configured PR limit", warning_message)
        self.assertIn("Keeping the content without truncation", warning_message)

        copied = mocks["copy_to_clipboard_auto"].call_args[0][0]
        self.assertIn("y" * 100, copied)
        self.assertNotIn("## Commits", copied)

    def test_disabled_limit_keeps_single_generation_without_instruction(self) -> None:
        generator = self._make_generator()
        response = {"content": "\n## Title: feat: small\n\nbody\n"}
        mocks = self._run_flow(generator, [response], apply_limit=False)

        system_msg = mocks["generate_content"].call_args[0][1]
        self.assertNotIn(AZURE_PR_DESCRIPTION_INSTRUCTION, system_msg)
        self.assertEqual(mocks["generate_content"].call_count, 1)
        mocks["warning"].assert_not_called()

        copied = mocks["copy_to_clipboard_auto"].call_args[0][0]
        self.assertNotIn("## Commits", copied)

    def test_issue_generation_never_applies_azure_limit(self) -> None:
        generator = self._make_generator(generation_type="issue", azure_limit=True)
        over = "## Title: something\n\n" + "x" * 4100
        response = {"content": "\n" + over + "\n"}
        mocks = self._run_flow(generator, [response], apply_limit=True)

        mocks["should_apply"].assert_not_called()
        self.assertEqual(mocks["generate_content"].call_count, 1)
        system_msg = mocks["generate_content"].call_args[0][1]
        self.assertNotIn(AZURE_PR_DESCRIPTION_INSTRUCTION, system_msg)
        mocks["warning"].assert_not_called()


if __name__ == "__main__":
    unittest.main()

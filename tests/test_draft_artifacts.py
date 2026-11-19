"""Offline draft and direct-CLI regressions; no real providers, clipboard or commits."""

from contextlib import ExitStack, chdir, contextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import errno
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from typer.testing import CliRunner
from rich.console import Console

from git_tools.cli import app
from git_tools.generators.bumpgen.errors import GitError
from git_tools.generators.bumpgen.git import run_command
from git_tools.generators.commitgen import CommitGenerator
from git_tools.generators.base.display import DisplayMixin
from git_tools.generators.issueprgen import IssuePullRequestGenerator
from git_tools.generators.utils.artifacts import save_draft
from git_tools.navigation import NavigationBack


BODY = "## Title: feat: keep details\n\nRésumé 😀 [literal] :warning: :smile:\n\n```python\n  print('kept')  \n```\n\n" + "https://example.com/" + "x" * 300 + "\nLAST  "


@contextmanager
def issue_boundaries(response=None, *, credentials=True, initialize=True, interactive=False, copy=False, generation_type="pr"):
    generator = IssuePullRequestGenerator(generation_type=generation_type, context="", input_source="c", copy_clipboard=copy, interactive=interactive)
    with ExitStack() as stack:
        for name, value in (
            ("get_default_branch", "develop"),
            ("get_commit_info", {"base_branch": "develop", "commit_count": 1}),
            ("_collect_generation_content", ("c", "feat: real input")),
            ("select_provider", "openrouter"),
            ("ensure_api_key_configured", credentials),
            ("select_model_params", ("mock-model", 0.0, 1000)),
            ("_initialize_service", initialize),
            ("generate_content", response),
            ("_should_apply_azure_limit", False),
            ("prompt_confirm", True),
        ):
            stack.enter_context(patch.object(generator, name, return_value=value))
        for name in ("resolve_pr_mode", "show_commit_summary", "display_reasoning", "display_token_usage", "display_generation_settings"):
            stack.enter_context(patch.object(generator, name))
        clipboard = stack.enter_context(patch("pyperclip.copy"))
        stack.enter_context(patch("subprocess.run", side_effect=AssertionError("unexpected Git mutation")))
        stack.enter_context(patch("subprocess.check_output", side_effect=AssertionError("unexpected repository access")))
        yield generator, clipboard


class DraftWriterTests(unittest.TestCase):
    def test_names_exact_bytes_and_frozen_timestamp_collisions(self):
        frozen = datetime(2026, 11, 17, 15, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, patch("git_tools.generators.utils.artifacts.datetime") as clock:
            clock.now.return_value = frozen
            root = Path(tmp)
            for kind, stem in (("pr", "PR"), ("issue", "ISSUE"), ("both", "ISSUEPR"), ("commit", "COMMIT")):
                paths = [save_draft(BODY, kind, root) for _ in range(3)]
                self.assertEqual(paths[0].name, f"{stem}.md")
                self.assertEqual(paths[1].name, f"{stem}-20261117T150000000000Z.md")
                self.assertEqual(paths[2].name, f"{stem}-20261117T150000000000Z-2.md")
                for path in paths:
                    self.assertEqual(path.read_bytes(), (BODY + "\n").encode("utf-8"))
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_occupied_files_directories_and_symlinks_are_never_overwritten(self):
        for occupied in ("file", "directory", "symlink", "dangling"):
            with self.subTest(occupied=occupied), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                original = root / "PR.md"
                target = root / "original"
                target.write_text("untouched")
                if occupied == "file":
                    original.write_text("original PR")
                elif occupied == "directory":
                    original.mkdir()
                else:
                    original.symlink_to(target if occupied == "symlink" else root / "missing")
                path = save_draft(BODY, "pr", root)
                self.assertNotEqual(path, original)
                self.assertEqual(target.read_text(), "untouched")
                if occupied == "file":
                    self.assertEqual(original.read_text(), "original PR")
                elif occupied == "directory":
                    self.assertTrue(original.is_dir())
                else:
                    self.assertTrue(original.is_symlink())

    def test_exclusive_publication_race_selects_another_name(self):
        real_link = os.link
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = True
            def racing_link(source, destination, **kwargs):
                nonlocal first
                if first:
                    first = False
                    target = Path(destination)
                    if not target.is_absolute():
                        target = root / target
                    target.write_text("other process")
                return real_link(source, destination, **kwargs)
            with patch("git_tools.generators.utils.artifacts.os.link", side_effect=racing_link):
                path = save_draft(BODY, "pr", root)
            self.assertNotEqual(path.name, "PR.md")
            self.assertEqual((root / "PR.md").read_text(), "other process")

    def test_flush_failure_removes_only_new_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "PR.md").write_text("original")
            with patch("git_tools.generators.utils.artifacts.os.fsync", side_effect=OSError(errno.ENOSPC, "disk full")):
                with self.assertRaises(OSError):
                    save_draft(BODY, "pr", root)
            self.assertEqual([path.name for path in root.iterdir()], ["PR.md"])
            self.assertEqual((root / "PR.md").read_text(), "original")

    def test_failed_write_never_unlinks_a_replacement_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "PR.md"
            replacement = root / "replacement"
            replacement.write_text("OTHER PROCESS COMPLETE DRAFT")
            published = False
            native_stat = Path.lstat
            def publish():
                nonlocal published
                os.replace(replacement, target)
                published = True
            def fail_fsync(fd):
                # A staging writer has no public filename yet; the old writer exposed PR.md here.
                if not target.exists():
                    publish()
                raise OSError(errno.ENOSPC, "disk full")
            def race_after_stat(path, *args, **kwargs):
                identity = native_stat(path, *args, **kwargs)
                if path == target and not published:
                    publish()
                return identity
            with patch("git_tools.generators.utils.artifacts.os.fsync", side_effect=fail_fsync), patch.object(Path, "lstat", race_after_stat):
                with self.assertRaises(OSError):
                    save_draft(BODY, "pr", root)
            self.assertTrue(published)
            self.assertEqual(target.read_text(), "OTHER PROCESS COMPLETE DRAFT")
            self.assertEqual(list(root.iterdir()), [target])

    def test_draft_name_is_visible_only_after_a_complete_flush(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_fsync = os.fsync
            def inspect_fsync(fd):
                self.assertEqual(list(root.glob("PR*.md")), [])
                real_fsync(fd)
            with patch("git_tools.generators.utils.artifacts.os.fsync", side_effect=inspect_fsync):
                path = save_draft(BODY, "pr", root)
            self.assertEqual(path.read_bytes(), (BODY + "\n").encode())
            self.assertEqual(list(root.iterdir()), [path])

    def test_failed_wrapper_closes_raw_descriptor_and_removes_private_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            descriptors = []
            def fail_wrapper(fd, *args, **kwargs):
                descriptors.append(fd)
                raise OSError(errno.EIO, "wrapper failed")
            with patch("git_tools.generators.utils.artifacts.os.fdopen", side_effect=fail_wrapper):
                with self.assertRaises(OSError):
                    save_draft(BODY, "pr", Path(tmp))
            self.assertEqual(len(descriptors), 1)
            with self.assertRaises(OSError) as closed:
                os.fstat(descriptors[0])
            self.assertEqual(closed.exception.errno, errno.EBADF)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_publication_failure_preserves_existing_files_and_leaves_no_partial_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = root / "PR.md"
            original.write_text("original")
            with patch("git_tools.generators.utils.artifacts.os.link", side_effect=OSError(errno.EOPNOTSUPP, "hard links unavailable")):
                with self.assertRaises(OSError):
                    save_draft(BODY, "pr", root)
            self.assertEqual(list(root.iterdir()), [original])
            self.assertEqual(original.read_text(), "original")

    def test_concurrent_saves_publish_unique_complete_drafts(self):
        frozen = datetime(2026, 11, 17, 15, 0, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, patch("git_tools.generators.utils.artifacts.datetime") as clock:
            root = Path(tmp)
            clock.now.return_value = frozen
            contents = [f"## Title: feat: result {index}\n\n{BODY}" for index in range(12)]
            with ThreadPoolExecutor(max_workers=6) as workers:
                paths = list(workers.map(lambda content: save_draft(content, "pr", root), contents))
            self.assertEqual(len(set(paths)), len(contents))
            self.assertEqual(len(list(root.iterdir())), len(contents))
            for path, content in zip(paths, contents):
                self.assertEqual(path.read_bytes(), (content + "\n").encode())

    def test_preserves_crlf_indentation_and_existing_trailing_newline(self):
        text = "  code  \r\n\r\nLast\r\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = save_draft(text, "pr", Path(tmp))
            self.assertEqual(path.read_bytes(), text.encode("utf-8"))


class DraftHandoffTests(unittest.TestCase):
    def test_all_generated_types_save_with_no_copy_in_invocation_directory(self):
        for kind, stem in (("pr", "PR"), ("issue", "ISSUE"), ("both", "ISSUEPR")):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, chdir(tmp):
                Path("nested").mkdir()
                with chdir("nested"), issue_boundaries({"content": f"````markdown\n{BODY}\n````"}, generation_type=kind) as (generator, clipboard):
                    path = generator.generate_issue_pullrequest()
                    self.assertEqual(path, Path.cwd() / f"{stem}.md")
                    self.assertEqual(path.read_bytes(), (BODY + "\n").encode("utf-8"))
                    clipboard.assert_not_called()
                self.assertFalse(Path(f"{stem}.md").exists())

    def test_copy_failure_and_late_cancel_preserve_exactly_one_saved_draft(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, copy=None, interactive=True) as (generator, clipboard):
                if cancel:
                    generator.prompt_confirm.side_effect = [True, NavigationBack()]
                    with self.assertRaises(NavigationBack):
                        generator.generate_issue_pullrequest()
                    clipboard.assert_not_called()
                else:
                    clipboard.side_effect = RuntimeError("no display")
                    generator.generate_issue_pullrequest()
                    clipboard.assert_called_once_with(BODY)
                self.assertEqual(list(Path(tmp).glob("*.md")), [Path(tmp) / "PR.md"])
                self.assertEqual(Path("PR.md").read_bytes(), (BODY + "\n").encode())

    def test_empty_missing_and_nonstring_responses_never_create_or_copy_drafts(self):
        for fixed in (False, True):
            for response in (None, {}, {"content": ""}, {"content": "  "}, {"content": "```markdown\n```"}, {"content": None}, {"content": []}):
                with self.subTest(fixed=fixed, response=response), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries(response) as (generator, clipboard):
                    with patch.object(generator, "_resolve_fixed_pr_title", return_value="Start 1.2.0" if fixed else None):
                        with self.assertRaises(ValueError):
                            generator.generate_issue_pullrequest()
                    self.assertEqual(list(Path(tmp).iterdir()), [])
                    clipboard.assert_not_called()

    def test_headless_default_does_not_attempt_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, copy=None) as (generator, clipboard):
            clipboard.side_effect = RuntimeError("no display")
            with patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator):
                result = CliRunner().invoke(app, ["pr"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(Path("PR.md").read_bytes(), (BODY + "\n").encode())
            clipboard.assert_not_called()

    def test_missing_key_local_mode_is_not_a_finished_draft(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries(credentials=False, copy=None) as (generator, clipboard):
            generator.generate_issue_pullrequest()
            self.assertEqual(list(Path(tmp).iterdir()), [])
            clipboard.assert_not_called()

    def test_save_error_is_nonzero_but_keeps_preview_and_requested_clipboard(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, copy=True) as (generator, clipboard):
            with patch("git_tools.generators.issueprgen.generator.save_draft", side_effect=PermissionError("read-only")), patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator):
                result = CliRunner().invoke(app, ["pr", "--copy"])
            self.assertEqual(result.exit_code, 1, result.output)
            self.assertIn("Could not save pr draft", result.output)
            self.assertIn("LAST", result.output)
            self.assertNotIn("Saved draft:", result.output)
            clipboard.assert_called_once_with(BODY)

    def test_malformed_real_metadata_cannot_block_copy_or_hide_a_write_failure(self):
        for command in ("pr", "issue"):
            for fail_save in (False, True):
                for usage in ({"cost": "0.002"}, {"prompt_tokens": "10"}):
                    response = {"content": BODY, "response_metadata": {"token_usage": usage}}
                    with self.subTest(command=command, fail_save=fail_save, usage=usage), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries(response, copy=True, generation_type=command) as (generator, clipboard), ExitStack() as stack:
                        generator.display_token_usage.side_effect = lambda value: DisplayMixin.display_token_usage(generator, value)
                        if fail_save:
                            stack.enter_context(patch("git_tools.generators.issueprgen.generator.save_draft", side_effect=PermissionError("read-only")))
                        stack.enter_context(patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator))
                        result = CliRunner().invoke(app, [command, "--copy"])
                        self.assertEqual(result.exit_code, int(fail_save), result.output)
                        clipboard.assert_called_once_with(BODY)
                        if fail_save:
                            self.assertIn(f"Could not save {command} draft", result.output)
                            self.assertEqual(list(Path(tmp).iterdir()), [])
                        else:
                            self.assertEqual(Path(f"{command.upper()}.md").read_bytes(), (BODY + "\n").encode())

    def test_cancellation_during_metadata_cannot_turn_a_failed_save_into_success(self):
        for command in ("pr", "issue"):
            for fail_save in (False, True):
                for stage in ("display_reasoning", "display_token_usage"):
                    for signal in (KeyboardInterrupt, NavigationBack):
                        with self.subTest(command=command, fail_save=fail_save, stage=stage, signal=signal), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, copy=True, generation_type=command) as (generator, clipboard), ExitStack() as stack:
                            getattr(generator, stage).side_effect = signal()
                            if fail_save:
                                stack.enter_context(patch("git_tools.generators.issueprgen.generator.save_draft", side_effect=PermissionError("read-only")))
                            stack.enter_context(patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator))
                            result = CliRunner().invoke(app, [command, "--copy"])
                            self.assertEqual(result.exit_code, int(fail_save), result.output)
                            clipboard.assert_not_called()
                            if fail_save:
                                self.assertIn(f"Could not save {command} draft", result.output)
                            else:
                                self.assertTrue(Path(f"{command.upper()}.md").is_file())

    def test_saved_path_preserves_emoji_aliases_in_directory_name(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            Path(":smile:").mkdir()
            with chdir(":smile:"), issue_boundaries({"content": BODY}) as (generator, clipboard), patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator):
                result = CliRunner().invoke(app, ["pr", "--no-copy"])
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertIn(f"Saved draft: {Path.cwd() / 'PR.md'}", result.output)

    def test_plain_commit_subjects_and_local_prompts_preserve_emoji_aliases(self):
        text = "fix: preserve :warning: and :smile: [literal]"
        for kind in ("commit", "workflow", "local"):
            with self.subTest(kind=kind), ExitStack() as stack:
                output = StringIO()
                capture = Console(file=output, force_terminal=False, width=25)
                generator = CommitGenerator(auto_commit=False, copy_clipboard=False)
                if kind == "commit":
                    stack.enter_context(patch("git_tools.generators.commitgen.generator.console", capture))
                    generator._display_response({"content": text})
                elif kind == "workflow":
                    stack.enter_context(patch("git_tools.generators.commitgen.workflow.console", capture))
                    stack.enter_context(patch.object(generator, "_get_staged_files", return_value=[]))
                    stack.enter_context(patch.object(generator, "_build_workflow_subject", return_value=text))
                    stack.enter_context(patch("git_tools.generators.commitgen.workflow.save_draft", return_value=None))
                    generator._handle_workflow_commit("open-release")
                else:
                    stack.enter_context(patch("git_tools.generators.base.interaction.console", capture))
                    generator.handoff_local_prompt(text)
                self.assertIn(text, output.getvalue())

    def test_cli_success_saves_reports_path_and_headless_preview_is_unwrapped(self):
        for command in ("pr", "issue"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, generation_type=command) as (generator, clipboard):
                with patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator):
                    result = CliRunner().invoke(app, [command, "--no-copy"], color=True)
                self.assertEqual(result.exit_code, 0, result.output)
                path = Path(tmp) / f"{command.upper()}.md"
                self.assertEqual(path.read_bytes(), (BODY + "\n").encode())
                self.assertIn(f"Saved draft: {path.resolve()}", result.output)
                self.assertIn(BODY, result.output)
                self.assertNotIn("\x1b[", result.output)
                self.assertNotIn("╭", result.output)

    def test_real_cli_dispatch_repeated_runs_keep_original_and_issue_has_own_artifact(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), ExitStack() as stack:
            for name, value in (("get_default_branch", "develop"), ("get_commit_info", {"base_branch": "develop", "commit_count": 1}), ("_collect_generation_content", ("c", "feat: input")), ("select_provider", "openrouter"), ("ensure_api_key_configured", True), ("select_model_params", ("mock", 0.0, 1000)), ("_initialize_service", True), ("generate_content", {"content": BODY}), ("_should_apply_azure_limit", False)):
                stack.enter_context(patch.object(IssuePullRequestGenerator, name, return_value=value))
            for name in ("show_commit_summary", "display_reasoning", "display_token_usage"):
                stack.enter_context(patch.object(IssuePullRequestGenerator, name))
            for name in ("prompt_confirm", "prompt_text", "prompt_select"):
                stack.enter_context(patch.object(IssuePullRequestGenerator, name, side_effect=AssertionError("unexpected prompt")))
            clipboard = stack.enter_context(patch("pyperclip.copy"))
            stack.enter_context(patch("subprocess.run", side_effect=AssertionError("unexpected Git mutation")))
            first = CliRunner().invoke(app, ["pr", "--no-copy"])
            self.assertEqual(first.exit_code, 0, first.output)
            self.assertEqual(Path("PR.md").read_bytes(), (BODY + "\n").encode())
            Path("PR.md").write_text("original must survive")
            second = CliRunner().invoke(app, ["pr", "--no-copy"])
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertEqual(Path("PR.md").read_text(), "original must survive")
            self.assertEqual(len(list(Path(tmp).glob("PR-*.md"))), 1)
            issue = CliRunner().invoke(app, ["issue", "--no-copy"])
            self.assertEqual(issue.exit_code, 0, issue.output)
            self.assertEqual(Path("ISSUE.md").read_bytes(), (BODY + "\n").encode())
            clipboard.assert_not_called()

    def test_context_only_fixed_pr_saves_with_no_unique_commits(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}) as (generator, clipboard):
            generator.start_pr = True
            generator.get_commit_info.return_value = None
            fixed = SimpleNamespace(fixed_title="Start 1.2.0", to_prompt_block=lambda: "Validated version context")
            with patch.object(generator, "_resolve_start_pr_context", return_value=fixed):
                path = generator.generate_issue_pullrequest()
            self.assertTrue(path.read_text().startswith("## Title: Start 1.2.0"))
            generator._collect_generation_content.assert_called_once_with(None, fixed)

    def test_early_cancellation_creates_no_artifact_and_write_failure_cannot_be_cancelled_into_success(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}, copy=None, interactive=True) as (generator, clipboard):
            generator.get_default_branch.side_effect = NavigationBack()
            with self.assertRaises(NavigationBack):
                generator.generate_issue_pullrequest()
            self.assertEqual(list(Path(tmp).iterdir()), [])
            generator.get_default_branch.side_effect = None
            generator.prompt_confirm.side_effect = [True, NavigationBack()]
            with patch("git_tools.generators.issueprgen.generator.save_draft", side_effect=PermissionError("read-only")), self.assertRaisesRegex(ValueError, "Could not save"):
                generator.generate_issue_pullrequest()
            clipboard.assert_not_called()

    def test_fixed_titles_and_azure_final_result_saved_once(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries({"content": BODY}) as (generator, clipboard):
            generator._should_apply_azure_limit.return_value = True
            with patch.object(generator, "_resolve_fixed_pr_title", return_value="Start 1.2.0"), patch.object(generator, "_enforce_azure_pr_description_limit", return_value="## Title: Start 1.2.0\n\nCondensed") as enforce:
                path = generator.generate_issue_pullrequest()
            self.assertEqual(path.read_text(), "## Title: Start 1.2.0\n\nCondensed\n")
            self.assertIn("## Title: Start 1.2.0", enforce.call_args.args[0])
            self.assertEqual(len(list(Path(tmp).glob("*.md"))), 1)

    def test_blank_azure_retry_keeps_complete_original_with_fixed_title(self):
        generator = IssuePullRequestGenerator(generation_type="pr")
        original = "## Title: Start 1.2.0\n\n" + "x" * 4100
        for response in (None, {"content": ""}, {"content": "```\n```"}, {"content": None}):
            with self.subTest(response=response), patch.object(generator, "generate_content", return_value=response), patch.object(generator, "_resolve_fixed_pr_title", return_value="Start 1.2.0"):
                self.assertEqual(generator._enforce_azure_pr_description_limit(original, "source", "system"), original)

    def test_normalization_preserves_combined_titles_and_fenced_examples(self):
        example = "```text\nNext Develop: keep this example\n## Related Issue\nIssue: #123\n## Title: example title\n```"
        generator = IssuePullRequestGenerator(generation_type="pr")
        with patch.object(generator, "_resolve_fixed_pr_title", return_value="Start 1.2.0"):
            normalized = generator._normalize_pr_output("## Title: wrong\n\n" + example + "\n\nFinal  ")
        self.assertIn(example, normalized)
        self.assertTrue(normalized.startswith("## Title: Start 1.2.0"))
        self.assertTrue(normalized.endswith("Final  "))
        generator.generation_type = "both"
        combined = "## Title: issue title\n\nIssue body\n\n## Title: PR title\n\n" + example
        with patch.object(generator, "_resolve_fixed_pr_title", return_value="Start 1.2.0"):
            self.assertEqual(generator._normalize_pr_output(combined), combined)


class DirectFailureTests(unittest.TestCase):
    def test_issue_pr_provider_and_initialization_failures_exit_nonzero(self):
        for command in ("pr", "issue"):
            for initialize, response in ((False, None), (True, None), (True, {"content": ""})):
                with self.subTest(command=command, initialize=initialize, response=response), tempfile.TemporaryDirectory() as tmp, chdir(tmp), issue_boundaries(response, initialize=initialize, generation_type=command) as (generator, clipboard):
                    with patch("git_tools.generators.issueprgen.IssuePullRequestGenerator", return_value=generator):
                        result = CliRunner().invoke(app, [command, "--no-copy"])
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertEqual(list(Path(tmp).iterdir()), [])
                    clipboard.assert_not_called()

    def test_commit_provider_invalid_output_and_sensitive_refusal_exit_nonzero(self):
        for case in ("initialize", "generate", "invalid", "sensitive"):
            with self.subTest(case=case), ExitStack() as stack:
                generator = CommitGenerator(auto_commit=False, copy_clipboard=False)
                stack.enter_context(patch("git_tools.generators.commitgen.CommitGenerator", return_value=generator))
                for name, value in (("get_staged_diff", "diff"), ("_check_sensitive_files", case != "sensitive"), ("_handle_large_diff_processing", "diff"), ("select_provider", "openrouter"), ("ensure_api_key_configured", True), ("select_model_params", ("mock", 0.0, 1000)), ("_initialize_service", case != "initialize"), ("generate_commit_message", None if case == "generate" else {"content": ""})):
                    stack.enter_context(patch.object(generator, name, return_value=value))
                stack.enter_context(patch("subprocess.run", side_effect=AssertionError("unexpected commit")))
                result = CliRunner().invoke(app, ["commit", "--no-commit", "--no-copy"])
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertNotIn("Committed changes", result.output)

    def test_normal_and_workflow_commit_failures_and_timeouts_exit_nonzero(self):
        for fixed in (False, True):
            for failure in (subprocess.CalledProcessError(1, ["git", "commit"]), subprocess.TimeoutExpired(["git", "commit"], 900)):
                with self.subTest(fixed=fixed, failure=type(failure)), ExitStack() as stack:
                    generator = CommitGenerator(workflow_kind="open-release" if fixed else None, auto_commit=True)
                    stack.enter_context(patch("git_tools.generators.commitgen.CommitGenerator", return_value=generator))
                    stack.enter_context(patch.object(generator, "_get_staged_files", return_value=[]))
                    if not fixed:
                        stack.enter_context(patch.object(generator, "generate_commit", side_effect=lambda: generator._handle_commit_action({"content": "fix: test"})))
                    run = stack.enter_context(patch("subprocess.run", side_effect=failure))
                    result = CliRunner().invoke(app, ["commit"])
                    self.assertEqual(result.exit_code, 1, result.output)
                    self.assertNotIn("Committed changes", result.output)
                    run.assert_called_once()

    def test_explicit_interactive_requires_both_terminals_before_construction(self):
        targets = {"commit": "git_tools.generators.commitgen.CommitGenerator", "issue": "git_tools.generators.issueprgen.IssuePullRequestGenerator", "pr": "git_tools.generators.issueprgen.IssuePullRequestGenerator", "bump": "git_tools.generators.bumpgen.BumpGenerator", "init": "git_tools.generators.initgen.CommitizenInitGenerator"}
        for command, target in targets.items():
            for stdin, stdout in ((False, False), (True, False), (False, True), (True, True)):
                with self.subTest(command=command, stdin=stdin, stdout=stdout), patch(target) as constructor, patch("git_tools.cli.sys.stdin.isatty", return_value=stdin), patch("git_tools.cli.sys.stdout.isatty", return_value=stdout):
                    # CliRunner installs its own streams, so stub the detector from the independently checked TTY pair.
                    with patch("git_tools.cli._has_interactive_terminal", return_value=stdin and stdout):
                        result = CliRunner().invoke(app, [command, "-i"])
                    self.assertEqual(result.exit_code, 0 if stdin and stdout else 1, result.output)
                    self.assertEqual(constructor.call_count, int(stdin and stdout))

    def test_defaults_and_get_next_remain_prompt_free_without_terminals(self):
        for args, target in ((["init", "-i", "--defaults"], "git_tools.generators.initgen.CommitizenInitGenerator"), (["bump", "-i", "--get-next"], "git_tools.generators.bumpgen.BumpGenerator")):
            with self.subTest(args=args), patch(target), patch("git_tools.cli._has_interactive_terminal", return_value=False):
                result = CliRunner().invoke(app, args)
                self.assertEqual(result.exit_code, 0, result.output)

    def test_unexpected_eof_is_failure_not_successful_cancellation(self):
        targets = (("commit", "git_tools.generators.commitgen.CommitGenerator", "generate_commit"), ("pr", "git_tools.generators.issueprgen.IssuePullRequestGenerator", "generate_issue_pullrequest"), ("issue", "git_tools.generators.issueprgen.IssuePullRequestGenerator", "generate_issue_pullrequest"), ("bump", "git_tools.generators.bumpgen.BumpGenerator", "generate_bump"), ("init", "git_tools.generators.initgen.CommitizenInitGenerator", "generate_init"))
        for command, target, method in targets:
            with self.subTest(command=command), patch(target) as constructor:
                getattr(constructor.return_value, method).side_effect = EOFError()
                result = CliRunner().invoke(app, [command])
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn("Input ended", result.output)

    def test_bump_git_timeout_is_bounded_and_reports_possible_partial_state(self):
        with patch("git_tools.generators.bumpgen.git.subprocess.run", side_effect=subprocess.TimeoutExpired(["git", "status"], 120)) as run:
            with self.assertRaisesRegex(GitError, "timed out.*Inspect repository state"):
                run_command(["git", "status"], cwd=Path.cwd())
        self.assertEqual(run.call_args.kwargs["timeout"], 120)


if __name__ == "__main__":
    unittest.main()

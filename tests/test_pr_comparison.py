"""PR comparison inputs against real Git histories in disposable repositories."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.generators.base.diffs import DiffProcessingMixin
from git_tools.generators.issueprgen.branches import BranchResolutionMixin
from git_tools.generators.issueprgen.commits import CommitHistoryMixin
from git_tools.generators.issueprgen.content import GenerationContentMixin
from git_tools.generators.issueprgen.versions import VersionLookupMixin
from git_tools.generators.issueprgen import IssuePullRequestGenerator


class ComparisonHarness(
    BranchResolutionMixin,
    CommitHistoryMixin,
    GenerationContentMixin,
    VersionLookupMixin,
    DiffProcessingMixin,
):
    """Exercise input collection without constructing a model or provider."""

    def __init__(self, base: str | None = None, *, interactive: bool = False):
        self.logger = logging.getLogger(type(self).__name__)
        self._cli_base_branch = base
        self._interactive = interactive
        self._cli_input_source = "b"
        self.release_pr = self.hotfix_pr = self.start_pr = False
        self.backmerge_release_pr = self.backmerge_hotfix_pr = False

    def get_diff_processing_params(self, default: int) -> None:
        return None

    def display_quota_breakdown(self, *args) -> None:
        pass


class PrComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous_cwd)
        # Never inherit a caller's Git config, hooks, identity, or signing policy.
        env = patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        })
        env.start()
        self.addCleanup(env.stop)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "PR comparison tests")
        self.git("config", "user.email", "pr-comparison@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.0.0"\n')
        self.initial = self.commit("chore: initial base", date="2024-01-01T00:00:00+0000")

    def git(self, *args: str, date: str | None = None) -> str:
        env = dict(os.environ)
        if date:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(
            ["git", *args], cwd=self.root, env=env, check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()

    def write(self, path: str, text: str) -> None:
        (self.root / path).write_text(text, encoding="utf-8")

    def commit(self, message: str, *, date: str | None = None) -> str:
        self.git("add", "--all")
        self.git("commit", "-m", message, "--allow-empty", date=date)
        return self.git("rev-parse", "HEAD")

    def feature(self) -> str:
        self.git("switch", "-c", "feature/topic")
        self.write("feature.txt", "feature change\n")
        return self.commit("feat: isolated feature", date="2024-01-02T00:00:00+0000")

    def remote_only_base(self, name: str = "main") -> str:
        self.git("update-ref", f"refs/remotes/origin/{name}", self.initial)
        self.feature()
        self.git("branch", "-D", "main")
        return f"origin/{name}"

    def test_explicit_remote_only_base_is_carried_into_all_inputs(self) -> None:
        expected_ref = self.remote_only_base()
        generator = ComparisonHarness("main")
        before_refs = self.git("for-each-ref")
        before_config = (self.root / ".git/config").read_bytes()
        base = generator.get_default_branch()
        self.assertEqual(base, expected_ref)
        info = generator.get_commit_info(base)
        self.assertIsNotNone(info)
        self.assertEqual(info["base_branch"], expected_ref)
        self.assertEqual(info["commit_count"], 1)
        self.assertEqual(generator._load_version_from_ref(base), "1.0.0")
        source, content = generator._collect_generation_content(info, None)
        self.assertEqual(source, "b")
        self.assertIn("feat: isolated feature", content)
        self.assertIn("+feature change", content)
        with patch("git_tools.generators.issueprgen.commits.console.print") as display:
            generator.show_commit_summary(info)
        panel_calls = [call for call in display.call_args_list if call.args]
        self.assertEqual(len(panel_calls), 1)
        self.assertEqual(display.call_args.args, ())  # panel-owned trailing blank
        self.assertIn(expected_ref, panel_calls[0].args[0].renderable)
        # Resolution/collection is read-only: no fetch, ref movement, or config writes.
        self.assertEqual(self.git("for-each-ref"), before_refs)
        self.assertEqual((self.root / ".git/config").read_bytes(), before_config)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_cli_and_interactive_accept_the_same_local_only_short_name(self) -> None:
        self.feature()
        for interactive in (False, True):
            with self.subTest(interactive=interactive):
                generator = ComparisonHarness(None if interactive else "main", interactive=interactive)
                with patch.object(generator, "prompt_text", return_value="main", create=True):
                    self.assertEqual(generator.get_default_branch(), "main")

    def test_invalid_cli_and_interactive_bases_raise_instead_of_silently_defaulting(self) -> None:
        self.feature()
        for base in ("missing", "--all", "main..HEAD", "main:feature.txt", "bad ref", "main\n"):
            for interactive in (False, True):
                with self.subTest(base=base, interactive=interactive):
                    generator = ComparisonHarness(None if interactive else base, interactive=interactive)
                    with patch.object(generator, "prompt_text", return_value=base, create=True):
                        with self.assertRaisesRegex(ValueError, "[Bb]ase|[Bb]ranch"):
                            generator.get_default_branch()

    def test_blob_and_tree_are_not_valid_commit_bases(self) -> None:
        for object_name in ("HEAD:.cz.toml", "HEAD^{tree}"):
            object_hash = self.git("rev-parse", object_name)
            with self.subTest(object_name=object_name):
                with self.assertRaisesRegex(ValueError, "[Bb]ase|[Bb]ranch"):
                    ComparisonHarness(object_hash).get_default_branch()

    def test_commit_hash_and_commit_tag_are_valid_bases(self) -> None:
        self.feature()
        self.git("tag", "-a", "baseline", self.initial, "-m", "base tag")
        for base in (self.initial, self.initial[:7], "baseline", "refs/tags/baseline"):
            with self.subTest(base=base):
                generator = ComparisonHarness(base)
                resolved = generator.get_default_branch()
                info = generator.get_commit_info(resolved)
                self.assertEqual(info["commit_count"], 1)
                self.assertEqual(info["base_branch"], resolved)

    def test_explicit_local_and_remote_intent_survive_divergent_refs(self) -> None:
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.1.0"\n')
        self.write("remote.txt", "remote base change\n")
        remote_hash = self.commit("feat: newer remote base")
        self.git("update-ref", "refs/remotes/origin/main", remote_hash)
        self.feature()
        # Local main is stale and divergent while the feature uses origin/main.
        self.git("branch", "-f", "main", self.initial)
        self.git("switch", "main")
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.0.1"\n')
        self.write("local-only.txt", "local base work must not enter the feature diff\n")
        self.commit("fix: divergent local base")
        self.git("switch", "feature/topic")
        local = ComparisonHarness("main")
        remote = ComparisonHarness("origin/main")
        self.assertEqual(local.get_default_branch(), "main")
        self.assertEqual(remote.get_default_branch(), "origin/main")
        local_info = local.get_commit_info(local.get_default_branch())
        remote_info = remote.get_commit_info(remote.get_default_branch())
        self.assertEqual(local_info["commit_count"], 2)
        self.assertEqual(remote_info["commit_count"], 1)
        self.assertEqual(local._load_version_from_ref(local_info["base_branch"]), "1.0.1")
        self.assertEqual(remote._load_version_from_ref(remote_info["base_branch"]), "1.1.0")
        self.assertIn("remote base change", local.get_branch_diffs(local_info["base_branch"])[0])
        self.assertNotIn("remote base change", remote.get_branch_diffs(remote_info["base_branch"])[0])
        self.assertIn("feat: newer remote base", local.get_pr_commit_log("main"))
        self.assertNotIn("feat: newer remote base", remote.get_pr_commit_log("origin/main"))
        # Inference selected origin/main, so it must not drop back to stale main.
        inferred = ComparisonHarness().get_default_branch()
        self.assertEqual(inferred, "origin/main")
        self.assertEqual(ComparisonHarness().get_commit_info(inferred)["commit_count"], 1)

    def test_inferred_reflog_base_skips_the_current_published_branch(self) -> None:
        self.git("update-ref", "refs/remotes/origin/main", self.initial)
        feature_hash = self.feature()
        self.git("update-ref", "refs/remotes/origin/feature/topic", feature_hash)
        self.git("switch", "-c", "temporary")
        self.git("switch", "feature/topic")
        self.assertEqual(ComparisonHarness().get_default_branch(), "origin/main")

    def test_inference_skips_refs_that_resolve_to_head(self) -> None:
        self.git("branch", "develop")
        head = self.feature()
        self.git("update-ref", "refs/remotes/origin/main", head)
        self.git("branch", "-D", "main")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.assertEqual(ComparisonHarness().get_default_branch(), "develop")

    def test_symbolic_remote_default_preserves_branch_path(self) -> None:
        self.feature()
        self.git("branch", "-D", "main")
        self.git("reflog", "expire", "--expire=all", "--all")
        self.git("update-ref", "refs/remotes/origin/team/integration", self.initial)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/team/integration")
        base = ComparisonHarness().get_default_branch()
        self.assertIn(base, ("origin/team/integration", "refs/remotes/origin/team/integration"))
        self.assertEqual(ComparisonHarness().get_commit_info(base)["commit_count"], 1)

    def test_symbolic_remote_default_with_git_valid_name_reaches_all_inputs(self) -> None:
        # Explicit input retains its old restricted grammar; Git's own discovered
        # full refs must nevertheless survive comparison revalidation.
        name = "prod+stable"
        full_ref = f"refs/remotes/origin/{name}"
        self.git("check-ref-format", "--branch", name)
        self.git("branch", "-m", "main", name)
        self.git("update-ref", full_ref, self.initial)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", full_ref)
        feature_hash = self.feature()
        # The local namesake differs: an inferred remote must retain remote intent.
        self.git("branch", "-f", name, feature_hash)
        self.git("reflog", "expire", "--expire=all", "--all")
        before_refs = self.git("for-each-ref")
        before_config = (self.root / ".git/config").read_bytes()
        for interactive, selected in ((False, ""), (True, ""), (True, full_ref)):
            with self.subTest(interactive=interactive, selected=selected):
                generator = ComparisonHarness(interactive=interactive)
                with patch.object(generator, "prompt_text", return_value=selected, create=True):
                    base = generator.get_default_branch()
                self.assertEqual(base, full_ref)
                info = generator.get_commit_info(base)
                self.assertEqual(info["base_branch"], full_ref)
                self.assertEqual(info["merge_base"], self.initial)
                self.assertEqual(info["commit_hashes"], [feature_hash])
                self.assertEqual(info["commit_count"], 1)
                self.assertIn("feat: isolated feature", generator.get_commit_messages(info))
                legacy_info = {"base_branch": base, "commit_count": 1}
                self.assertIn("feat: isolated feature", generator.get_commit_messages(legacy_info))
                self.assertIn("+feature change", generator.get_branch_diffs(base)[0])
                self.assertEqual(generator._load_version_from_ref(base), "1.0.0")
                self.assertIn("feat: isolated feature", generator.get_pr_commit_log(base))
                source, content = generator._collect_generation_content(info, None)
                self.assertEqual(source, "b")
                self.assertIn("feat: isolated feature", content)
                self.assertIn("+feature change", content)
                with patch("git_tools.generators.issueprgen.commits.console.print") as display:
                    generator.show_commit_summary(info)
                panel_calls = [call for call in display.call_args_list if call.args]
                self.assertEqual(len(panel_calls), 1)
                self.assertEqual(display.call_args.args, ())  # panel-owned trailing blank
                self.assertIn(full_ref, panel_calls[0].args[0].renderable)
        # Neither CLI nor a newly entered unsupported name gains broader grammar.
        for explicit in (name, f"origin/{name}", full_ref):
            with self.subTest(explicit=explicit):
                with self.assertRaisesRegex(ValueError, "Invalid base"):
                    ComparisonHarness(explicit).get_default_branch()
        for selected in (name, f"origin/{name}"):
            with self.subTest(manual=selected):
                generator = ComparisonHarness(interactive=True)
                with patch.object(generator, "prompt_text", return_value=selected, create=True):
                    with self.assertRaisesRegex(ValueError, "Invalid base"):
                        generator.get_default_branch()
        self.assertEqual(self.git("for-each-ref"), before_refs)
        self.assertEqual((self.root / ".git/config").read_bytes(), before_config)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_internal_exact_ref_validation_rejects_revision_expressions_and_noncommits(self) -> None:
        self.feature()
        self.git("update-ref", "refs/tags/tree-base", self.git("rev-parse", "HEAD^{tree}"))
        generator = ComparisonHarness()
        for ref in ("main", "HEAD", "refs/heads/main~1", "refs/heads/main^{commit}",
                    "refs/heads/main..HEAD", "refs/heads/missing", "refs/tags/tree-base"):
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError):
                    generator._validate_exact_base_ref(ref)

    def test_no_valid_inferred_base_is_a_clear_error_not_nonexistent_main(self) -> None:
        self.feature()
        self.git("branch", "-D", "main")
        with self.assertRaisesRegex(ValueError, "[Bb]ase|--base"):
            ComparisonHarness().get_default_branch()

    def custom_base_without_inference_candidates(self) -> str:
        """A usable nonstandard base with no origin/default/checkouts to infer."""
        base = "custom/integration"
        self.git("branch", base, self.initial)
        self.feature()
        self.git("branch", "-D", "main")
        self.git("reflog", "expire", "--expire=all", "--all")
        return base

    def test_interactive_missing_inference_candidate_accepts_valid_manual_base(self) -> None:
        base = self.custom_base_without_inference_candidates()
        before_refs = self.git("for-each-ref")
        before_config = (self.root / ".git/config").read_bytes()
        generator = ComparisonHarness(interactive=True)
        with (
            patch.object(generator, "prompt_text", return_value=base, create=True) as prompt,
            patch("git_tools.generators.issueprgen.branches.warning") as warning,
        ):
            resolved = generator.get_default_branch()
        self.assertEqual(resolved, base)
        prompt.assert_called_once_with("Enter base branch name or commit hash", "")
        warning.assert_called_once()
        self.assertIn("Could not infer a base branch", warning.call_args.args[0])
        self.assertEqual(generator.get_commit_info(resolved)["commit_count"], 1)
        # A direct invocation still needs --base, rather than guessing a ref.
        with self.assertRaisesRegex(ValueError, "Could not infer.*--base"):
            ComparisonHarness().get_default_branch()
        self.assertEqual(self.git("for-each-ref"), before_refs)
        self.assertEqual((self.root / ".git/config").read_bytes(), before_config)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_interactive_missing_inference_candidate_still_validates_manual_input(self) -> None:
        self.custom_base_without_inference_candidates()
        for selected in ("", "missing", "--all", "main..HEAD"):
            with self.subTest(selected=selected):
                generator = ComparisonHarness(interactive=True)
                with (
                    patch.object(generator, "prompt_text", return_value=selected, create=True) as prompt,
                    patch("git_tools.generators.issueprgen.branches.warning"),
                ):
                    with self.assertRaisesRegex(ValueError, "[Bb]ase|[Bb]ranch"):
                        generator.get_default_branch()
                prompt.assert_called_once_with("Enter base branch name or commit hash", "")

    def test_interactive_missing_inference_candidate_preserves_manual_input_cancel(self) -> None:
        self.custom_base_without_inference_candidates()
        generator = ComparisonHarness(interactive=True)
        with (
            patch.object(generator, "prompt_text", side_effect=KeyboardInterrupt, create=True),
            patch("git_tools.generators.issueprgen.branches.warning"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                generator.get_default_branch()

    def test_workflow_defaults_keep_remote_only_base_and_accept_develop(self) -> None:
        self.feature()
        self.git("branch", "-D", "main")
        self.git("update-ref", "refs/remotes/origin/master", self.initial)
        self.git("update-ref", "refs/remotes/origin/develop", self.initial)
        for mode, expected in (("release_pr", "origin/master"), ("hotfix_pr", "origin/master"),
                               ("start_pr", "origin/develop"), ("backmerge_release_pr", "origin/develop"),
                               ("backmerge_hotfix_pr", "origin/develop")):
            with self.subTest(mode=mode):
                generator = ComparisonHarness()
                setattr(generator, mode, True)
                base = generator.get_default_branch()
                self.assertEqual(base, expected)
                if expected.endswith("develop"):
                    generator._require_develop_base_branch(base, mode=mode)
                    generator._require_develop_base_branch("refs/remotes/origin/develop", mode=mode)
                self.assertEqual(generator._load_version_from_ref(base), "1.0.0")

    def test_fixed_modes_allow_distinct_target_at_head_for_context_only_output(self) -> None:
        self.git("switch", "-c", "release/1.1.0")
        self.git("update-ref", "refs/remotes/origin/master", self.initial)
        self.git("update-ref", "refs/remotes/origin/develop", self.initial)
        for mode, expected in (("release_pr", "origin/master"), ("hotfix_pr", "origin/master"),
                               ("start_pr", "origin/develop"), ("backmerge_release_pr", "origin/develop"),
                               ("backmerge_hotfix_pr", "origin/develop")):
            with self.subTest(mode=mode):
                generator = ComparisonHarness()
                setattr(generator, mode, True)
                base = generator.get_default_branch()
                self.assertEqual(base, expected)
                self.assertIsNone(generator.get_commit_info(base))

    def test_promotion_context_accepts_exact_remote_ref_without_losing_it(self) -> None:
        for kind, branch, current, expected in (
            ("release", "release/1.1.0", "1.1.0-rc.0", "1.1.0"),
            ("hotfix", "hotfix/urgent", "1.0.1-rc.0", "1.0.1"),
        ):
            for base in ("origin/main", "refs/remotes/origin/master", "refs/remotes/upstream/main"):
                with self.subTest(kind=kind, base=base):
                    generator = IssuePullRequestGenerator(generation_type="pr", **{f"{kind}_pr": True})
                    with (
                        patch.object(generator, "_get_current_branch_name", return_value=branch),
                        patch.object(generator, "_load_version_from_ref", return_value="1.0.0") as load,
                        patch.object(generator, "_load_current_branch_version", return_value=current),
                    ):
                        context = getattr(generator, f"_resolve_{kind}_pr_context")(base)
                    self.assertEqual(context.base_branch, base)
                    self.assertEqual(context.target_version, expected)
                    load.assert_called_once_with(base)

    def merged_base_history(self) -> tuple[ComparisonHarness, str, str]:
        feature_hash = self.feature()
        self.git("switch", "main")
        self.write("base.txt", "later base work\n")
        base_hash = self.commit("fix: base-side work must stay excluded", date="2024-01-03T00:00:00+0000")
        self.git("switch", "feature/topic")
        self.git("merge", "--no-ff", "main", "-m", "Merge refreshed base", date="2024-01-04T00:00:00+0000")
        return ComparisonHarness("main"), feature_hash, base_hash

    def test_messages_use_exact_merge_base_range_not_last_n_reachable_commits(self) -> None:
        generator, feature_hash, base_hash = self.merged_base_history()
        info = generator.get_commit_info(generator.get_default_branch())
        self.assertEqual(info["commit_count"], 2)
        self.assertEqual(set(info["commit_hashes"]), {self.git("rev-parse", "HEAD"), feature_hash})
        self.assertEqual(info["commit_range"], f"{base_hash}..{self.git('rev-parse', 'HEAD')}")
        # Demonstrate the regression really differs from unrestricted git log -N.
        old_messages = self.git("log", "-2", "--pretty=%s")
        self.assertIn("base-side work", old_messages)
        self.assertNotIn("feat: isolated feature", old_messages)
        messages = generator.get_commit_messages(info)
        self.assertIn("feat: isolated feature", messages)
        self.assertIn("Merge refreshed base", messages)
        self.assertNotIn("base-side work", messages)
        self.assertEqual(generator.get_commit_messages(info["commit_count"]), messages)
        for source in ("c", "b"):
            with self.subTest(source=source):
                generator._cli_input_source = source
                _, content = generator._collect_generation_content(info, None)
                self.assertIn("feat: isolated feature", content)
                self.assertNotIn("base-side work", content)
                self.assertNotIn("+later base work", content)

    def test_message_range_is_pinned_if_head_moves_after_summary(self) -> None:
        generator, _, _ = self.merged_base_history()
        info = generator.get_commit_info(generator.get_default_branch())
        self.write("later.txt", "new unrelated work\n")
        self.commit("chore: later head movement")
        messages = generator.get_commit_messages(info)
        self.assertIn("feat: isolated feature", messages)
        self.assertNotIn("later head movement", messages)
        pinned_diff, _ = generator.get_branch_diffs(info["base_branch"])
        self.assertIn("+feature change", pinned_diff)
        self.assertNotIn("new unrelated work", pinned_diff)
        # Moving the base also cannot alter an already-inspected comparison.
        self.git("branch", "-f", "main", "HEAD")
        self.assertEqual(generator.get_branch_diffs(info["base_branch"])[0], pinned_diff)

    def test_divergent_target_keeps_existing_merge_base_semantics(self) -> None:
        # Keep the established merge-base policy, rather than changing to base..HEAD.
        self.git("switch", "-c", "feature/topic")
        self.write("feature.txt", "feature\n")
        feature_hash = self.commit("feat: topic")
        self.git("switch", "main")
        self.write("main.txt", "main-only\n")
        self.commit("fix: target branch only")
        self.git("switch", "feature/topic")
        generator = ComparisonHarness("main")
        info = generator.get_commit_info(generator.get_default_branch())
        self.assertEqual(info["commit_count"], 1)
        self.assertEqual(info["commit_hashes"], [feature_hash])
        self.assertTrue(info["commit_range"].startswith(self.initial + ".."))
        _, content = generator._collect_generation_content(info, None)
        self.assertIn("feat: topic", content)
        self.assertNotIn("target branch only", content)
        self.assertNotIn("main-only", content)

    def test_non_origin_remote_base_preserves_mode_branch_identity(self) -> None:
        self.git("update-ref", "refs/remotes/upstream/develop", self.initial)
        self.feature()
        generator = ComparisonHarness("upstream/develop")
        base = generator.get_default_branch()
        generator._require_develop_base_branch(base, mode="Start PR mode")
        self.assertEqual(generator._load_version_from_ref(base), "1.0.0")
        self.assertEqual(generator.get_commit_info(base)["commit_count"], 1)

    def test_explicit_qualified_remote_is_not_shadowed_by_a_local_branch(self) -> None:
        self.git("update-ref", "refs/remotes/upstream/main", self.initial)
        self.feature()
        self.git("branch", "upstream/main")
        generator = ComparisonHarness("upstream/main")
        base = generator.get_default_branch()
        self.assertEqual(base, "refs/remotes/upstream/main")
        self.assertEqual(generator.get_commit_info(base)["commit_count"], 1)

    def test_explicit_local_branch_is_not_shadowed_by_a_tag(self) -> None:
        self.feature()
        self.git("tag", "main")
        generator = ComparisonHarness("main")
        base = generator.get_default_branch()
        self.assertEqual(base, "refs/heads/main")
        self.assertEqual(generator.get_commit_info(base)["commit_count"], 1)

    def test_legacy_summary_dict_derives_messages_from_its_base_not_its_count(self) -> None:
        generator, _, _ = self.merged_base_history()
        messages = generator.get_commit_messages({"base_branch": "main", "commit_count": 2})
        self.assertIn("feat: isolated feature", messages)
        self.assertNotIn("base-side work", messages)

    def test_count_without_an_inspected_range_never_logs_unbounded_head(self) -> None:
        generator = ComparisonHarness()
        with patch("subprocess.check_output") as log:
            self.assertIsNone(generator.get_commit_messages(2))
            self.assertIsNone(generator.get_commit_messages(0))
        log.assert_not_called()

    def test_unrelated_valid_base_raises_instead_of_reporting_no_commits(self) -> None:
        self.git("switch", "--orphan", "unrelated")
        self.commit("chore: unrelated history")
        with self.assertRaisesRegex(ValueError, "shared history"):
            ComparisonHarness().get_commit_info("main")

    def test_empty_comparison_is_still_no_commit_info(self) -> None:
        generator = ComparisonHarness("main")
        self.assertIsNone(generator.get_commit_info(generator.get_default_branch()))


if __name__ == "__main__":
    unittest.main()

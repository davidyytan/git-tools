"""Stdlib-only tests of the real PR workflow mixins, without LLM/UI imports."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from git_tools.generators import bumpgen


def load_mixins():
    root = Path(__file__).resolve().parents[1] / "git_tools"
    prefix = "_hotfix_backmerge_tests"
    for name, directory in ((prefix, root / "generators"),
                            (prefix + ".issueprgen", root / "generators/issueprgen"),
                            (prefix + ".base", root / "generators/base")):
        module = types.ModuleType(name)
        module.__path__ = [str(directory)]
        sys.modules[name] = module
    sys.modules[prefix + ".bumpgen"] = bumpgen

    def load(name, path):
        spec = importlib.util.spec_from_file_location(prefix + "." + name, root / path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    prompts = load("base.prompts", "generators/base/prompts.py")
    load("issueprgen.contexts", "generators/issueprgen/contexts.py")
    versions = load("issueprgen.versions", "generators/issueprgen/versions.py")
    workflow = load("issueprgen.workflow", "generators/issueprgen/workflow.py")
    titles = load("issueprgen.titles", "generators/issueprgen/titles.py")
    promotion = load("issueprgen.promotion", "generators/issueprgen/promotion.py")
    return prompts, versions, workflow, titles, promotion


prompts, versions, workflow, titles, promotion = load_mixins()


class Harness(workflow.WorkflowContextMixin, titles.FixedTitleMixin,
              versions.VersionLookupMixin, promotion.PromotionContextMixin,
              prompts.PromptTemplateMixin):
    def __init__(self, version=None, interactive=False):
        self._cli_workflow_version = version
        self._interactive = interactive
        self.start_pr = self.release_pr = self.hotfix_pr = self.backmerge_release_pr = False
        self.backmerge_hotfix_pr = True
        self.generation_type = "pr"
        self._workflow_pr_context = self._promotion_pr_context = None
        self._get_current_branch_name = Mock(return_value="hotfix/auth")
        self._load_version_from_ref = Mock(return_value="1.6.1")
        self._load_current_branch_version = Mock(return_value="1.7.0-alpha.2")
        self.prompt_text = Mock(return_value="1.6.1")

    def _require_develop_base_branch(self, branch, *, mode):
        if branch != "develop":
            raise ValueError(mode + " requires develop")


class HotfixBackmergeTests(unittest.TestCase):
    def test_no_version_fails_closed_regardless_of_master_and_source(self):
        for master in (None, "1.6.0", "1.6.1", "1.6.2", "1.7.0"):
            for source in (None, "1.6.0", "1.6.1-rc.1", "1.7.0-alpha.2"):
                with self.subTest(master=master, source=source):
                    h = Harness()
                    h._load_version_from_ref.return_value = master
                    h._load_current_branch_version.return_value = source
                    with self.assertRaisesRegex(ValueError, "Pass --workflow-version"):
                        h._resolve_backmerge_hotfix_pr_context("develop")
                    self.assertIsNone(h._resolve_fixed_pr_title())
                    h._load_version_from_ref.assert_not_called()
                    h._load_current_branch_version.assert_not_called()

    def test_explicit_version_is_used_despite_newer_or_missing_state(self):
        for state in (None, "1.7.0-alpha.2", "1.6.2"):
            with self.subTest(state=state):
                h = Harness(" 1.6.1 ")
                h._load_version_from_ref.return_value = state
                h._load_current_branch_version.return_value = state
                context = h._resolve_backmerge_hotfix_pr_context("develop")
                self.assertEqual(context.target_version, "1.6.1")
                self.assertEqual(context.fixed_title, "Backmerge Hotfix 1.6.1")
                self.assertEqual(context.target_source, "explicit workflow version input")
                self.assertEqual(h._resolve_fixed_pr_title(), context.fixed_title)
                h._workflow_pr_context = context
                self.assertEqual(h._resolve_fixed_pr_title(), context.fixed_title)
                h.prompt_text.assert_not_called()

    def test_interactive_prompts_without_guess_and_preserves_context(self):
        h = Harness(interactive=True)
        context = h._resolve_backmerge_hotfix_pr_context("develop")
        h.prompt_text.assert_called_once_with("Enter already-promoted hotfix version", "")
        h._workflow_pr_context = context
        self.assertEqual(h._resolve_fixed_pr_title(), "Backmerge Hotfix 1.6.1")

    def test_invalid_explicit_version_rejected_in_context_and_title(self):
        for value in (" ", "1.6", "v1.6.1", "1.6.1-rc.1", "1.6.1+build"):
            with self.subTest(value=value):
                h = Harness(value)
                with self.assertRaises(ValueError):
                    h._resolve_backmerge_hotfix_pr_context("develop")
                with self.assertRaises(ValueError):
                    h._resolve_fixed_pr_title()

    def test_empty_interactive_input_rejected(self):
        h = Harness(interactive=True)
        h.prompt_text.return_value = ""
        with self.assertRaisesRegex(ValueError, "required"):
            h._resolve_backmerge_hotfix_pr_context("develop")

    def test_wrong_base_rejected(self):
        with self.assertRaises(ValueError):
            Harness("1.6.1")._resolve_backmerge_hotfix_pr_context("master")

    def test_prompt_and_normalization_use_explicit_title(self):
        h = Harness("1.6.1")
        self.assertEqual(h._build_pr_title_block(), "## Title: Backmerge Hotfix 1.6.1")
        self.assertIn("Backmerge Hotfix 1.6.1", h._build_pr_title_instruction())
        self.assertIn("Backmerge Hotfix 1.6.1", h._build_both_title_instruction())
        self.assertEqual(h._normalize_pr_output("## Title: Backmerge Hotfix 1.6.2\n\nBody"),
                         "## Title: Backmerge Hotfix 1.6.1\n\nBody")

    def test_hotfix_promotion_still_selects_next_patch(self):
        h = Harness()
        h.backmerge_hotfix_pr = False
        h.hotfix_pr = True
        h._load_version_from_ref.return_value = "1.6.0"
        h._load_current_branch_version.return_value = "1.6.1-rc.2"
        context = h._resolve_hotfix_pr_context("master")
        self.assertEqual(context.target_version, "1.6.1")
        h._promotion_pr_context = context
        self.assertEqual(h._resolve_fixed_pr_title(), "Hotfix 1.6.1")

    def test_release_backmerge_keeps_branch_name_inference(self):
        h = Harness()
        h.backmerge_hotfix_pr = False
        h.backmerge_release_pr = True
        h._get_current_branch_name.return_value = "release/1.6.0"
        context = h._resolve_backmerge_release_pr_context("develop")
        self.assertEqual(context.fixed_title, "Backmerge Release 1.6.0")


if __name__ == "__main__":
    unittest.main()

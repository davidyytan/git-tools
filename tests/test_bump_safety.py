"""Safety/continuity tests use only repositories inside isolated temp directories."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from git_tools.generators.bumpgen import BumpGenerator, BumpOptions, ConfigError, GitError, run_bump
from git_tools.generators.bumpgen.engine import apply_bump_plan, plan_bump
from git_tools.generators.bumpgen.git import describe_git_tag_behavior, require_clean_index


class BumpSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name).resolve()
        self.git("init")
        for key, value in (("user.name", "Test User"), ("user.email", "test@example.com"),
                           ("commit.gpgSign", "false"), ("tag.gpgSign", "false")):
            self.git("config", key, value)
        (self.root / ".cz.toml").write_text(
            '[tool.commitizen]\nversion = "1.2.3"\ntag_format = "v$version"\n', encoding="utf-8"
        )
        (self.root / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8"
        )
        (self.root / "package.json").write_text('{"name":"demo","version":"1.2.3"}\n', encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "chore: initial")
        self.git("tag", "v1.2.3")
        (self.root / "feature.txt").write_text("feature\n", encoding="utf-8")
        self.git("add", "feature.txt")
        self.git("commit", "-m", "fix: feature")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def state(self) -> tuple:
        files = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*")
                 if path.is_file() and ".git" not in path.relative_to(self.root).parts}
        return files, self.git("rev-parse", "HEAD"), self.git("show-ref"), self.git("diff", "--cached"), self.git("status", "--porcelain")

    def test_dry_run_full_diff_is_write_free_and_matches_apply(self) -> None:
        before = self.state()
        output = StringIO()
        with redirect_stdout(output):
            version = run_bump(BumpOptions(dry_run=True), cwd=self.root)
        self.assertEqual(str(version), "1.2.4")
        self.assertEqual(self.state(), before)
        for name in (".cz.toml", "pyproject.toml", "package.json"):
            self.assertIn(f"a/{name}", output.getvalue())
            self.assertIn(f"b/{name}", output.getvalue())
        plan = plan_bump(BumpOptions(), cwd=self.root)
        expected = {update.path: update.after for update in plan.updates}
        result = apply_bump_plan(plan)
        self.assertEqual(result, version)
        for path, content in expected.items():
            self.assertEqual(path.read_text(), content)
            self.assertEqual(self.git("show", f"HEAD:{path.relative_to(self.root)}"), content.strip())
        self.assertEqual(self.git("log", "-1", "--format=%s"), plan.message)
        self.assertEqual(self.git("rev-parse", "v1.2.4"), self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_get_next_is_lightweight_even_with_bad_auxiliary(self) -> None:
        with patch("git_tools.generators.bumpgen.engine.plan_version_file_updates", side_effect=AssertionError("must not plan")):
            output = StringIO()
            before = self.state()
            with redirect_stdout(output):
                version = run_bump(BumpOptions(get_next=True), cwd=self.root)
        self.assertEqual(output.getvalue(), "1.2.4\n")
        self.assertEqual(str(version), "1.2.4")
        self.assertEqual(self.state(), before)

    def test_interactive_cancel_and_default_preview_are_write_free(self) -> None:
        for actions in (("Cancel",), ("Preview", "Cancel")):
            with self.subTest(actions=actions):
                before = self.state()
                generator = BumpGenerator(increment="PATCH", interactive=True)
                with (patch.object(generator, "prompt_select", side_effect=["Stable release", *actions]) as select,
                      patch.object(generator, "prompt_confirm") as confirm,
                      redirect_stdout(StringIO())):
                    generator.generate_bump(cwd=self.root)
                self.assertEqual(self.state(), before)
                self.assertEqual(select.call_args_list[1].kwargs["default"], "Preview")
                confirm.assert_not_called()

    def test_interactive_preview_can_apply_same_plan_without_reprompt(self) -> None:
        generator = BumpGenerator(increment="PATCH", interactive=True)
        with (patch.object(generator, "prompt_select", side_effect=["Stable release", "Preview", "Apply"]) as select,
              patch.object(generator, "prompt_confirm") as confirm,
              patch("git_tools.generators.bumpgen.generator.plan_bump", wraps=plan_bump) as planner,
              redirect_stdout(StringIO())):
            generator.generate_bump(cwd=self.root)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(select.call_count, 3)
        confirm.assert_not_called()
        self.assertEqual(self.git("rev-parse", "v1.2.4"), self.git("rev-parse", "HEAD"))

    def test_staged_content_blocks_direct_and_interactive_before_mutation(self) -> None:
        for target in ("unrelated.txt", ".cz.toml"):
            with self.subTest(target=target):
                path = self.root / target
                original = path.read_text() if path.exists() else None
                path.write_text((original or "") + "# staged work\n")
                self.git("add", target)
                before = self.state()
                with self.assertRaisesRegex(GitError, "Unstage"):
                    run_bump(BumpOptions(increment="PATCH"), cwd=self.root)
                self.assertEqual(self.state(), before)
                generator = BumpGenerator(increment="PATCH", interactive=True)
                with (patch.object(generator, "prompt_select", side_effect=["Stable release", "Apply"]),
                      redirect_stdout(StringIO()), self.assertRaisesRegex(GitError, "Unstage")):
                    generator.generate_bump(cwd=self.root)
                self.assertEqual(self.state(), before)
                self.git("reset", "--", target)
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)

    def test_staged_gitlink_is_rejected_even_when_diff_ignores_submodules(self) -> None:
        old_commit = self.git("rev-parse", "HEAD^")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{old_commit},nested")
        self.git("commit", "-m", "chore: track gitlink")
        self.git("config", "diff.ignoreSubmodules", "all")
        plan = plan_bump(BumpOptions(increment="PATCH", create_tag=False), cwd=self.root)
        new_commit = self.git("rev-parse", "HEAD")
        self.git("update-index", "--cacheinfo", f"160000,{new_commit},nested")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        self.assertEqual(self.git("diff", "--cached", "--ignore-submodules=none", "--name-only"), "nested")
        before = self.state()
        with self.assertRaisesRegex(GitError, "Unstage"):
            run_bump(BumpOptions(increment="PATCH", create_tag=False), cwd=self.root)
        self.assertEqual(self.state(), before)
        with self.assertRaisesRegex(GitError, "Unstage"):
            apply_bump_plan(plan)
        self.assertEqual(self.state(), before)

    def test_intent_to_add_has_no_staged_content_to_absorb(self) -> None:
        path = self.root / "intent.txt"
        path.write_text("not staged for commit\n", encoding="utf-8")
        self.git("add", "--intent-to-add", "intent.txt")
        require_clean_index(self.root)
        plan = plan_bump(BumpOptions(increment="PATCH", create_tag=False), cwd=self.root)
        apply_bump_plan(plan)
        self.assertEqual(self.git("ls-tree", "--name-only", "HEAD", "intent.txt"), "")
        self.assertEqual(path.read_text(), "not staged for commit\n")

    def test_symlinked_core_snapshot_rejects_destination_edits_and_retargeting(self) -> None:
        config_path = self.root / ".cz.toml"
        destination = self.root / "policy.toml"
        config_path.rename(destination)
        config_path.symlink_to(destination.name)
        self.git("add", ".cz.toml", "policy.toml")
        self.git("commit", "-m", "chore: symlink release config")
        original = destination.read_text(encoding="utf-8")
        for change in ("contents", "destination"):
            with self.subTest(change=change):
                plan = plan_bump(BumpOptions(increment="PATCH", create_tag=False), cwd=self.root)
                if change == "contents":
                    destination.write_text(original + "# concurrent important customization\n", encoding="utf-8")
                else:
                    replacement = self.root / "replacement.toml"
                    replacement.write_text(original, encoding="utf-8")
                    config_path.unlink()
                    config_path.symlink_to(replacement.name)
                before = self.state()
                with (self.assertRaisesRegex(GitError, "stale"),
                      patch("git_tools.generators.bumpgen.engine.git_add") as add):
                    apply_bump_plan(plan)
                add.assert_not_called()
                self.assertEqual(self.state(), before)
                if change == "contents":
                    self.assertIn("concurrent important customization", destination.read_text())
                    destination.write_text(original, encoding="utf-8")
                else:
                    config_path.unlink()
                    config_path.symlink_to(destination.name)
                    replacement.unlink()

    def test_ignored_metadata_symlink_loops_preserve_auxiliary_policy(self) -> None:
        config_path = self.root / ".cz.toml"
        original = config_path.read_text(encoding="utf-8")
        for mode in ("enabled", "disabled", "excluded"):
            with self.subTest(mode=mode):
                if mode == "disabled":
                    config_path.write_text(original + "sync_auxiliary = false\n", encoding="utf-8")
                if mode == "excluded":
                    directory = self.root / "node_modules"
                    directory.mkdir()
                    loop = directory / "package.json"
                else:
                    loop = self.root / "package.json"
                    loop.unlink()
                loop.symlink_to(loop.name)
                before = self.state()
                output = StringIO()
                with redirect_stdout(output):
                    result = run_bump(BumpOptions(increment="PATCH", dry_run=True), cwd=self.root)
                self.assertEqual(str(result), "1.2.4")
                self.assertEqual(self.state(), before)
                plan = plan_bump(BumpOptions(increment="PATCH", create_tag=False), cwd=self.root)
                self.assertNotIn(loop, [update.path for update in plan.updates])
                apply_bump_plan(plan)
                self.assertEqual(config_path.read_text().count('version = "1.2.4"'), 1)
                self.assertTrue(loop.is_symlink())
                self.assertEqual(loop.readlink(), Path(loop.name))
                # Restore this disposable fixture for the next policy scenario.
                loop.unlink()
                if mode == "excluded":
                    directory.rmdir()
                self.git("reset", "--hard", "HEAD^")
                self.assertEqual(config_path.read_text(), original)

    def test_apply_refuses_stale_head_file_config_tag_settings_and_discovery(self) -> None:
        for change in ("head", "branch", "file", "config", "tag", "git", "new_target", "staged"):
            with self.subTest(change=change):
                plan = plan_bump(BumpOptions(), cwd=self.root)
                path = self.root / "pyproject.toml"
                if change == "head":
                    self.git("commit", "--allow-empty", "-m", "fix: concurrent")
                elif change == "branch":
                    self.git("checkout", "-b", "concurrent-branch")
                elif change == "file":
                    path.write_text(path.read_text() + "# concurrent\n")
                elif change == "config":
                    path = self.root / ".cz.toml"
                    path.write_text(path.read_text() + "# concurrent policy\n")
                elif change == "tag":
                    self.git("tag", "concurrent-tag")
                elif change == "git":
                    self.git("config", "tag.gpgSign", "true")
                elif change == "new_target":
                    (self.root / "new-app").mkdir()
                    (self.root / "new-app" / "package.json").write_text('{"version":"1.2.3"}')
                else:
                    (self.root / "staged.txt").write_text("work")
                    self.git("add", "staged.txt")
                before = self.state()
                with self.assertRaisesRegex(GitError, "stale|Unstage"):
                    apply_bump_plan(plan)
                self.assertEqual(self.state(), before)
                if change in ("file", "config"):
                    self.git("restore", str(path.relative_to(self.root)))
                elif change == "tag":
                    self.git("tag", "-d", "concurrent-tag")
                elif change == "git":
                    self.git("config", "tag.gpgSign", "false")
                elif change == "new_target":
                    (self.root / "new-app" / "package.json").unlink()
                    (self.root / "new-app").rmdir()
                elif change == "staged":
                    self.git("reset", "--", "staged.txt")
                    (self.root / "staged.txt").unlink()

    def test_changes_during_interactive_prompt_are_not_applied(self) -> None:
        generator = BumpGenerator(increment="PATCH", interactive=True)
        def select(message, choices, default):
            if "Choose action" in message:
                self.git("commit", "--allow-empty", "-m", "fix: concurrent")
                return "Apply"
            return "Stable release"
        before_files = self.state()[0]
        with patch.object(generator, "prompt_select", side_effect=select), self.assertRaisesRegex(GitError, "stale"):
            generator.generate_bump(cwd=self.root)
        self.assertEqual(self.state()[0], before_files)
        self.assertNotIn("v1.2.4", self.git("tag"))

    def test_history_permission_is_only_asked_for_truly_initial_history(self) -> None:
        self.git("tag", "-d", "v1.2.3")
        before = self.state()
        generator = BumpGenerator(increment="PATCH", interactive=True)
        with (patch.object(generator, "prompt_select", return_value="Stable release"),
              patch.object(generator, "prompt_confirm", return_value=False) as confirm):
            generator.generate_bump(cwd=self.root)
        self.assertEqual(confirm.call_count, 1)
        self.assertFalse(confirm.call_args.kwargs["default"])
        self.assertEqual(self.state(), before)
        # A prior bump anchor makes the permission unnecessary, even with no tags.
        self.git("commit", "--allow-empty", "-m", "bump: version 1.2.2 -> 1.2.3")
        with (patch.object(generator, "prompt_select", side_effect=["Stable release", "Cancel"]),
              patch.object(generator, "prompt_confirm") as confirm):
            generator.generate_bump(cwd=self.root)
        confirm.assert_not_called()
        self.git("tag", "unrelated-tag")
        # Remove the synthetic anchor to exercise inconsistent tagged history.
        self.git("reset", "--hard", "HEAD^")
        with (patch.object(generator, "prompt_select", return_value="Stable release"),
              patch.object(generator, "prompt_confirm") as confirm,
              self.assertRaisesRegex(ConfigError, "stale|rewritten")):
            generator.generate_bump(cwd=self.root)
        confirm.assert_not_called()

    def test_effective_git_signing_is_displayed_without_signing_prompt(self) -> None:
        self.git("config", "tag.gpgSign", "true")
        generator = BumpGenerator(increment="PATCH", interactive=True)
        output = StringIO()
        with (patch.object(generator, "prompt_select", side_effect=["Stable release", "Cancel"]),
              patch.object(generator, "prompt_confirm") as confirm, redirect_stdout(output)):
            generator.generate_bump(cwd=self.root)
        self.assertIn("Signed annotated tag (Git tag.gpgSign=true)", output.getvalue())
        confirm.assert_not_called()
        for respect, create, expected in ((False, True, "Lightweight"), (True, False, "No tag")):
            description = describe_git_tag_behavior(self.root, create_tag=create, annotated=False,
                                                   signed=False, message=None, respect_git_config=respect)
            self.assertIn(expected, description)

    def test_no_tag_and_annotated_tag_apply_parity(self) -> None:
        plan = plan_bump(BumpOptions(create_tag=False), cwd=self.root)
        self.assertEqual(plan.tag_behavior, "No tag")
        apply_bump_plan(plan)
        self.assertEqual(self.git("tag"), "v1.2.3")
        plan = plan_bump(BumpOptions(increment="PATCH", annotated_tag=True), cwd=self.root)
        self.assertEqual(plan.tag_behavior, "Annotated tag (unsigned)")
        apply_bump_plan(plan)
        self.assertEqual(self.git("cat-file", "-t", "v1.2.5"), "tag")
        self.assertEqual(self.git("rev-parse", "v1.2.5^{commit}"), self.git("rev-parse", "HEAD"))


if __name__ == "__main__":
    unittest.main()

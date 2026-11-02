"""Release-led regressions with ordinary files, mocked Git reads, and no commits."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
from io import StringIO
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

from git_tools.generators.bumpgen.cli import build_parser, main
from git_tools.generators.bumpgen.engine import (
    BumpOptions,
    _compute_bump,
    apply_bump_plan,
    plan_bump,
    print_bump_plan,
    run_bump,
)
from git_tools.generators.bumpgen.errors import ConfigError, GitError
from git_tools.generators.bumpgen.strategy import decide_version_strategy


class ReleaseTargetTests(unittest.TestCase):
    """No .git directory, repository initialization, or real Git operation is used."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict("os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": "true"})
        environment.start()
        self.addCleanup(environment.stop)
        self.denied = [
            self.start_patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")),
            self.start_patch("subprocess.Popen", side_effect=AssertionError("subprocess forbidden")),
            self.start_patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
        ]
        self.denied.extend(
            self.start_patch(f"git_tools.generators.bumpgen.engine.{name}",
                             side_effect=AssertionError(f"{name} forbidden"))
            for name in ("git_add", "git_commit", "git_tag", "run_command")
        )
        self.subject = self.start_patch("git_tools.generators.bumpgen.strategy.get_last_commit_message", return_value="fix: stabilize release")
        self.unique = self.start_patch("git_tools.generators.bumpgen.strategy.branch_has_unique_commits_since", return_value=(True, "origin/develop"))
        self.strategy_tags = self.start_patch("git_tools.generators.bumpgen.strategy.get_tag_names", return_value=["v0.1.0"])
        self.master = self.start_patch("git_tools.generators.bumpgen.strategy.load_version_from_refs", return_value="0.1.0")
        self.start_patch("git_tools.generators.bumpgen.rules.latest_commit_has_meaningful_changes", return_value=True)
        self.start_patch("git_tools.generators.bumpgen.engine.is_git_project", return_value=True)
        self.start_patch("git_tools.generators.bumpgen.engine.get_tag_names", return_value=["v0.1.0"])
        self.history = self.start_patch("git_tools.generators.bumpgen.engine.resolve_version_history_ref", return_value="mock-anchor")
        self.messages = self.start_patch("git_tools.generators.bumpgen.engine.get_commit_messages", return_value=["fix: stabilize release"])
        self.state = self.start_patch("git_tools.generators.bumpgen.engine._repository_state", return_value=("head", "release-branch", "tags", "git-config"))
        self.start_patch("git_tools.generators.bumpgen.engine.describe_git_tag_behavior", return_value="Signed annotated tag (mocked Git read)")
        self.start_patch("git_tools.generators.bumpgen.engine.require_clean_index", return_value=None)
        self.addCleanup(self.assert_no_mutations)
        self.write_fixture("0.2.0-alpha.1")

    def start_patch(self, name, *args, **kwargs):
        patcher = patch(name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def assert_no_mutations(self) -> None:
        for denied in self.denied:
            denied.assert_not_called()
        self.assertFalse((self.root / ".git").exists())

    def write_fixture(self, version: str, scheme: str = "semver2") -> None:
        (self.root / ".cz.toml").write_text(
            '[tool.commitizen]\n'
            f'version = "{version}"\n'
            f'version_scheme = "{scheme}"\n'
            'tag_format = "v$version"\n', encoding="utf-8",
        )
        (self.root / "pyproject.toml").write_text(
            f'[project]\nname = "demo"\nversion = "{version}"\n', encoding="utf-8",
        )
        (self.root / "package.json").write_text(
            f'{{"name":"demo","version":"{version}"}}\n', encoding="utf-8",
        )

    def snapshot(self) -> dict[Path, bytes]:
        return {path.relative_to(self.root): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    @contextmanager
    def deny_file_writes(self):
        with (patch.object(Path, "write_text", side_effect=AssertionError("file write forbidden")) as text,
              patch.object(Path, "write_bytes", side_effect=AssertionError("file write forbidden")) as binary):
            yield
            text.assert_not_called()
            binary.assert_not_called()

    def options(self, **changes) -> BumpOptions:
        return replace(BumpOptions(release_target="0.1.1", prerelease="rc", increment_mode="exact", yes=True), **changes)

    def decision_and_options(self, branch="release/0.1.1", flow="variant"):
        decision = decide_version_strategy(self.root, branch, flow=flow)
        self.assertFalse(decision.invalid, decision.error)
        self.assertFalse(decision.skip, decision.reason)
        options = BumpOptions(**vars(build_parser().parse_args(shlex.split(decision.args))))
        return decision, options

    def assert_computed(self, branch, expected, *, flow="variant", absolute=True):
        before = self.snapshot()
        with self.deny_file_writes():
            decision, options = self.decision_and_options(branch, flow)
            config, result, increment = _compute_bump(options, cwd=self.root)
        self.assertEqual(str(result), expected)
        self.assertEqual(result.scheme, config.current_version.scheme)
        self.assertEqual(options.release_target is not None, absolute)
        if absolute:
            self.assertEqual(decision.mode, "start-release-rc")
            self.assertEqual(".".join(map(str, result.release)), decision.release_target)
            self.assertIsNone(increment)
        self.assertEqual(self.snapshot(), before)
        self.history.assert_called()
        self.messages.assert_called_with(self.root, start_ref="mock-anchor")
        return decision, options

    def test_original_patch_mismatch_uses_absolute_target_in_both_schemes(self):
        for source, scheme, expected in (
            ("0.2.0-alpha.1", "semver2", "0.1.1-rc.0"),
            ("0.2.0-a1", "semver", "0.1.1-rc0"),
        ):
            with self.subTest(scheme=scheme):
                self.write_fixture(source, scheme)
                decision, _ = self.assert_computed("release/0.1.1", expected)
                self.assertEqual(decision.release_increment, "PATCH")

    def test_original_minor_mismatch_uses_absolute_target_in_both_schemes(self):
        for source, scheme, expected in (
            ("0.3.0-alpha.0", "semver2", "0.2.0-rc.0"),
            ("0.3.0-a0", "semver", "0.2.0-rc0"),
        ):
            with self.subTest(scheme=scheme):
                self.write_fixture(source, scheme)
                decision, _ = self.assert_computed("release/0.2.0", expected)
                self.assertEqual(decision.release_increment, "MINOR")

    def test_beta_can_retarget_and_major_target_remains_absolute(self):
        for source, target, expected in (
            ("0.3.0-beta.2", "0.2.0", "0.2.0-rc.0"),
            ("0.2.0-alpha.1", "1.0.0", "1.0.0-rc.0"),
        ):
            with self.subTest(source=source, target=target):
                self.write_fixture(source)
                self.assert_computed(f"release/{target}", expected)

    def test_short_form_beta_retargets_without_changing_scheme(self):
        self.write_fixture("0.3.0-b2", "semver")
        self.assert_computed("release/0.2.0", "0.2.0-rc0")

    def test_stable_master_can_open_forward_target_with_configured_scheme(self):
        for scheme, expected in (("semver2", "0.2.0-rc.0"), ("semver", "0.2.0-rc0")):
            with self.subTest(scheme=scheme):
                self.write_fixture("0.1.0", scheme)
                self.assert_computed("release/0.2.0", expected)

    def test_same_line_promotion_and_continuation_keep_existing_paths(self):
        for source, scheme, expected in (
            ("0.2.0-alpha.1", "semver2", "0.2.0-rc.0"),
            ("0.2.0-beta.1", "semver2", "0.2.0-rc.0"),
            ("0.2.0-rc.2", "semver2", "0.2.0-rc.3"),
            ("0.2.0-a1", "semver", "0.2.0-rc0"),
            ("0.2.0-rc2", "semver", "0.2.0-rc3"),
        ):
            with self.subTest(source=source):
                self.write_fixture(source, scheme)
                self.assert_computed("release/0.2.0", expected, absolute=False)

    def test_variant_rejects_different_rc_and_stable_nonmaster_sources(self):
        for source in ("0.3.0-rc.1", "0.1.1-rc.1", "0.3.0", "0.1.1", "0.0.1"):
            with self.subTest(source=source):
                self.write_fixture(source)
                before = self.snapshot()
                with self.deny_file_writes():
                    decision = decide_version_strategy(self.root, "release/0.2.0", flow="variant")
                self.assertTrue(decision.invalid)
                self.assertEqual(decision.args, "")
                self.assertEqual(self.snapshot(), before)
        self.history.assert_not_called()

    def test_variant_rejects_stable_on_selected_line_as_before(self):
        self.write_fixture("0.2.0")
        decision = decide_version_strategy(self.root, "release/0.2.0", flow="variant")
        self.assertTrue(decision.invalid)
        self.assertIn("must carry a prerelease", decision.error)

    def test_variant_rejects_noncanonical_and_nonnext_branch_targets(self):
        for branch in ("release/00.2.0", "release/0.02.0", "release/٠.٢.٠", "release/v0.2.0",
                       "release/0.2", "release/0.2.0-rc.0", "release/0.2.0\n", "release/0.4.0"):
            with self.subTest(branch=branch):
                decision = decide_version_strategy(self.root, branch, flow="variant")
                self.assertTrue(decision.invalid)
                self.assertEqual(decision.args, "")

    def test_existing_release_gates_do_not_emit_target_operation(self):
        for subject, unique in (("fix: stabilize", False), ("ordinary note", True),
                                ("bump: version 0.1.0 -> 0.2.0-alpha.1", True),
                                ("dvc: commit experiment abc123", True),
                                ("Release 0.2.0", True)):
            with self.subTest(subject=subject, unique=unique):
                self.subject.return_value = subject
                self.unique.return_value = (unique, "origin/develop")
                decision = decide_version_strategy(self.root, "release/0.1.1", flow="variant")
                self.assertTrue(decision.skip)
                self.assertEqual(decision.args, "")

    def test_classic_release_promotion_and_mismatch_behavior_is_unchanged(self):
        self.assert_computed("release/0.2.0", "0.2.0-rc.0", flow="classic", absolute=False)
        decision = decide_version_strategy(self.root, "release/0.1.1", flow="classic")
        self.assertTrue(decision.invalid)
        self.assertIn("does not match", decision.error)

    def test_other_branch_calculation_paths_do_not_use_absolute_targets(self):
        for source, branch, subject, expected in (
            ("0.2.0-alpha.1", "develop", "fix: develop fix", "0.2.0-alpha.2"),
            ("0.2.0-alpha.1", "develop", "Start 0.3.0", "0.3.0-alpha.0"),
            ("0.3.0-alpha.1", "develop", "Backmerge Release 0.2.0", "0.3.0-alpha.2"),
            ("0.1.0", "develop", "Backmerge Release 0.1.1", "0.1.1"),
            ("0.1.0", "hotfix/repair", "fix: hotfix", "0.1.1-rc.0"),
            ("0.1.1-rc.2", "hotfix/repair", "fix: hotfix", "0.1.1-rc.3"),
            ("0.2.0-rc.2", "master", "Release 0.2.0", "0.2.0"),
            ("0.3.0-alpha.1", "release/0.2.0", "chore: merge develop for backmerge", "0.3.0-alpha.2"),
        ):
            with self.subTest(branch=branch, subject=subject):
                self.write_fixture(source)
                self.subject.return_value = subject
                self.assert_computed(branch, expected, absolute=False)

    def test_master_bootstrap_still_uses_ordinary_increment(self):
        self.write_fixture("0.0.1")
        self.strategy_tags.return_value = []
        self.subject.return_value = "Release 0.1.0"
        self.assert_computed("master", "0.1.0", absolute=False)

    def test_ordinary_linear_and_exact_math_is_unchanged_without_target(self):
        for scheme, source, linear, exact in (
            ("semver2", "0.2.0-alpha.1", "0.2.0-rc.0", "0.2.1-rc.0"),
            ("semver", "0.2.0-a1", "0.2.0-rc0", "0.2.1-rc0"),
        ):
            self.write_fixture(source, scheme)
            for mode, expected in (("linear", linear), ("exact", exact)):
                with self.subTest(scheme=scheme, mode=mode):
                    options = BumpOptions(increment="PATCH", prerelease="rc", increment_mode=mode)
                    _, actual, increment = _compute_bump(options, cwd=self.root)
                    self.assertEqual(str(actual), expected)
                    self.assertEqual(increment, "PATCH")

    def test_ordinary_major_version_zero_configuration_is_unchanged(self):
        self.write_fixture("0.1.0")
        path = self.root / ".cz.toml"
        path.write_text(path.read_text() + "major_version_zero = true\n", encoding="utf-8")
        self.messages.return_value = ["feat!: breaking change"]
        _, actual, increment = _compute_bump(BumpOptions(), cwd=self.root)
        self.assertEqual((str(actual), increment), ("0.2.0", "MINOR"))

    def test_parser_rejects_noncanonical_target_spellings(self):
        for target in ("", "0.2", "v0.2.0", "00.2.0", "0.02.0", "0.2.00", "٠.٢.٠",
                       "０.２.０", "0.2.0-rc.0", "0.2.0+build", "0.2.0\n", " 0.2.0", "-1.2.0"):
            with self.subTest(target=target), redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                build_parser().parse_args([f"--release-target={target}"])

    def test_engine_rejects_noncanonical_targets_from_direct_options(self):
        for target in ("", "0.2", "v0.2.0", "00.2.0", "٠.٢.٠", "0.2.0-rc.0", "0.2.0+build", "0.2.0\n", 12):
            with self.subTest(target=target), self.assertRaisesRegex(ConfigError, "canonical ASCII"):
                _compute_bump(self.options(release_target=target), cwd=self.root)
        self.history.assert_not_called()

    def test_conflicting_target_options_fail_before_file_planning(self):
        for changes in ({"prerelease": None}, {"prerelease": "alpha"}, {"prerelease": "beta"},
                        {"increment_mode": "linear"}, {"increment": "PATCH"},
                        {"default_increment": "PATCH"}, {"allow_no_commit": True}):
            with self.subTest(changes=changes):
                before = self.snapshot()
                with (self.deny_file_writes(),
                      patch("git_tools.generators.bumpgen.engine.plan_version_file_updates") as files,
                      self.assertRaises(ConfigError)):
                    plan_bump(self.options(**changes), cwd=self.root)
                files.assert_not_called()
                self.assertEqual(self.snapshot(), before)
        self.history.assert_not_called()

    def test_direct_target_operation_rejects_same_line_rc_retarget_and_nonforward_stable(self):
        for source, target in (("0.2.0-alpha.1", "0.2.0"), ("0.2.0-rc.2", "0.2.0"),
                               ("0.3.0-rc.2", "0.2.0"), ("0.1.1-rc.0", "0.2.0"),
                               ("0.3.0", "0.2.0"), ("0.2.0", "0.2.0")):
            with self.subTest(source=source, target=target):
                self.write_fixture(source)
                before = self.snapshot()
                with (self.deny_file_writes(),
                      patch("git_tools.generators.bumpgen.engine.plan_version_file_updates") as files,
                      self.assertRaises(ConfigError)):
                    plan_bump(self.options(release_target=target), cwd=self.root)
                files.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_history_refusal_is_preserved_before_target_calculation_or_planning(self):
        before = self.snapshot()
        self.history.side_effect = ConfigError("stale or rewritten current history")
        with (self.deny_file_writes(),
              patch("git_tools.generators.bumpgen.engine.plan_version_file_updates") as files,
              self.assertRaisesRegex(ConfigError, "stale or rewritten")):
            plan_bump(self.options(), cwd=self.root)
        files.assert_not_called()
        self.messages.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_existing_target_tag_refuses_before_planning_unless_tagging_disabled(self):
        for source, scheme, target_tag, expected in (
            ("0.2.0-alpha.1", "semver2", "v0.1.1-rc.0", "0.1.1-rc.0"),
            ("0.2.0-a1", "semver", "v0.1.1-rc0", "0.1.1-rc0"),
        ):
            with self.subTest(scheme=scheme):
                self.write_fixture(source, scheme)
                before = self.snapshot()
                with (self.deny_file_writes(),
                      patch("git_tools.generators.bumpgen.engine.get_tag_names", return_value=["v0.1.0", target_tag]),
                      patch("git_tools.generators.bumpgen.engine.plan_version_file_updates") as files):
                    with self.assertRaisesRegex(GitError, "already exists"):
                        plan_bump(self.options(), cwd=self.root)
                    files.assert_not_called()
                    _, actual, _ = _compute_bump(self.options(create_tag=False), cwd=self.root)
                    self.assertEqual(str(actual), expected)
                self.assertEqual(self.snapshot(), before)

    def test_target_operation_does_not_autodetect_a_different_tuple(self):
        self.messages.return_value = ["feat!: a larger change"]
        with patch("git_tools.generators.bumpgen.engine.detect_increment", side_effect=AssertionError("must not autodetect")):
            _, actual, increment = _compute_bump(self.options(), cwd=self.root)
        self.assertEqual(str(actual), "0.1.1-rc.0")
        self.assertIsNone(increment)

    def test_get_next_is_write_free_and_does_not_plan_files(self):
        before = self.snapshot()
        output = StringIO()
        with (self.deny_file_writes(), redirect_stdout(output),
              patch("git_tools.generators.bumpgen.engine.plan_version_file_updates", side_effect=AssertionError("must not plan")),
              patch("git_tools.generators.bumpgen.engine._source_files", side_effect=AssertionError("must not snapshot files"))):
            actual = run_bump(self.options(get_next=True), cwd=self.root)
        self.assertEqual(str(actual), "0.1.1-rc.0")
        self.assertEqual(output.getvalue(), "0.1.1-rc.0\n")
        self.assertEqual(self.snapshot(), before)

    def test_preview_plan_version_message_tag_and_updates_agree_without_writes(self):
        before = self.snapshot()
        with self.deny_file_writes():
            plan = plan_bump(self.options(), cwd=self.root)
            output = StringIO()
            with redirect_stdout(output):
                print_bump_plan(plan)
        self.assertEqual(str(plan.new_version), "0.1.1-rc.0")
        self.assertEqual(plan.options.release_target, "0.1.1")
        self.assertIn("0.2.0-alpha.1 → 0.1.1-rc.0", plan.message)
        self.assertEqual(plan.tag_name, "v0.1.1-rc.0")
        self.assertEqual({item.path.name for item in plan.updates}, {".cz.toml", "pyproject.toml", "package.json"})
        for item in plan.updates:
            self.assertIn("0.1.1-rc.0", item.after)
            self.assertNotIn("0.2.0-alpha.1", item.after)
        self.assertNotIn("increment detected:", output.getvalue())
        self.assertIn("tag to create: v0.1.1-rc.0", output.getvalue())
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(FrozenInstanceError):
            plan.options.release_target = "1.0.0"

    def test_dry_run_uses_the_same_absolute_calculation_without_mutation(self):
        before = self.snapshot()
        with self.deny_file_writes(), redirect_stdout(StringIO()):
            actual = run_bump(self.options(dry_run=True), cwd=self.root)
        self.assertEqual(str(actual), "0.1.1-rc.0")
        self.assertEqual(self.snapshot(), before)

    def test_changes_during_planning_fail_before_mutation(self):
        self.state.side_effect = [("before",), ("after",)]
        before = self.snapshot()
        with self.deny_file_writes(), self.assertRaisesRegex(GitError, "changed while preparing"):
            plan_bump(self.options(), cwd=self.root)
        self.assertEqual(self.snapshot(), before)

    def test_apply_refuses_stale_repository_or_files_without_recomputing(self):
        for change in ("head", "symbolic-branch", "tags", "git-config", "source-bytes", "new-discovery-file"):
            with self.subTest(change=change):
                self.write_fixture("0.2.0-alpha.1")
                optional = self.root / "package-lock.json"
                optional.unlink(missing_ok=True)
                self.state.return_value = ("head", "release-branch", "tags", "git-config")
                plan = plan_bump(self.options(), cwd=self.root)
                if change == "source-bytes":
                    path = self.root / ".cz.toml"
                    path.write_text(path.read_text() + "# concurrent edit\n", encoding="utf-8")
                elif change == "new-discovery-file":
                    optional.write_text('{}\n', encoding="utf-8")
                else:
                    self.state.return_value = ("changed", change)
                before = self.snapshot()
                with (self.deny_file_writes(),
                      patch("git_tools.generators.bumpgen.engine._compute_bump", side_effect=AssertionError("must not recompute")),
                      self.assertRaisesRegex(GitError, "stale")):
                    apply_bump_plan(plan)
                self.assertEqual(self.snapshot(), before)

    def test_staged_index_refusal_still_precedes_direct_and_planned_mutation(self):
        plan = plan_bump(self.options(), cwd=self.root)
        before = self.snapshot()
        with (self.deny_file_writes(),
              patch("git_tools.generators.bumpgen.engine.require_clean_index", side_effect=GitError("Unstage changes")),
              patch("git_tools.generators.bumpgen.engine._compute_bump", side_effect=AssertionError("must not recompute"))):
            with self.assertRaisesRegex(GitError, "Unstage"):
                run_bump(self.options(), cwd=self.root)
            with self.assertRaisesRegex(GitError, "Unstage"):
                apply_bump_plan(plan)
        self.assertEqual(self.snapshot(), before)

    def test_module_main_maps_release_target_and_get_next(self):
        output = StringIO()
        with (patch.object(Path, "cwd", return_value=self.root), self.deny_file_writes(),
              redirect_stdout(output)):
            code = main(["--yes", "--release-target", "0.1.1", "--prerelease", "rc",
                         "--increment-mode", "exact", "--get-next"])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "0.1.1-rc.0\n")

    def test_module_main_reports_invalid_combinations_without_writes(self):
        error = StringIO()
        before = self.snapshot()
        with (patch.object(Path, "cwd", return_value=self.root), self.deny_file_writes(),
              redirect_stderr(error)):
            code = main(["--release-target", "0.1.1", "--get-next"])
        self.assertEqual(code, 1)
        self.assertIn("requires --prerelease rc --increment-mode exact", error.getvalue())
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.generators.bumpgen import (
    BOOTSTRAP_RELEASE_SUBJECTS,
    BumpOptions,
    canonicalize_package_name,
    ConsistencyError,
    ConfigError,
    Version,
    build_git_tag_args,
    build_parser,
    detect_increment,
    detect_scheme,
    find_version_bump_commit,
    format_release_line_prerelease,
    get_git_bool_config,
    has_bootstrap_commitizen_version,
    is_bootstrap_release_subject,
    is_bump_eligible,
    load_bump_config,
    parse_bump_subject_target_version,
    plan_version_file_updates,
    release_tuple,
    resolve_git_tag_args,
    run_bump,
    version_to_uv_version,
    SectionVersionTarget,
    UvLockVersionTarget,
    load_current_version_for_strategy,
)


class DetectIncrementTests(unittest.TestCase):
    def test_detects_highest_increment_from_conventional_commits(self) -> None:
        commits = [
            "fix: patch",
            "feat: minor",
            "docs: ignored",
            "feat!: breaking",
        ]
        self.assertEqual(
            detect_increment(commits, major_version_zero=False),
            "MAJOR",
        )

    def test_major_version_zero_downgrades_breaking_to_minor(self) -> None:
        commits = ["feat!: breaking"]
        self.assertEqual(
            detect_increment(commits, major_version_zero=True),
            "MINOR",
        )

    def test_default_increment_applies_to_other_conventional_types(self) -> None:
        commits = ["style(ui): align spacing"]
        self.assertEqual(
            detect_increment(
                commits,
                major_version_zero=False,
                default_increment="PATCH",
            ),
            "PATCH",
        )

    def test_default_increment_does_not_override_higher_priority_rules(self) -> None:
        commits = ["docs: update guide", "feat: add export"]
        self.assertEqual(
            detect_increment(
                commits,
                major_version_zero=False,
                default_increment="PATCH",
            ),
            "MINOR",
        )

    def test_default_increment_ignores_non_conventional_messages(self) -> None:
        commits = ["Merge branch 'develop' into master"]
        self.assertIsNone(
            detect_increment(
                commits,
                major_version_zero=False,
                default_increment="PATCH",
            )
        )

    def test_default_increment_ignores_dvc_experiment_commits(self) -> None:
        commits = ["dvc: commit experiment 7cef9647b1cb8f94"]
        self.assertIsNone(
            detect_increment(
                commits,
                major_version_zero=False,
                default_increment="PATCH",
            )
        )

    def test_dvc_experiment_commit_is_not_bump_eligible(self) -> None:
        self.assertFalse(is_bump_eligible("dvc: commit experiment 7cef9647b1cb8f94"))
        self.assertTrue(is_bump_eligible("dvc: document experiment workflow"))

    def test_parser_accepts_default_increment(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args(["--default-increment", "PATCH"])
        self.assertEqual(namespace.default_increment, "PATCH")


class BootstrapMetadataTests(unittest.TestCase):
    def test_bootstrap_release_subject_accepts_both_cosmetic_labels(self) -> None:
        self.assertEqual(
            BOOTSTRAP_RELEASE_SUBJECTS,
            frozenset({"Release 0.0.1", "Release 0.1.0"}),
        )
        self.assertTrue(is_bootstrap_release_subject("Release 0.0.1"))
        self.assertTrue(is_bootstrap_release_subject("Release 0.1.0"))
        self.assertFalse(is_bootstrap_release_subject("Release 1.0.0"))

    def test_bootstrap_release_subject_accepts_github_pr_suffix(self) -> None:
        self.assertTrue(is_bootstrap_release_subject("Release 0.1.0 (#7)"))
        self.assertFalse(is_bootstrap_release_subject("Release 1.0.0 (#7)"))

    def test_bootstrap_commitizen_version_requires_dot_cz_toml_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertFalse(has_bootstrap_commitizen_version(root))

            (root / ".cz.toml").write_text(
                "[tool.commitizen]\nversion = \"0.0.1\"\n",
                encoding="utf-8",
            )
            self.assertTrue(has_bootstrap_commitizen_version(root))

            (root / ".cz.toml").write_text(
                "[tool.commitizen]\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )
            self.assertFalse(has_bootstrap_commitizen_version(root))


class OptionalDependencyImportTests(unittest.TestCase):
    def test_bumpgen_imports_without_questionary_for_strategy_usage(self) -> None:
        module_name = "git_tools.generators.bumpgen"
        base_name = "git_tools.generators.base"
        questionary_name = "questionary"
        original_modules = {
            name: sys.modules.get(name)
            for name in (module_name, base_name, questionary_name)
        }

        for name in (module_name, base_name, questionary_name):
            sys.modules.pop(name, None)

        builtin_import = __import__

        def fake_import(
            name: str,
            globals: dict[str, object] | None = None,
            locals: dict[str, object] | None = None,
            fromlist: tuple[str, ...] = (),
            level: int = 0,
        ) -> object:
            if name == questionary_name:
                raise ModuleNotFoundError(
                    "No module named 'questionary'",
                    name=questionary_name,
                )
            return builtin_import(name, globals, locals, fromlist, level)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                module = importlib.import_module(module_name)

            self.assertTrue(hasattr(module, "decide_version_strategy"))

            generator = module.BumpGenerator(interactive=False)
            self.assertFalse(generator._interactive)

            interactive_generator = module.BumpGenerator(interactive=True)
            with self.assertRaisesRegex(
                ModuleNotFoundError,
                "Optional dependency 'questionary' is required",
            ):
                interactive_generator._build_options()
        finally:
            for name in (module_name, base_name, questionary_name):
                sys.modules.pop(name, None)
            for name, module in original_modules.items():
                if module is not None:
                    sys.modules[name] = module


class VersionTests(unittest.TestCase):
    def test_linear_mode_finalizes_prerelease_without_bumping_patch(self) -> None:
        current = Version.parse("2.0.0-beta.0")
        self.assertEqual(str(current.bump("PATCH")), "2.0.0")

    def test_exact_mode_bumps_patch_from_prerelease(self) -> None:
        current = Version.parse("2.0.0-beta.0")
        self.assertEqual(
            str(current.bump("PATCH", exact_increment=True)),
            "2.0.1",
        )

    def test_linear_mode_keeps_higher_prerelease_phase(self) -> None:
        current = Version.parse("2.0.0-beta.0")
        self.assertEqual(
            str(current.bump("MINOR", prerelease="alpha")),
            "2.0.0-beta.1",
        )

    def test_uv_lock_version_conversion_uses_package_form(self) -> None:
        self.assertEqual(version_to_uv_version("0.2.0-alpha.15"), "0.2.0a15")
        self.assertEqual(version_to_uv_version("0.2.0-beta.2"), "0.2.0b2")
        self.assertEqual(version_to_uv_version("0.2.0-rc.3"), "0.2.0rc3")
        self.assertEqual(version_to_uv_version("0.2.0"), "0.2.0")

    def test_package_name_canonicalization_matches_uv_lock_style(self) -> None:
        self.assertEqual(canonicalize_package_name("Git_Tools"), "git-tools")


class VersionTargetApplyTests(unittest.TestCase):
    def test_section_target_preserves_crlf_line_endings(self) -> None:
        target = SectionVersionTarget(
            path=Path("pyproject.toml"),
            label="project.version",
            section_header="[project]",
        )

        updated, changed = target.apply(
            '[project]\r\nname = "git-tools"\r\nversion = "0.2.0-alpha.12"\r\n',
            current_version="0.2.0-alpha.12",
            new_version="0.2.0-alpha.16",
            check_consistency=True,
        )

        self.assertTrue(changed)
        self.assertEqual(
            updated,
            '[project]\r\nname = "git-tools"\r\nversion = "0.2.0-alpha.16"\r\n',
        )

    def test_uv_lock_target_preserves_lf_line_endings(self) -> None:
        target = UvLockVersionTarget(
            path=Path("uv.lock"),
            label="uv.lock",
            package_name="git-tools",
        )

        updated, changed = target.apply(
            '[[package]]\nname = "git-tools"\nversion = "0.2.0a12"\nsource = { registry = "https://example.test" }\n',
            current_version="0.2.0-alpha.12",
            new_version="0.2.0-alpha.16",
            check_consistency=True,
        )

        self.assertTrue(changed)
        self.assertEqual(
            updated,
            '[[package]]\nname = "git-tools"\nversion = "0.2.0a16"\nsource = { registry = "https://example.test" }\n',
        )

    def test_uv_lock_target_preserves_crlf_line_endings(self) -> None:
        target = UvLockVersionTarget(
            path=Path("uv.lock"),
            label="uv.lock",
            package_name="git-tools",
        )

        updated, changed = target.apply(
            '[[package]]\r\nname = "git-tools"\r\nversion = "0.2.0a12"\r\nsource = { registry = "https://example.test" }\r\n',
            current_version="0.2.0-alpha.12",
            new_version="0.2.0-alpha.16",
            check_consistency=True,
        )

        self.assertTrue(changed)
        self.assertEqual(
            updated,
            '[[package]]\r\nname = "git-tools"\r\nversion = "0.2.0a16"\r\nsource = { registry = "https://example.test" }\r\n',
        )


class GitTagArgsTests(unittest.TestCase):
    def test_lightweight_tags_respect_git_config_by_default(self) -> None:
        self.assertEqual(
            build_git_tag_args(
                "1.2.3",
                annotated=False,
                signed=False,
                message=None,
                respect_git_config=True,
            ),
            ["git", "tag", "1.2.3"],
        )

    def test_lightweight_tags_can_ignore_git_config_explicitly(self) -> None:
        self.assertEqual(
            build_git_tag_args(
                "1.2.3",
                annotated=False,
                signed=False,
                message=None,
                respect_git_config=False,
            ),
            ["git", "-c", "tag.gpgSign=false", "tag", "1.2.3"],
        )

    def test_signed_tags_remain_explicit(self) -> None:
        self.assertEqual(
            build_git_tag_args(
                "1.2.3",
                annotated=False,
                signed=True,
                message=None,
                respect_git_config=False,
            ),
            ["git", "tag", "-s", "1.2.3", "-m", "1.2.3"],
        )

    def test_git_config_signed_tags_become_explicit_to_avoid_editor_hang(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("git_tools.generators.bumpgen.get_git_bool_config", return_value=True):
                self.assertEqual(
                    resolve_git_tag_args(
                        root,
                        "1.2.3",
                        annotated=False,
                        signed=False,
                        message=None,
                        respect_git_config=True,
                    ),
                    ["git", "tag", "-s", "1.2.3", "-m", "1.2.3"],
                )


class ConfigAndUpdateTests(unittest.TestCase):
    def test_auto_source_prefers_commitizen_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\nversion = \"0.2.0-alpha.15\"\n",
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"git-tools\"\nversion = \"0.2.0-alpha.12\"\n",
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                "[[package]]\nname = \"git-tools\"\nversion = \"0.2.0a12\"\n",
                encoding="utf-8",
            )

            config = load_bump_config(root)

            self.assertEqual(config.current_version_text, "0.2.0-alpha.15")
            self.assertEqual(len(config.version_targets), 3)

    def test_consistency_check_heals_mismatched_auxiliary_versions_when_commitizen_is_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cz_path = root / ".cz.toml"
            pyproject_path = root / "pyproject.toml"
            uv_lock_path = root / "uv.lock"
            cz_path.write_text(
                "[tool.commitizen]\nversion = \"0.2.0-alpha.15\"\n",
                encoding="utf-8",
            )
            pyproject_path.write_text(
                "[project]\nname = \"git-tools\"\nversion = \"0.2.0-alpha.12\"\n",
                encoding="utf-8",
            )
            uv_lock_path.write_text(
                "[[package]]\nname = \"git-tools\"\nversion = \"0.2.0a12\"\n",
                encoding="utf-8",
            )

            config = load_bump_config(root)
            updates = plan_version_file_updates(
                config,
                Version.parse("0.2.0-alpha.16"),
                check_consistency=True,
            )

            self.assertIn('version = "0.2.0-alpha.16"', updates[cz_path])
            self.assertIn('version = "0.2.0-alpha.16"', updates[pyproject_path])
            self.assertIn('version = "0.2.0a16"', updates[uv_lock_path])

    def test_requires_dot_cz_toml_as_version_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"git-tools\"\nversion = \"0.2.0-alpha.15\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_bump_config(root)

    def test_mismatch_can_be_healed_when_consistency_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cz_path = root / ".cz.toml"
            pyproject_path = root / "pyproject.toml"
            uv_lock_path = root / "uv.lock"
            cz_path.write_text(
                "[tool.commitizen]\nversion = \"0.2.0-alpha.15\"\n",
                encoding="utf-8",
            )
            pyproject_path.write_text(
                "[project]\nname = \"git-tools\"\nversion = \"0.2.0-alpha.12\"\n",
                encoding="utf-8",
            )
            uv_lock_path.write_text(
                "[[package]]\nname = \"git-tools\"\nversion = \"0.2.0a12\"\n",
                encoding="utf-8",
            )

            config = load_bump_config(root)
            updates = plan_version_file_updates(
                config,
                Version.parse("0.2.0-alpha.16"),
                check_consistency=False,
            )

            self.assertIn('version = "0.2.0-alpha.16"', updates[cz_path])
            self.assertIn('version = "0.2.0-alpha.16"', updates[pyproject_path])
            self.assertIn('version = "0.2.0a16"', updates[uv_lock_path])

    def test_configured_semver_overrides_auto_detected_scheme_for_stable_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\n"
                'version_scheme = "semver"\n'
                'version = "1.2.3"\n',
                encoding="utf-8",
            )

            config = load_bump_config(root)

            self.assertEqual(config.current_version.scheme, "semver")
            bumped = config.current_version.bump("MINOR", prerelease="alpha")
            self.assertEqual(str(bumped), "1.3.0-a0")

    def test_configured_semver_resolves_to_semver(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\n"
                'version_scheme = "semver"\n'
                'version = "1.2.3"\n',
                encoding="utf-8",
            )

            config = load_bump_config(root)

            self.assertEqual(config.current_version.scheme, "semver")

    def test_configured_scheme_rejects_mismatched_prerelease(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\n"
                'version_scheme = "semver"\n'
                'version = "1.2.3-alpha.0"\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError) as ctx:
                load_bump_config(root)

            self.assertIn("disagrees", str(ctx.exception))

    def test_unsupported_configured_scheme_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\n"
                'version_scheme = "calver"\n'
                'version = "1.2.3"\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_bump_config(root)

    def test_strategy_reader_requires_dot_cz_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"git-tools\"\nversion = \"1.2.3\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_current_version_for_strategy(root)


class RunBumpTagSafetyTests(unittest.TestCase):
    def _init_repo(self, root: Path, version: str) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgSign", "false"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "config", "tag.gpgSign", "false"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        (root / ".cz.toml").write_text(
            (
                "[tool.commitizen]\n"
                'name = "cz_conventional_commits"\n'
                'tag_format = "$version"\n'
                'version_scheme = "semver2"\n'
                f'version = "{version}"\n'
            ),
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            (
                "[project]\n"
                'name = "example-project"\n'
                f'version = "{version}"\n'
            ),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)

    def test_yes_allows_initial_tag_when_repo_has_no_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_repo(root, "0.0.1")
            subprocess.run(
                ["git", "commit", "-m", "feat: initial release"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            new_version = run_bump(
                BumpOptions(yes=True, prerelease="alpha", dry_run=True),
                cwd=root,
            )

            self.assertEqual(str(new_version), "0.1.0-alpha.0")

    def test_yes_allows_initial_stable_bump_when_repo_has_no_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_repo(root, "0.0.1")
            subprocess.run(
                ["git", "commit", "-m", "Release 0.0.1"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            new_version = run_bump(
                BumpOptions(yes=True, increment="MINOR", dry_run=True),
                cwd=root,
            )

            self.assertEqual(str(new_version), "0.1.0")

    def test_yes_does_not_allow_missing_current_tag_when_tags_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_repo(root, "0.1.0")
            subprocess.run(
                ["git", "commit", "-m", "feat: initial release"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "tag", "0.1.0"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            (root / ".cz.toml").write_text(
                (
                    "[tool.commitizen]\n"
                    'name = "cz_conventional_commits"\n'
                    'tag_format = "$version"\n'
                    'version_scheme = "semver2"\n'
                    'version = "0.1.1-alpha.0"\n'
                ),
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                (
                    "[project]\n"
                    'name = "example-project"\n'
                    'version = "0.1.1-alpha.0"\n'
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "feat: continue work"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            with self.assertRaises(ConfigError) as ctx:
                run_bump(
                    BumpOptions(yes=True, prerelease="rc", dry_run=True),
                    cwd=root,
                )

            self.assertIn("No tag matching the current version was found", str(ctx.exception))
            self.assertIn("no prior bump commit", str(ctx.exception).lower())

    def test_run_bump_can_finalize_untagged_prerelease_without_creating_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_repo(root, "1.6.0-rc.0")
            subprocess.run(
                ["git", "commit", "-m", "fix: start release candidate"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "tag", "1.6.0-rc.0"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            (root / ".cz.toml").write_text(
                (
                    "[tool.commitizen]\n"
                    'name = "cz_conventional_commits"\n'
                    'tag_format = "$version"\n'
                    'version_scheme = "semver2"\n'
                    'version = "1.6.0-rc.1"\n'
                ),
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                (
                    "[project]\n"
                    'name = "example-project"\n'
                    'version = "1.6.0-rc.1"\n'
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "bump: version 1.6.0-rc.0 -> 1.6.0-rc.1"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            new_version = run_bump(
                BumpOptions(create_tag=False),
                cwd=root,
            )

            self.assertEqual(str(new_version), "1.6.0")
            tags = subprocess.run(
                ["git", "tag"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("1.6.0\n", tags)

    def test_run_bump_can_continue_from_last_bump_commit_when_current_version_has_no_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._init_repo(root, "0.1.0")
            subprocess.run(
                ["git", "commit", "-m", "feat: initial release"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "tag", "0.1.0"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            (root / ".cz.toml").write_text(
                (
                    "[tool.commitizen]\n"
                    'name = "cz_conventional_commits"\n'
                    'tag_format = "$version"\n'
                    'version_scheme = "semver2"\n'
                    'version = "0.2.0"\n'
                ),
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                (
                    "[project]\n"
                    'name = "example-project"\n'
                    'version = "0.2.0"\n'
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "bump: version 0.1.0 -> 0.2.0"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            (root / "next-cycle.txt").write_text("next develop cycle\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "feat: start the next cycle"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            new_version = run_bump(
                BumpOptions(
                    prerelease="alpha",
                    default_increment="PATCH",
                    create_tag=False,
                ),
                cwd=root,
            )

            self.assertEqual(str(new_version), "0.3.0-alpha.0")
            tags = subprocess.run(
                ["git", "tag"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertNotIn("0.3.0-alpha.0", tags)


class MultiSchemeVersionTests(unittest.TestCase):
    def test_semver2_scheme_is_default_for_stable(self) -> None:
        version = Version.parse("1.2.3")
        self.assertEqual(version.scheme, "semver2")
        self.assertEqual(str(version), "1.2.3")
        self.assertFalse(version.is_prerelease)

    def test_semver2_prerelease_round_trips(self) -> None:
        version = Version.parse("1.2.3-alpha.4")
        self.assertEqual(version.scheme, "semver2")
        self.assertEqual(version.prerelease_type, "alpha")
        self.assertEqual(version.prerelease_number, 4)
        self.assertEqual(str(version), "1.2.3-alpha.4")
        self.assertEqual(version.prerelease, "alpha.4")

    def test_semver_prerelease_round_trips(self) -> None:
        version = Version.parse("1.2.3-a4")
        self.assertEqual(version.scheme, "semver")
        self.assertEqual(version.prerelease_type, "alpha")
        self.assertEqual(version.prerelease_number, 4)
        self.assertEqual(str(version), "1.2.3-a4")
        self.assertEqual(version.prerelease, "a4")

    def test_semver_b_short_maps_to_beta(self) -> None:
        version = Version.parse("2.0.0-b1")
        self.assertEqual(version.prerelease_type, "beta")
        self.assertEqual(str(version), "2.0.0-b1")

    def test_semver_rc_short_maps_to_rc(self) -> None:
        version = Version.parse("2.0.0-rc5")
        self.assertEqual(version.prerelease_type, "rc")
        self.assertEqual(str(version), "2.0.0-rc5")

    def test_invalid_version_raises_config_error(self) -> None:
        for value in ("not-a-version", "1.2", "1.2.3-foo.0", "1.2.3a0", "1.2.3-alpha0"):
            with self.subTest(value=value):
                with self.assertRaises(ConfigError):
                    Version.parse(value)

    def test_bump_preserves_semver_scheme(self) -> None:
        current = Version.parse("1.0.0-b0")
        bumped = current.bump("PATCH", prerelease="beta")
        self.assertEqual(bumped.scheme, "semver")
        self.assertEqual(str(bumped), "1.0.0-b1")

    def test_bump_finalizes_prerelease_per_scheme(self) -> None:
        for current_text, expected in (
            ("1.0.0-alpha.0", "1.0.0"),
            ("1.0.0-a0", "1.0.0"),
        ):
            with self.subTest(current=current_text):
                self.assertEqual(
                    str(Version.parse(current_text).bump("PATCH")),
                    expected,
                )

    def test_bump_advances_phase_per_scheme(self) -> None:
        cases = [
            ("1.0.0-alpha.0", "rc", "1.0.0-rc.0"),
            ("1.0.0-a0", "rc", "1.0.0-rc0"),
            ("1.0.0-alpha.2", "beta", "1.0.0-beta.0"),
            ("1.0.0-a2", "beta", "1.0.0-b0"),
        ]
        for current_text, channel, expected in cases:
            with self.subTest(current=current_text, channel=channel):
                bumped = Version.parse(current_text).bump(None, prerelease=channel)
                self.assertEqual(str(bumped), expected)

    def test_release_tuple_handles_supported_schemes(self) -> None:
        for text in ("1.2.3", "1.2.3-alpha.0", "1.2.3-a0"):
            with self.subTest(text=text):
                self.assertEqual(release_tuple(text), (1, 2, 3))

    def test_detect_scheme_returns_none_for_unsupported_values(self) -> None:
        self.assertEqual(detect_scheme("0.1.0-alpha.0"), "semver2")
        self.assertEqual(detect_scheme("0.1.0-a0"), "semver")
        self.assertIsNone(detect_scheme("0.1.0a0"))
        self.assertIsNone(detect_scheme("xxx"))

    def test_uv_conversion_accepts_supported_schemes(self) -> None:
        self.assertEqual(version_to_uv_version("0.2.0-alpha.15"), "0.2.0a15")
        self.assertEqual(version_to_uv_version("0.2.0-a15"), "0.2.0a15")
        self.assertEqual(version_to_uv_version("0.2.0"), "0.2.0")

    def test_bump_subject_pattern_accepts_supported_schemes(self) -> None:
        for subject, expected in (
            ("bump: version 1.0.0-alpha.0 → 1.0.0-alpha.1", "1.0.0-alpha.1"),
            ("bump: version 1.0.0-a0 → 1.0.0-a1", "1.0.0-a1"),
            ("bump: version 1.0.0-a0 -> 1.0.0-a1", "1.0.0-a1"),
        ):
            with self.subTest(subject=subject):
                self.assertEqual(parse_bump_subject_target_version(subject), expected)

    def test_format_release_line_prerelease_respects_scheme(self) -> None:
        self.assertEqual(
            format_release_line_prerelease((1, 2, 0), "alpha", 0, scheme="semver2"),
            "1.2.0-alpha.0",
        )
        self.assertEqual(
            format_release_line_prerelease((1, 2, 0), "alpha", 0, scheme="semver"),
            "1.2.0-a0",
        )


class MultiSchemeRunBumpTests(unittest.TestCase):
    def _seed_repo(self, root: Path, version: str, scheme_label: str) -> None:
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
        for key, value in (
            ("user.name", "Test User"),
            ("user.email", "test@example.com"),
            ("commit.gpgSign", "false"),
            ("tag.gpgSign", "false"),
        ):
            subprocess.run(
                ["git", "config", key, value],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        (root / ".cz.toml").write_text(
            (
                "[tool.commitizen]\n"
                "name = \"cz_conventional_commits\"\n"
                "tag_format = \"$version\"\n"
                f"version_scheme = \"{scheme_label}\"\n"
                f"version = \"{version}\"\n"
            ),
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            f"[project]\nname = \"example-project\"\nversion = \"{version}\"\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True, text=True)

    def test_find_version_bump_commit_accepts_semver_subject(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root, "0.1.0-a1", "semver")
            subprocess.run(
                ["git", "commit", "-m", "bump: version 0.1.0-a0 -> 0.1.0-a1"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )

            bump_commit = find_version_bump_commit(root, "0.1.0-a1")

            self.assertIsNotNone(bump_commit)

    def test_run_bump_preserves_semver(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root, "0.1.0-a0", "semver")
            subprocess.run(
                ["git", "commit", "-m", "feat: continue"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            new_version = run_bump(
                BumpOptions(yes=True, prerelease="alpha", dry_run=True),
                cwd=root,
            )
            self.assertEqual(str(new_version), "0.1.0-a1")
            self.assertEqual(new_version.scheme, "semver")


if __name__ == "__main__":
    unittest.main()

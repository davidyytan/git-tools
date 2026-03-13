from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.bump import (
    BumpOptions,
    canonicalize_package_name,
    ConsistencyError,
    ConfigError,
    SemVer2Version,
    build_git_tag_args,
    build_parser,
    detect_increment,
    get_git_bool_config,
    load_bump_config,
    plan_version_file_updates,
    resolve_git_tag_args,
    run_bump,
    semver2_to_uv_version,
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

    def test_parser_accepts_default_increment(self) -> None:
        parser = build_parser()
        namespace = parser.parse_args(["--default-increment", "PATCH"])
        self.assertEqual(namespace.default_increment, "PATCH")


class SemVer2VersionTests(unittest.TestCase):
    def test_linear_mode_finalizes_prerelease_without_bumping_patch(self) -> None:
        current = SemVer2Version.parse("2.0.0-beta.0")
        self.assertEqual(str(current.bump("PATCH")), "2.0.0")

    def test_exact_mode_bumps_patch_from_prerelease(self) -> None:
        current = SemVer2Version.parse("2.0.0-beta.0")
        self.assertEqual(
            str(current.bump("PATCH", exact_increment=True)),
            "2.0.1",
        )

    def test_linear_mode_keeps_higher_prerelease_phase(self) -> None:
        current = SemVer2Version.parse("2.0.0-beta.0")
        self.assertEqual(
            str(current.bump("MINOR", prerelease="alpha")),
            "2.0.0-beta.1",
        )

    def test_uv_lock_version_conversion_matches_pep440(self) -> None:
        self.assertEqual(semver2_to_uv_version("0.2.0-alpha.15"), "0.2.0a15")
        self.assertEqual(semver2_to_uv_version("0.2.0-beta.2"), "0.2.0b2")
        self.assertEqual(semver2_to_uv_version("0.2.0-rc.3"), "0.2.0rc3")
        self.assertEqual(semver2_to_uv_version("0.2.0"), "0.2.0")

    def test_package_name_canonicalization_matches_uv_lock_style(self) -> None:
        self.assertEqual(canonicalize_package_name("Git_Tools"), "git-tools")


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
            with patch("git_tools.bump.get_git_bool_config", return_value=True):
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
                SemVer2Version.parse("0.2.0-alpha.16"),
                check_consistency=True,
            )

            self.assertIn('version = "0.2.0-alpha.16"', updates[cz_path])
            self.assertIn('version = "0.2.0-alpha.16"', updates[pyproject_path])
            self.assertIn('version = "0.2.0a16"', updates[uv_lock_path])

    def test_pyproject_source_can_heal_commitizen_auxiliary_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cz_path = root / ".cz.toml"
            pyproject_path = root / "pyproject.toml"
            cz_path.write_text(
                "[tool.commitizen]\nversion = \"0.2.0-alpha.12\"\n",
                encoding="utf-8",
            )
            pyproject_path.write_text(
                "[project]\nname = \"git-tools\"\nversion = \"0.2.0-alpha.15\"\n",
                encoding="utf-8",
            )

            config = load_bump_config(root, version_source="pyproject")

            updates = plan_version_file_updates(
                config,
                SemVer2Version.parse("0.2.0-alpha.16"),
                check_consistency=True,
            )

            self.assertIn('version = "0.2.0-alpha.16"', updates[cz_path])
            self.assertIn('version = "0.2.0-alpha.16"', updates[pyproject_path])

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
                SemVer2Version.parse("0.2.0-alpha.16"),
                check_consistency=False,
            )

            self.assertIn('version = "0.2.0-alpha.16"', updates[cz_path])
            self.assertIn('version = "0.2.0-alpha.16"', updates[pyproject_path])
            self.assertIn('version = "0.2.0a16"', updates[uv_lock_path])


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
            self.assertIn("--yes only applies", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

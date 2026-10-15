from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.generators.bumpgen import (
    ConfigError,
    ConsistencyError,
    PatternVersionTarget,
    Version,
    load_bump_config,
    plan_version_file_updates,
)


class PatternVersionTargetTests(unittest.TestCase):
    def apply(self, text: str, pattern: str = "version", *, check: bool = False):
        return PatternVersionTarget(
            path=Path("custom.txt"), label="custom", regex=re.compile(pattern)
        ).apply(text, current_version="1.2.3", new_version="1.2.4", check_consistency=check)

    def test_replaces_single_whole_token_and_preserves_other_lines(self):
        text = 'version = "1.2.3"\r\ndependency = "1.2.3"\r\n'
        self.assertEqual(
            self.apply(text),
            ('version = "1.2.4"\r\ndependency = "1.2.3"\r\n', True),
        )

    def test_repeated_single_versions_and_empty_selected_lines(self):
        self.assertEqual(
            self.apply('version header\nversion="1.2.3"\nversion="1.2.3"'),
            ('version header\nversion="1.2.4"\nversion="1.2.4"', True),
        )

    def test_stale_versions_and_both_prerelease_schemes_sync_as_whole_tokens(self):
        for source in ("0.9.0", "11.2.3", "1.2.30", "1.2.3-alpha.1", "1.2.3-beta.2", "1.2.3-rc.3", "1.2.3-a1", "1.2.3-b2", "1.2.3-rc3"):
            with self.subTest(source=source):
                self.assertEqual(self.apply(f'version="{source}"'), ('version="1.2.4"', True))

    def test_consistency_requires_exact_token_not_substring(self):
        for source in ("0.9.0", "11.2.3", "1.2.30", "1.2.3-alpha.1"):
            with self.subTest(source=source), self.assertRaises(ConsistencyError):
                self.apply(f'version="{source}"', check=True)

    def test_multiple_tokens_on_one_line_are_ambiguous_even_if_identical(self):
        for other in ("1.2.3", "9.0.0"):
            for check in (False, True):
                with self.subTest(other=other, check=check), self.assertRaises(ConsistencyError):
                    self.apply(f'{{"version":"1.2.3","dependency":"{other}"}}', check=check)

    def test_differing_versions_across_lines_are_ambiguous(self):
        for check in (False, True):
            with self.subTest(check=check), self.assertRaises(ConsistencyError):
                self.apply('version="1.2.3"\nversion="9.0.0"', check=check)

    def test_unsupported_suffixes_are_not_partially_replaced(self):
        for source in ("1.2.3+build.1", "1.2.3-preview.1", "1.2.3.4", "1.2.3-alpha.1-extra", "1.2.3_suffix"):
            with self.subTest(source=source), self.assertRaises(ConsistencyError):
                self.apply(f'version="{source}"')

    def test_embedded_and_missing_tokens_are_not_replaced(self):
        for text in ('version=unknown', 'version="v1.2.3"', 'version="prefix1.2.3"', 'dependency="1.2.3"'):
            with self.subTest(text=text), self.assertRaises(ConfigError):
                self.apply(text)

    def test_noop_reports_unchanged(self):
        self.assertEqual(self.apply('version="1.2.4"'), ('version="1.2.4"', False))


class CustomTargetPlanningTests(unittest.TestCase):
    def configure(self, root: Path, specs: list[str]):
        import json
        (root / ".cz.toml").write_text(
            '[tool.commitizen]\nversion="1.2.3"\nversion_files=' + json.dumps(specs) + '\n',
            encoding="utf-8",
        )

    def plan(self, root: Path):
        return plan_version_file_updates(
            load_bump_config(root), Version.parse("1.2.4"), check_consistency=True
        )

    def test_glob_isolates_ambiguous_unreadable_and_directory_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["*.txt:version"])
            files = {
                "good.txt": 'version="0.9.0"',
                "same.txt": 'version="1.2.3", dependency="1.2.3"',
                "mixed.txt": 'version="1.2.3"\nversion="9.0.0"',
                "unsupported.txt": 'version="1.2.3+build.1"',
            }
            for name, text in files.items():
                (root / name).write_text(text, encoding="utf-8")
            (root / "unreadable.txt").write_bytes(b"\xff")
            (root / "directory.txt").mkdir()
            with self.assertLogs("git_tools.generators.bumpgen", level="WARNING") as logs:
                updates = self.plan(root)
            self.assertIn('version="1.2.4"', updates[root / ".cz.toml"])
            self.assertEqual(updates[root / "good.txt"], 'version="1.2.4"')
            for name in ("same.txt", "mixed.txt", "unsupported.txt", "unreadable.txt", "directory.txt"):
                self.assertNotIn(root / name, updates)
                self.assertIn(name, " ".join(logs.output))
            for name, text in files.items():
                self.assertEqual((root / name).read_text(encoding="utf-8"), text)

    def test_plain_paths_keep_current_version_line_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["good.txt", "stale.txt"])
            (root / "good.txt").write_text('1.2.3\ndependency=9.0.0', encoding="utf-8")
            (root / "stale.txt").write_text('0.9.0', encoding="utf-8")
            with self.assertLogs("git_tools.generators.bumpgen", level="WARNING"):
                updates = self.plan(root)
            self.assertEqual(updates[root / "good.txt"], '1.2.4\ndependency=9.0.0')
            self.assertNotIn(root / "stale.txt", updates)

    def test_duplicate_and_overlapping_selectors_preserve_successful_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["custom.txt:^version", "custom.txt:^version", "custom.txt:."])
            (root / "custom.txt").write_text('version="1.2.3"\ndependency="9.0.0"', encoding="utf-8")
            with self.assertLogs("git_tools.generators.bumpgen", level="WARNING"):
                updates = self.plan(root)
            self.assertEqual(updates[root / "custom.txt"], 'version="1.2.4"\ndependency="9.0.0"')

    def test_symlink_selectors_share_pending_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["custom.txt:^first", "alias.txt:^second"])
            path = root / "custom.txt"
            path.write_text('first="1.2.3"\nsecond="1.2.3"', encoding="utf-8")
            (root / "alias.txt").symlink_to(path)
            updates = self.plan(root)
            self.assertEqual(updates[path], 'first="1.2.4"\nsecond="1.2.4"')
            self.assertNotIn(root / "alias.txt", updates)

    def test_custom_aliases_cannot_override_automatic_ecosystem_handlers(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["npm-alias.json:version", "cargo-alias.toml:version"])
            npm = root / "package.json"
            npm.write_text('{"version":"1.2.3","dependencies":{"lib":"1.2.3"}}', encoding="utf-8")
            cargo = root / "Cargo.toml"
            cargo.write_text('[package]\nname="app"\nversion="1.2.3"\n[dependencies]\nlib={version="1.2.3"}\n', encoding="utf-8")
            (root / "npm-alias.json").symlink_to(npm)
            (root / "cargo-alias.toml").symlink_to(cargo)
            updates = self.plan(root)
            self.assertEqual(json.loads(updates[npm]), {"version": "1.2.4", "dependencies": {"lib": "1.2.3"}})
            self.assertIn('version="1.2.4"', updates[cargo])
            self.assertIn('lib={version="1.2.3"}', updates[cargo])
            self.assertNotIn(root / "npm-alias.json", updates)
            self.assertNotIn(root / "cargo-alias.toml", updates)

    def test_external_paths_are_hard_configuration_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            root = parent / "repo"
            root.mkdir()
            external = parent / "external.txt"
            external.write_text('version="1.2.3"', encoding="utf-8")
            (root / "alias.txt").symlink_to(external)
            (root / "external-dir").symlink_to(parent, target_is_directory=True)
            specs = [
                "../external.txt:version", str(external) + ":version",
                "alias.txt:version", "*.txt:version",
                "external-dir/*.txt:version", "../missing.txt:version",
                "alias.txt:[",  # Unsafe paths must not hide behind invalid regexes.
            ]
            for spec in specs:
                with self.subTest(spec=spec):
                    self.configure(root, [spec])
                    with self.assertRaisesRegex(ConfigError, "outside repository root"):
                        load_bump_config(root)
                    self.assertEqual(external.read_text(encoding="utf-8"), 'version="1.2.3"')

    def test_internal_absolute_and_parent_alias_paths_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "sub").mkdir()
            path = root / "custom.txt"
            path.write_text('version="1.2.3"', encoding="utf-8")
            self.configure(root, [str(path) + ":version", "sub/../custom.txt:version"])
            self.assertEqual(self.plan(root)[path], 'version="1.2.4"')

    def test_repository_root_alias_uses_physical_identity(self):
        from git_tools.generators.bumpgen.repo import managed_version_paths
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp).resolve()
            root = parent / "physical"
            root.mkdir()
            alias = parent / "alias"
            alias.symlink_to(root, target_is_directory=True)
            self.configure(root, ["custom.txt:version"])
            (root / "custom.txt").write_text('version="1.2.3"', encoding="utf-8")
            config = load_bump_config(alias)
            self.assertEqual(config.root, root)
            self.assertTrue(all(target.path.is_relative_to(root) for target in config.version_targets))
            # Repository helpers must also accept a lexical alias of the physical root.
            self.assertEqual(managed_version_paths(alias), {".cz.toml", "custom.txt"})
            self.assertEqual(managed_version_paths(config.root), {".cz.toml", "custom.txt"})

    def test_toggle_disables_all_auxiliary_targets_without_reading_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["../unsafe.txt:version"])
            (root / "src-tauri").mkdir()
            for filename in ("pyproject.toml", "uv.lock", "package.json", "package-lock.json",
                             "npm-shrinkwrap.json", "Cargo.toml", "Cargo.lock",
                             "src-tauri/Cargo.toml", "src-tauri/Cargo.lock"):
                (root / filename).write_bytes(b"\xff")
            with patch.dict("os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": "false"}):
                with patch("git_tools.generators.bumpgen.config._warn_auxiliary") as warn:
                    updates = self.plan(root)
                warn.assert_not_called()
            self.assertEqual(set(updates), {root / ".cz.toml"})
            self.assertIn('version="1.2.4"', updates[root / ".cz.toml"])

    def test_disabled_sync_still_commits_and_tags_authoritative_version(self):
        import subprocess
        from git_tools.generators.bumpgen import BumpOptions, run_bump
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["custom.txt:version"])
            auxiliary = {
                "pyproject.toml": '[project]\nname="app"\nversion="1.2.3"\n',
                "package.json": '{"version":"1.2.3"}\n',
                "custom.txt": 'version="1.2.3"\n',
            }
            for name, text in auxiliary.items():
                (root / name).write_text(text, encoding="utf-8")
            def git(*args):
                return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
            git("init")
            git("config", "user.name", "Test Bot")
            git("config", "user.email", "test@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("config", "tag.gpgsign", "false")
            git("add", ".")
            git("commit", "-m", "feat: initial")
            git("tag", "1.2.3")
            with patch.dict("os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": "false"}):
                version = run_bump(BumpOptions(increment="PATCH", yes=True, respect_git_config=False), cwd=root)
            self.assertEqual(str(version), "1.2.4")
            self.assertIn('version="1.2.4"', (root / ".cz.toml").read_text())
            for name, text in auxiliary.items():
                self.assertEqual((root / name).read_text(), text)
            self.assertEqual(git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"), ".cz.toml")
            self.assertIn("1.2.4", git("tag").splitlines())
            self.assertEqual(git("status", "--porcelain"), "")

    def test_toggle_defaults_precedence_and_boolean_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "custom.txt"
            path.write_text('version="1.2.3"', encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                for setting in (None, True, False):
                    self.configure(root, ["custom.txt:version"])
                    if setting is not None:
                        with (root / ".cz.toml").open("a") as stream:
                            stream.write(f"sync_auxiliary={str(setting).lower()}\n")
                    self.assertEqual(path in self.plan(root), setting is not False)
                    for value in ("true", "1", "YES", " on ", "false", "0", "NO", " off "):
                        with self.subTest(setting=setting, env=value), patch.dict(
                            "os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": value}
                        ):
                            self.assertEqual(path in self.plan(root), value.strip().lower() in {"true", "1", "yes", "on"})
                    for value in ("", "maybe", "2", "enabled"):
                        with self.subTest(value=value), patch.dict(
                            "os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": value}
                        ), self.assertRaisesRegex(ConfigError, "GIT_TOOLS_BUMP_SYNC_AUXILIARY"):
                            load_bump_config(root)
                for value in ('"false"', '1', '[]'):
                    self.configure(root, [])
                    with (root / ".cz.toml").open("a") as stream:
                        stream.write(f"sync_auxiliary={value}\n")
                    # Invalid repository configuration is rejected even with an env override.
                    with patch.dict("os.environ", {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": "false"}), self.assertRaisesRegex(ConfigError, "sync_auxiliary must be a TOML boolean"):
                        load_bump_config(root)

    def test_invalid_missing_and_non_string_specs_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.configure(root, ["custom.txt:[", "missing*.txt", "custom.txt:^version", 42])
            (root / "custom.txt").write_text('version="1.2.3"', encoding="utf-8")
            with self.assertLogs("git_tools.generators.bumpgen", level="WARNING"):
                updates = self.plan(root)
            self.assertEqual(updates[root / "custom.txt"], 'version="1.2.4"')


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from pathlib import Path

from git_tools.generators.initgen import (
    CommitizenInitGenerator,
    CzInitError,
    CzInitOptions,
    build_commitizen_section,
    detect_default_version,
    upsert_commitizen_section,
)


class CommitizenInitGeneratorTests(unittest.TestCase):
    def test_defaults_follow_commitizen_bootstrap_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"demo\"\nversion = \"0.4.0\"\n",
                encoding="utf-8",
            )
            (root / "uv.lock").write_text(
                "[[package]]\nname = \"demo\"\nversion = \"0.4.0\"\n",
                encoding="utf-8",
            )

            path = CommitizenInitGenerator(interactive=False).generate_init(cwd=root)

            self.assertEqual(path.resolve(), (root / ".cz.toml").resolve())
            content = path.read_text(encoding="utf-8")
            self.assertIn('[tool.commitizen]', content)
            self.assertIn('version = "0.0.1"', content)
            self.assertNotIn('version_provider = "uv"', content)
            self.assertIn('tag_format = "$version"', content)
            self.assertIn('version_scheme = "semver2"', content)
            self.assertIn("major_version_zero = true", content)

    def test_existing_config_requires_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text(
                "[tool.commitizen]\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(CzInitError):
                CommitizenInitGenerator(interactive=False).generate_init(cwd=root)

    def test_force_updates_existing_config_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".cz.toml"
            config_path.write_text(
                "[tool.commitizen]\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

            CommitizenInitGenerator(
                version="0.2.0",
                force=True,
                interactive=False,
            ).generate_init(cwd=root)

            content = config_path.read_text(encoding="utf-8")
            self.assertIn('version = "0.2.0"', content)
            self.assertIn('name = "cz_conventional_commits"', content)

    def test_force_preserves_policy_comments_and_other_tables(self) -> None:
        original = '''# Repository policy
[tool.commitizen] # custom plugin
name = 'cz_customize'
version = "0.1.0" # release anchor
tag_format = 'release/$version'
major_version_zero = false # never downgrade breaking changes
sync_auxiliary = false
auxiliary_directories = ["apps/api", "packages/web"] # chosen targets
version_files = ["VERSION", "package.json:version"]
custom = """keep this
[tool.commitizen]
# not a header or comment
"""
[tool.commitizen.customize]
bump_pattern = "BREAKING|feat|fix"
[tool.other]
value = "untouched"
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / ".cz.toml"
            path.write_text(original, encoding="utf-8")
            CommitizenInitGenerator(version="0.2.0", force=True).generate_init(cwd=root)
            updated = path.read_text(encoding="utf-8")
            # Only version and the missing scheme may differ.
            self.assertEqual(updated.replace('version = "0.2.0"', 'version = "0.1.0"').replace('version_scheme = "semver2"\n', ''), original)
            saved = tomllib.loads(updated)["tool"]["commitizen"]
            self.assertFalse(saved["sync_auxiliary"])
            self.assertFalse(saved["major_version_zero"])
            self.assertEqual(saved["tag_format"], "release/$version")
            self.assertEqual(saved["auxiliary_directories"], ["apps/api", "packages/web"])

    def test_force_stable_version_preserves_explicit_prerelease_scheme(self) -> None:
        for requested in (None, "1.2.4"):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                path = root / ".cz.toml"
                path.write_text('[tool.commitizen]\nversion = "1.2.3"\nversion_scheme = "semver" # release policy\n', encoding="utf-8")
                CommitizenInitGenerator(force=True, version=requested).generate_init(cwd=root)
                content = path.read_text(encoding="utf-8")
                self.assertIn('version_scheme = "semver" # release policy', content)
                self.assertIn(f'version = "{requested or "1.2.3"}"', content)

    def test_force_explicit_policy_overrides_keep_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / ".cz.toml"
            path.write_text('[tool.commitizen]\nversion = "0.1.0"\ntag_format = "$version" # tag policy\nmajor_version_zero = true # policy\nsync_auxiliary = false\n', encoding="utf-8")
            CommitizenInitGenerator(force=True, tag_format='release/"$version"', major_version_zero=False).generate_init(cwd=root)
            updated = path.read_text(encoding="utf-8")
            saved = tomllib.loads(updated)["tool"]["commitizen"]
            self.assertEqual(saved["version"], "0.1.0")
            self.assertEqual(saved["tag_format"], 'release/"$version"')
            self.assertFalse(saved["major_version_zero"])
            self.assertIn('false # policy', updated)
            self.assertIn('# tag policy', updated)
            CommitizenInitGenerator(force=True, major_version_zero=True).generate_init(cwd=root)
            self.assertTrue(tomllib.loads(path.read_text())["tool"]["commitizen"]["major_version_zero"])

    def test_force_invalid_toml_fails_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / ".cz.toml"
            original = '[tool.commitizen]\nsync_auxiliary = false\nversion = "broken\n'
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(CzInitError, "back up and remove"):
                CommitizenInitGenerator(force=True, version="0.2.0").generate_init(cwd=root)
            self.assertEqual(path.read_text(), original)

    def test_force_handles_quoted_dotted_inline_and_nested_tables(self) -> None:
        layouts = [
            '[ tool . "commitizen" ] # policy\n"version" = "0.1.0" # anchor\nsync_auxiliary = false\n[tool.commitizen.customize]\nkey = "value"\n',
            '["tool" . \'commitizen\'] # policy\nversion = "0.1.0"\nnotes = \'# [tool.commitizen] = not syntax\'\n[tool.commitizen.customize]\nmessage = "= # [other]"\n',
            'tool.commitizen.version = "0.1.0" # anchor\ntool.commitizen.sync_auxiliary = false\n[other]\nkey = "value"\n',
            '[tool]\ncommitizen.version = "0.1.0"\ncommitizen.sync_auxiliary = false\n[other]\nkey = "value"\n',
            'tool = { commitizen = { version = "0.1.0", sync_auxiliary = false } } # retained\n',
            '[tool]\ncommitizen = { version = "0.1.0", sync_auxiliary = false } # retained\n',
            '[tool.commitizen.customize]\nkey = "value"\n',
            '# empty config\n',
        ]
        section = build_commitizen_section(CzInitOptions(".cz.toml", "0.2.0", "$version", False), updating=True)
        for original in layouts:
            with self.subTest(original=original):
                updated = upsert_commitizen_section(original, section)
                saved = tomllib.loads(updated)["tool"]["commitizen"]
                self.assertEqual(saved["version"], "0.2.0")
                if "sync_auxiliary" in original:
                    self.assertFalse(saved["sync_auxiliary"])
                for comment in ("# anchor", "# policy", "# retained", "# empty config"):
                    if comment in original:
                        self.assertIn(comment, updated)

    def test_saved_custom_tag_template_is_not_revalidated_or_normalized(self) -> None:
        for tag_format in ("release-${version}", "release/$major.$minor.$patch", " $version "):
            with self.subTest(tag_format=tag_format), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                path = root / ".cz.toml"
                path.write_text(f'[tool.commitizen]\nversion = "0.1.0"\ntag_format = "{tag_format}"\n')
                CommitizenInitGenerator(force=True, version="0.2.0").generate_init(cwd=root)
                self.assertEqual(tomllib.loads(path.read_text())["tool"]["commitizen"]["tag_format"], tag_format)

    def test_explicit_invalid_values_fail_without_prompt_loops(self) -> None:
        for kwargs in ({"version": "invalid"}, {"version": "0.1.0", "tag_format": "invalid"}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as tmpdir:
                generator = CommitizenInitGenerator(interactive=True, **kwargs)
                with patch.object(generator, "prompt_text") as prompt, self.assertRaises(CzInitError):
                    generator.generate_init(cwd=Path(tmpdir))
                prompt.assert_not_called()
                self.assertFalse((Path(tmpdir) / ".cz.toml").exists())

    def test_force_interactive_defaults_keep_saved_false_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / ".cz.toml"
            path.write_text('[tool.commitizen]\nversion = "0.1.0"\ntag_format = "release/$version"\nmajor_version_zero = false\n', encoding="utf-8")
            generator = CommitizenInitGenerator(force=True, interactive=True)
            def confirm(message, default):
                return True if message == "Write Commitizen config now?" else default
            with patch.object(generator, "prompt_text", side_effect=lambda message, default: default), patch.object(generator, "prompt_confirm", side_effect=confirm):
                generator.generate_init(cwd=root)
            self.assertFalse(tomllib.loads(path.read_text())["tool"]["commitizen"]["major_version_zero"])

    def test_existing_config_is_rejected_before_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cz.toml").write_text('[tool.commitizen]\nversion = "0.1.0"\n')
            generator = CommitizenInitGenerator(interactive=True)
            with patch.object(generator, "prompt_text") as prompt, self.assertRaises(CzInitError):
                generator.generate_init(cwd=root)
            prompt.assert_not_called()

    def test_explicit_cz_toml_config_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with self.assertRaises(CzInitError):
                CommitizenInitGenerator(
                    config_file="cz.toml",
                    interactive=False,
                ).generate_init(cwd=root)

    def test_legacy_cz_toml_on_disk_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "cz.toml").write_text(
                "[tool.commitizen]\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(CzInitError):
                CommitizenInitGenerator(interactive=False).generate_init(cwd=root)

    def test_pyproject_commitizen_section_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text(
                "[project]\nname = \"demo\"\nversion = \"0.1.0\"\n\n"
                "[tool.commitizen]\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

            with self.assertRaises(CzInitError):
                CommitizenInitGenerator(interactive=False).generate_init(cwd=root)

    def test_detect_default_version_prefers_latest_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
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
            (root / "README.md").write_text("demo\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "commit", "-m", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "tag", "0.4.0"], cwd=root, check=True, capture_output=True, text=True)

            self.assertEqual(detect_default_version(root), "0.4.0")

    def test_detect_default_version_falls_back_to_release_bootstrap_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.assertEqual(detect_default_version(root), "0.0.1")

    def test_build_commitizen_section_omits_commitizen_defaults(self) -> None:
        commitizen_section = build_commitizen_section(
            CzInitOptions(
                config_file=".cz.toml",
                version="0.0.1",
                tag_format="$version",
                major_version_zero=False,
            )
        )
        self.assertIn('version = "0.0.1"', commitizen_section)
        self.assertNotIn("version_provider", commitizen_section)
        self.assertNotIn("major_version_zero = false", commitizen_section)

        major_zero_section = build_commitizen_section(
            CzInitOptions(
                config_file=".cz.toml",
                version="0.0.1",
                tag_format="$version",
                major_version_zero=True,
            )
        )
        self.assertIn('version = "0.0.1"', major_zero_section)
        self.assertIn("major_version_zero = true", major_zero_section)


class CommitizenInitSchemeTests(unittest.TestCase):
    def test_semver_version_writes_semver_scheme_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            CommitizenInitGenerator(
                version="0.1.0-a0",
                interactive=False,
            ).generate_init(cwd=root)
            content = (root / ".cz.toml").read_text(encoding="utf-8")
            self.assertIn("version_scheme = \"semver\"", content)
            self.assertIn("version = \"0.1.0-a0\"", content)

    def test_invalid_version_is_rejected_in_non_interactive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with self.assertRaises(CzInitError):
                CommitizenInitGenerator(
                    version="not-a-version",
                    interactive=False,
                ).generate_init(cwd=root)

    def test_build_section_includes_scheme_label(self) -> None:
        section = build_commitizen_section(
            CzInitOptions(
                config_file=".cz.toml",
                version="1.0.0-a0",
                tag_format="$version",
                major_version_zero=False,
                scheme="semver",
            )
        )
        self.assertIn("version_scheme = \"semver\"", section)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from git_tools.generators.initgen import (
    CommitizenInitGenerator,
    CzInitError,
    CzInitOptions,
    build_commitizen_section,
    detect_default_version,
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

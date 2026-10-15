"""Content-aware backmerge classification against real, temporary Git history."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from git_tools.generators.bumpgen.repo import latest_commit_has_meaningful_changes


class BackmergeContentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-b", "master")
        self.git("config", "user.name", "Backmerge tests")
        self.git("config", "user.email", "backmerge@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.filemode", "true")
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.2.3"\n')
        self.commit()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True,
            capture_output=True, text=True,
        ).stdout

    def write(self, path: str, text: str | bytes) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))

    def commit(self) -> None:
        self.git("add", "--all")
        self.git("commit", "-m", "test fixture", "--allow-empty")

    def compare(self, before: dict[str, str], after: dict[str, str], expected: bool) -> None:
        for path, text in before.items():
            self.write(path, text)
        self.commit()
        for path, text in after.items():
            self.write(path, text)
        self.commit()
        self.assertIs(latest_commit_has_meaningful_changes(self.root), expected)

    @staticmethod
    def npm(version: str = "1.2.3", dependency: str = "^4.0.0", build: str = "vite build") -> str:
        return json.dumps({"name": "app", "version": version,
                           "dependencies": {"dep": dependency}, "scripts": {"build": build}})

    @staticmethod
    def npm_lock(version: str = "1.2.3", dependency: str = "4.0.0") -> str:
        return json.dumps({"name": "app", "version": version, "lockfileVersion": 3,
                           "packages": {"": {"name": "app", "version": version},
                                        "node_modules/dep": {"version": dependency,
                                                               "integrity": "sha512-test"}},
                           "dependencies": {"dep": {"version": dependency}}})

    @staticmethod
    def cargo(version: str = "1.2.3", dependency: str = "1", build: str = "build.rs") -> str:
        return (f'[package]\nname = "app"\nversion = "{version}"\nbuild = "{build}"\n'
                f'[dependencies]\nserde = "{dependency}"\n')

    @staticmethod
    def cargo_lock(version: str = "1.2.3", dependency: str = "1.2.3") -> str:
        # A same-named registry crate must not be mistaken for the local app.
        return (f'version = 4\n[[package]]\nname = "app"\nversion = "{version}"\n'
                'dependencies = ["serde"]\n[[package]]\nname = "serde"\n'
                f'version = "{dependency}"\nsource = "registry+https://example.invalid"\n'
                'checksum = "abc"\n[[package]]\nname = "app"\nversion = "0.9.0"\n'
                'source = "registry+https://example.invalid"\n')

    def test_npm_manifest_own_version_only_is_not_meaningful(self) -> None:
        self.compare({"package.json": self.npm()}, {"package.json": self.npm("1.2.4")}, False)

    def test_npm_dependency_change_with_version_is_meaningful(self) -> None:
        self.compare({"package.json": self.npm()},
                     {"package.json": self.npm("1.2.4", dependency="^5.0.0")}, True)

    def test_npm_build_change_with_version_is_meaningful(self) -> None:
        self.compare({"package.json": self.npm()},
                     {"package.json": self.npm("1.2.4", build="vite build --minify")}, True)

    def test_npm_lockfiles_root_versions_only_are_not_meaningful(self) -> None:
        for path in ("package-lock.json", "npm-shrinkwrap.json"):
            with self.subTest(path=path):
                self.compare({path: self.npm_lock()}, {path: self.npm_lock("1.2.4")}, False)

    def test_npm_lockfiles_dependency_versions_are_meaningful(self) -> None:
        for path in ("package-lock.json", "npm-shrinkwrap.json"):
            with self.subTest(path=path):
                self.compare({path: self.npm_lock()},
                             {path: self.npm_lock("1.2.4", "5.0.0")}, True)

    def test_npm_lockfile_integrity_change_is_meaningful(self) -> None:
        before = self.npm_lock()
        self.compare({"package-lock.json": before},
                     {"package-lock.json": before.replace("sha512-test", "sha512-new")}, True)

    def test_cargo_manifest_version_only_root_and_tauri(self) -> None:
        for prefix in ("", "src-tauri/"):
            with self.subTest(prefix=prefix):
                path = prefix + "Cargo.toml"
                self.compare({path: self.cargo()}, {path: self.cargo("1.2.4")}, False)

    def test_cargo_manifest_dependency_and_build_changes_root_and_tauri(self) -> None:
        for prefix in ("", "src-tauri/"):
            for kwargs in ({"dependency": "2"}, {"build": "new-build.rs"}):
                with self.subTest(prefix=prefix, kwargs=kwargs):
                    path = prefix + "Cargo.toml"
                    self.compare({path: self.cargo()}, {path: self.cargo("1.2.4", **kwargs)}, True)

    def test_cargo_lock_local_package_only_root_and_tauri(self) -> None:
        for prefix in ("", "src-tauri/"):
            with self.subTest(prefix=prefix):
                self.compare({prefix + "Cargo.toml": self.cargo(),
                              prefix + "Cargo.lock": self.cargo_lock()},
                             {prefix + "Cargo.toml": self.cargo("1.2.4"),
                              prefix + "Cargo.lock": self.cargo_lock("1.2.4")}, False)

    def test_cargo_lock_dependency_changes_root_and_tauri(self) -> None:
        for prefix in ("", "src-tauri/"):
            with self.subTest(prefix=prefix):
                self.compare({prefix + "Cargo.toml": self.cargo(),
                              prefix + "Cargo.lock": self.cargo_lock()},
                             {prefix + "Cargo.toml": self.cargo("1.2.4"),
                              prefix + "Cargo.lock": self.cargo_lock("1.2.4", "1.2.4")}, True)

    def test_cargo_lock_same_named_external_package_change_is_meaningful(self) -> None:
        self.compare({"Cargo.toml": self.cargo(), "Cargo.lock": self.cargo_lock()},
                     {"Cargo.lock": self.cargo_lock().replace('version = "0.9.0"', 'version = "0.9.1"')}, True)

    def test_cargo_lock_ambiguous_local_package_is_meaningful(self) -> None:
        extra = '\n[[package]]\nname = "app"\nversion = "0.8.0"\n'
        self.compare({"Cargo.toml": self.cargo(), "Cargo.lock": self.cargo_lock() + extra},
                     {"Cargo.lock": self.cargo_lock("1.2.4") + extra}, True)

    def test_commitizen_version_only_is_not_meaningful(self) -> None:
        self.compare({".cz.toml": '[tool.commitizen]\nversion = "1.2.3"\n'},
                     {".cz.toml": '[tool.commitizen]\nversion = "1.2.4"\n'}, False)

    def test_commitizen_configuration_change_is_meaningful(self) -> None:
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.2.4"\ntag_format = "v$version"\n')
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_pyproject_and_uv_own_versions_only(self) -> None:
        before = {"pyproject.toml": '[project]\nname = "app"\nversion = "1.2.3"\ndependencies = ["dep>=1"]\n',
                  "uv.lock": 'version = 1\n[[package]]\nname = "app"\nversion = "1.2.3"\nsource = { editable = "." }\n'
                             '[[package]]\nname = "dep"\nversion = "1.2.3"\nsource = { registry = "https://example.invalid" }\n'}
        after = {path: text.replace('version = "1.2.3"', 'version = "1.2.4"', 1)
                 for path, text in before.items()}
        self.compare(before, after, False)

    def test_pyproject_dependency_change_is_meaningful(self) -> None:
        before = '[project]\nname = "app"\nversion = "1.2.3"\ndependencies = ["dep>=1"]\n'
        self.compare({"pyproject.toml": before},
                     {"pyproject.toml": before.replace('1.2.3', '1.2.4').replace('dep>=1', 'dep>=2')}, True)

    def test_uv_dependency_change_is_meaningful(self) -> None:
        lock = ('version = 1\n[[package]]\nname = "app"\nversion = "1.2.3"\n'
                '[[package]]\nname = "dep"\nversion = "1.2.3"\n')
        self.compare({"pyproject.toml": '[project]\nname = "app"\nversion = "1.2.3"\n', "uv.lock": lock},
                     {"uv.lock": lock.replace('name = "dep"\nversion = "1.2.3"',
                                              'name = "dep"\nversion = "2.0.0"')}, True)

    def test_custom_target_only_selected_version_is_ignored(self) -> None:
        self.write(".cz.toml", '[tool.commitizen]\nversion = "1.2.3"\nversion_files = ["VERSION:release"]\n')
        self.compare({"VERSION": 'release = "1.2.3"\nbuild = "old"\n'},
                     {"VERSION": 'release = "1.2.4"\nbuild = "old"\n'}, False)
        self.write("VERSION", 'release = "1.2.5"\nbuild = "new"\n')
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_malformed_managed_files_are_meaningful(self) -> None:
        for path, good, bad in (("package.json", self.npm(), "{broken"),
                                ("Cargo.toml", self.cargo(), "[broken"),
                                ("Cargo.lock", self.cargo_lock(), "[broken"),
                                (".cz.toml", '[tool.commitizen]\nversion = "1.2.3"\n', "[broken")):
            with self.subTest(path=path):
                self.compare({".cz.toml": '[tool.commitizen]\nversion = "1.2.3"\n',
                              "Cargo.toml": self.cargo(), path: good}, {path: bad}, True)

    def test_malformed_previous_blob_is_meaningful(self) -> None:
        self.compare({"package.json": "{broken"}, {"package.json": self.npm()}, True)

    def test_undecodable_blob_is_meaningful(self) -> None:
        self.write("package.json", self.npm())
        self.commit()
        self.write("package.json", b"\xff\xfe")
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_new_and_deleted_managed_file_are_meaningful(self) -> None:
        self.write("package.json", self.npm())
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))
        (self.root / "package.json").unlink()
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_executable_mode_change_is_meaningful(self) -> None:
        self.write("package.json", self.npm())
        self.commit()
        self.git("update-index", "--chmod=+x", "package.json")
        self.git("commit", "-m", "change file mode")
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_worktree_does_not_hide_committed_dependency_change(self) -> None:
        self.compare({"package.json": self.npm()},
                     {"package.json": self.npm(dependency="^5.0.0")}, True)
        self.write("package.json", self.npm())
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_unmanaged_source_change_is_meaningful(self) -> None:
        self.compare({"app.py": "print(1)\n"}, {"app.py": "print(2)\n"}, True)

    def test_empty_commit_is_not_meaningful(self) -> None:
        self.commit()
        self.assertFalse(latest_commit_has_meaningful_changes(self.root))

    def test_merge_uses_first_parent_content(self) -> None:
        self.write("package.json", self.npm())
        self.commit()
        self.git("checkout", "-b", "bump")
        self.write("package.json", self.npm("1.2.4"))
        self.commit()
        self.git("checkout", "master")
        self.git("merge", "--no-ff", "bump", "-m", "merge version bump")
        self.assertFalse(latest_commit_has_meaningful_changes(self.root))
        self.git("checkout", "-b", "dependency")
        self.write("package.json", self.npm("1.2.5", dependency="^5.0.0"))
        self.commit()
        self.git("checkout", "master")
        self.git("merge", "--no-ff", "dependency", "-m", "merge dependency")
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_symlink_replacing_managed_file_is_meaningful(self) -> None:
        self.write("package.json", self.npm())
        self.write("other.json", self.npm())
        self.commit()
        (self.root / "package.json").unlink()
        (self.root / "package.json").symlink_to("other.json")
        self.commit()
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))

    def test_initial_commit_is_conservatively_meaningful(self) -> None:
        self.assertTrue(latest_commit_has_meaningful_changes(self.root))


if __name__ == "__main__":
    unittest.main()

"""Bounded, release-sharing discovery across every auxiliary ecosystem."""

import json
import tempfile
import tomllib
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from git_tools.generators.bumpgen import (
    ConfigError, Version, load_bump_config, plan_version_file_updates,
)


class BoundedDiscoveryTests(unittest.TestCase):
    ecosystems = ("python", "npm", "cargo")
    excluded = (".hidden", "node_modules", "target", "build", "dist", "vendor", "venv", "__pycache__")

    @contextmanager
    def repository(self, settings=""):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ", {}, clear=True
        ):
            root = Path(tmp).resolve()
            self.configure(root, settings)
            yield root

    def configure(self, root, settings=""):
        (root / ".cz.toml").write_text(
            '[tool.commitizen]\nversion = "1.2.3"\nversion_scheme = "semver2"\n' + settings,
            encoding="utf-8",
        )

    def files(self, directory, ecosystem, name="app"):
        directory.mkdir(parents=True, exist_ok=True)
        if ecosystem == "python":
            texts = {
                "pyproject.toml": f'[project]\nname = "{name}"\nversion = "0.9.0"\n',
                "uv.lock": f'version = 1\n[[package]]\nname = "{name.lower().replace("_", "-")}"\nversion = "0.9.0"\n\n[[package]]\nname = "dependency"\nversion = "0.9.0"\n',
            }
        elif ecosystem == "npm":
            texts = {
                "package.json": json.dumps({"name": name, "version": "0.9.0", "dependencies": {"dependency": "0.9.0"}}),
                "package-lock.json": json.dumps({"name": name, "version": "0.9.0", "lockfileVersion": 3, "packages": {"": {"name": name, "version": "0.9.0"}, "node_modules/dependency": {"version": "0.9.0"}}}),
                "npm-shrinkwrap.json": json.dumps({"name": name, "version": "0.9.0", "lockfileVersion": 3, "packages": {"": {"name": name, "version": "0.9.0"}, "node_modules/dependency": {"version": "0.9.0"}}}),
            }
        else:
            texts = {
                "Cargo.toml": f'[package]\nname = "{name}"\nversion = "0.9.0"\n[dependencies]\ndependency = "0.9.0"\n',
                "Cargo.lock": f'version = 4\n[[package]]\nname = "{name}"\nversion = "0.9.0"\n\n[[package]]\nname = "{name}"\nversion = "0.9.0"\nsource = "registry+https://example.invalid/index"\n\n[[package]]\nname = "dependency"\nversion = "0.9.0"\n',
            }
        paths = set()
        for filename, text in texts.items():
            path = directory / filename
            path.write_text(text, encoding="utf-8")
            paths.add(path)
        return paths

    def plan(self, root, version="1.2.4"):
        return plan_version_file_updates(
            load_bump_config(root), Version.parse(version), check_consistency=True,
        )

    def test_single_root_or_visible_child_is_discovered_for_every_ecosystem(self):
        for ecosystem in self.ecosystems:
            for location in (".", "backend", "src-tauri"):
                with self.subTest(ecosystem=ecosystem, location=location), self.repository() as root:
                    expected = self.files(root / location, ecosystem)
                    updates = self.plan(root)
                    self.assertEqual(set(updates), expected | {root / ".cz.toml"})
                    for path in expected:
                        self.assertIn("1.2.4", updates[path])
                        self.assertIn("0.9.0", path.read_text())  # Planning never writes.

    def test_different_ecosystems_in_different_directories_are_not_ambiguous(self):
        with self.repository() as root:
            expected = {root / ".cz.toml"}
            for ecosystem, directory in zip(self.ecosystems, ("backend", ".", "native")):
                expected |= self.files(root / directory, ecosystem)
            self.assertEqual(set(self.plan(root)), expected)

    def test_mixed_ecosystems_and_tauri_sync_together_without_package_managers(self):
        with self.repository() as root:
            expected = {root / ".cz.toml"}
            for ecosystem, child in (("python", "backend"), ("npm", "frontend"), ("cargo", "src-tauri")):
                for location in (".", child):
                    expected |= self.files(root / location, ecosystem)
            tauri_config = root / "src-tauri" / "tauri.conf.json"
            tauri_config.write_text('{"version":"../package.json"}\n', encoding="utf-8")
            unselected = {tauri_config}
            for ecosystem in self.ecosystems:
                unselected |= self.files(root / "apps" / ecosystem, ecosystem)
            before = {path: path.read_bytes() for path in expected | unselected}
            with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"), patch("subprocess.run") as run:
                updates = self.plan(root)
            run.assert_not_called()
            self.assertEqual(set(updates), expected)
            for location in (".", "backend"):
                directory = root / location
                self.assertEqual(tomllib.loads(updates[directory / "pyproject.toml"])["project"]["version"], "1.2.4")
                self.assertEqual(tomllib.loads(updates[directory / "uv.lock"])["package"][0]["version"], "1.2.4")
            for location in (".", "frontend"):
                directory = root / location
                self.assertEqual(json.loads(updates[directory / "package.json"])["version"], "1.2.4")
                for filename in ("package-lock.json", "npm-shrinkwrap.json"):
                    lock = json.loads(updates[directory / filename])
                    self.assertEqual(lock["version"], "1.2.4")
                    self.assertEqual(lock["packages"][""]["version"], "1.2.4")
            for location in (".", "src-tauri"):
                directory = root / location
                self.assertEqual(tomllib.loads(updates[directory / "Cargo.toml"])["package"]["version"], "1.2.4")
                self.assertEqual(tomllib.loads(updates[directory / "Cargo.lock"])["package"][0]["version"], "1.2.4")
            self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_hidden_generated_and_deep_directories_do_not_count_as_candidates(self):
        for ecosystem in self.ecosystems:
            with self.subTest(ecosystem=ecosystem), self.repository() as root:
                expected = self.files(root / "app", ecosystem)
                for directory in (*self.excluded, "packages/deep", "app/deeper"):
                    self.files(root / directory, ecosystem)
                with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                    updates = self.plan(root)
                self.assertEqual(set(updates), expected | {root / ".cz.toml"})

    def test_symlink_directories_are_not_candidates_even_when_internal(self):
        for ecosystem in self.ecosystems:
            for external in (False, True):
                with self.subTest(ecosystem=ecosystem, external=external), self.repository() as root:
                    expected = self.files(root / "app", ecosystem)
                    with tempfile.TemporaryDirectory() as tmp:
                        destination = Path(tmp).resolve() if external else root / ".hidden"
                        self.files(destination, ecosystem)
                        (root / "linked").symlink_to(destination, target_is_directory=True)
                        self.assertEqual(set(self.plan(root)), expected | {root / ".cz.toml"})

    def test_symlink_files_are_neither_read_nor_counted_as_candidates(self):
        for ecosystem in self.ecosystems:
            with self.subTest(ecosystem=ecosystem), self.repository() as root:
                expected = self.files(root / "app", ecosystem)
                hidden = self.files(root / ".hidden", ecosystem)
                linked = root / "linked"
                linked.mkdir()
                for path in hidden:
                    (linked / path.name).symlink_to(path)
                with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                    updates = self.plan(root)
                self.assertEqual(set(updates), expected | {root / ".cz.toml"})

    def test_symlink_sibling_locks_are_skipped_without_losing_manifest(self):
        for ecosystem in self.ecosystems:
            with self.subTest(ecosystem=ecosystem), self.repository() as root:
                paths = self.files(root / "app", ecosystem)
                locks = {p for p in paths if p.name in ("uv.lock", "Cargo.lock", "package-lock.json", "npm-shrinkwrap.json")}
                for lock in locks:
                    destination = root / ("." + lock.name)
                    lock.rename(destination)
                    lock.symlink_to(destination)
                self.assertEqual(set(self.plan(root)), (paths - locks) | {root / ".cz.toml"})

    def test_multiple_directories_sync_every_eligible_location_by_default(self):
        for ecosystem in self.ecosystems:
            for locations in ((".", "backend"), ("backend", "frontend")):
                with self.subTest(ecosystem=ecosystem, locations=locations), self.repository() as root:
                    expected = {root / ".cz.toml"}
                    for directory in locations:
                        expected |= self.files(root / directory, ecosystem)
                    other = "npm" if ecosystem != "npm" else "cargo"
                    expected |= self.files(root / "other", other)
                    with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                        updates = self.plan(root)
                    self.assertEqual(set(updates), expected)
                    for path in expected:
                        self.assertIn("1.2.4", updates[path])

    def test_default_root_and_multiple_children_keep_lock_matching_local(self):
        locations = ((".", "Root_App"), ("backend", "Backend_App"), ("smoke_runs", "Smoke_App"))
        canonical_names = [name.lower().replace("_", "-") for _, name in locations]
        for ecosystem in self.ecosystems:
            with self.subTest(ecosystem=ecosystem), self.repository() as root:
                expected = {root / ".cz.toml"}
                for location, name in locations:
                    directory = root / location
                    expected |= self.files(directory, ecosystem, name=name)
                    if ecosystem == "python":
                        with (directory / "pyproject.toml").open("a", encoding="utf-8") as manifest:
                            manifest.write('dependencies = ["dependency==0.9.0"]\n')
                        # Other release-sharing projects are dependencies here,
                        # not extra copies of this lock's own local package.
                        with (directory / "uv.lock").open("a", encoding="utf-8") as lock:
                            for dependency in canonical_names:
                                if dependency != name.lower().replace("_", "-"):
                                    lock.write(f'\n[[package]]\nname = "{dependency}"\nversion = "0.9.0"\n')
                before = {path: path.read_bytes() for path in expected}
                with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                    config = load_bump_config(root)
                    updates = plan_version_file_updates(
                        config, Version.parse("1.3.0-alpha.2"), check_consistency=True,
                    )
                self.assertEqual(set(updates), expected)
                if ecosystem == "python":
                    self.assertEqual(config.project_name, "Root_App")
                for location, name in locations:
                    directory = root / location
                    if ecosystem == "python":
                        manifest = tomllib.loads(updates[directory / "pyproject.toml"])["project"]
                        self.assertEqual(manifest["version"], "1.3.0-alpha.2")
                        self.assertEqual(manifest["dependencies"], ["dependency==0.9.0"])
                        own_name = name.lower().replace("_", "-")
                        packages = tomllib.loads(updates[directory / "uv.lock"])["package"]
                        self.assertEqual(
                            [(p["name"], p["version"]) for p in packages],
                            [(own_name, "1.3.0a2"), ("dependency", "0.9.0")]
                            + [(n, "0.9.0") for n in canonical_names if n != own_name],
                        )
                    elif ecosystem == "npm":
                        manifest = json.loads(updates[directory / "package.json"])
                        self.assertEqual(manifest["version"], "1.3.0-alpha.2")
                        self.assertEqual(manifest["dependencies"], {"dependency": "0.9.0"})
                        for filename in ("package-lock.json", "npm-shrinkwrap.json"):
                            lock = json.loads(updates[directory / filename])
                            self.assertEqual(lock["version"], "1.3.0-alpha.2")
                            self.assertEqual(lock["packages"][""]["version"], "1.3.0-alpha.2")
                            self.assertEqual(lock["packages"]["node_modules/dependency"]["version"], "0.9.0")
                            self.assertEqual(lock["lockfileVersion"], 3)
                    else:
                        manifest = tomllib.loads(updates[directory / "Cargo.toml"])
                        self.assertEqual(manifest["package"]["version"], "1.3.0-alpha.2")
                        self.assertEqual(manifest["dependencies"], {"dependency": "0.9.0"})
                        lock = tomllib.loads(updates[directory / "Cargo.lock"])
                        self.assertEqual(lock["version"], 4)
                        self.assertEqual([p["version"] for p in lock["package"]], ["1.3.0-alpha.2", "0.9.0", "0.9.0"])
                self.assertEqual({path: path.read_bytes() for path in expected}, before)

    def test_explicit_selection_allows_multiple_release_sharing_directories(self):
        with self.repository('auxiliary_directories = [".", "backend"]\n') as root:
            expected = {root / ".cz.toml"}
            for ecosystem in self.ecosystems:
                for directory in (".", "backend"):
                    expected |= self.files(root / directory, ecosystem, name="root-app" if directory == "." else "backend-app")
                self.files(root / "unselected", ecosystem)
            with self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                updates = self.plan(root)
            self.assertEqual(set(updates), expected)
            for directory, name in ((root, "root-app"), (root / "backend", "backend-app")):
                packages = tomllib.loads(updates[directory / "uv.lock"])["package"]
                self.assertEqual(packages[0]["name"], name)
                self.assertEqual(packages[0]["version"], "1.2.4")
                self.assertEqual(packages[1]["version"], "0.9.0")

    def test_explicit_selection_is_an_allowlist_not_additive(self):
        for ecosystem in self.ecosystems:
            for selection in ('["backend"]', '[]'):
                with self.subTest(ecosystem=ecosystem, selection=selection), self.repository(f"auxiliary_directories = {selection}\n") as root:
                    self.files(root, ecosystem)
                    child = self.files(root / "backend", ecosystem)
                    expected = {root / ".cz.toml"} | (child if selection != "[]" else set())
                    self.assertEqual(set(self.plan(root)), expected)

    def test_auxiliary_directories_requires_a_list_of_strings(self):
        for value in ('"backend"', 'true', '42', '{}', '["backend", 1]', '[false]', '[[]]'):
            with self.subTest(value=value), self.repository(f"auxiliary_directories = {value}\n") as root:
                (root / "backend").mkdir()
                with self.assertRaises(ConfigError):
                    load_bump_config(root)

    def test_unsafe_explicit_directories_are_configuration_errors(self):
        with self.repository() as root, tempfile.TemporaryDirectory() as tmp:
            (root / "backend" / "deep").mkdir(parents=True)
            (root / "linked").symlink_to(root / "backend", target_is_directory=True)
            (root / "external").symlink_to(Path(tmp).resolve(), target_is_directory=True)
            for entry in ("../", "backend/..", "backend/../backend", "backend/deep", str(root), str(Path(tmp).resolve()), "linked", "external"):
                with self.subTest(entry=entry):
                    self.configure(root, "auxiliary_directories = " + json.dumps([entry]) + "\n")
                    with self.assertRaises(ConfigError):
                        load_bump_config(root)

    def test_disabled_sync_bypasses_directory_validation_and_manifest_reads(self):
        for value in ('42', '["../unsafe"]', '["backend/deep"]'):
            for env_override in (False, True):
                with self.subTest(value=value, env_override=env_override), self.repository() as root:
                    self.configure(root, f"auxiliary_directories = {value}\n" + ("" if env_override else "sync_auxiliary = false\n"))
                    for ecosystem in self.ecosystems:
                        for path in self.files(root, ecosystem):
                            path.write_bytes(b"\xff")
                    overrides = {"GIT_TOOLS_BUMP_SYNC_AUXILIARY": "false"} if env_override else {}
                    with patch.dict("os.environ", overrides), self.assertNoLogs("git_tools.generators.bumpgen", level="WARNING"):
                        updates = self.plan(root)
                    self.assertEqual(set(updates), {root / ".cz.toml"})

    def test_malformed_child_manifests_do_not_block_healthy_same_ecosystem_locations(self):
        for ecosystem, filename in zip(self.ecosystems, ("pyproject.toml", "package.json", "Cargo.toml")):
            for malformed in (b"[broken", b"\xff"):
                with self.subTest(ecosystem=ecosystem, malformed=malformed), self.repository() as root:
                    expected = self.files(root, ecosystem) | self.files(root / "healthy", ecosystem)
                    expected.add(root / ".cz.toml")
                    before = {path: path.read_bytes() for path in expected}
                    child = root / "backend"
                    child.mkdir()
                    path = child / filename
                    path.write_bytes(malformed)
                    with self.assertLogs("git_tools.generators.bumpgen", level="WARNING"):
                        updates = self.plan(root)
                    self.assertEqual(set(updates), expected)
                    for updated in expected:
                        self.assertIn("1.2.4", updates[updated])
                    self.assertEqual(path.read_bytes(), malformed)
                    self.assertEqual({path: path.read_bytes() for path in expected}, before)

    def test_versionless_child_does_not_block_healthy_same_ecosystem_locations(self):
        manifests = {
            "python": ("pyproject.toml", '[project]\nname = "versionless"\ndynamic = ["version"]\n'),
            "npm": ("package.json", '{"name": "versionless", "dependencies": {"dependency": "0.9.0"}}\n'),
            "cargo": ("Cargo.toml", '[package]\nname = "versionless"\n'),
        }
        for ecosystem, (filename, text) in manifests.items():
            with self.subTest(ecosystem=ecosystem), self.repository() as root:
                expected = self.files(root, ecosystem) | self.files(root / "healthy", ecosystem)
                expected.add(root / ".cz.toml")
                before = {path: path.read_bytes() for path in expected}
                child = root / "versionless"
                child.mkdir()
                path = child / filename
                path.write_text(text, encoding="utf-8")
                logs = self.assertNoLogs if ecosystem == "python" else self.assertLogs
                with logs("git_tools.generators.bumpgen", level="WARNING"):
                    updates = self.plan(root)
                self.assertEqual(set(updates), expected)
                for updated in expected:
                    self.assertIn("1.2.4", updates[updated])
                self.assertEqual(path.read_text(encoding="utf-8"), text)
                self.assertEqual({path: path.read_bytes() for path in expected}, before)

    def test_child_lock_matching_and_dependency_fields_are_preserved(self):
        with self.repository() as root:
            for ecosystem in self.ecosystems:
                self.files(root / ecosystem, ecosystem, name="My_App" if ecosystem == "python" else "app")
            updates = self.plan(root, "1.3.0-alpha.2")
            python = tomllib.loads(updates[root / "python" / "pyproject.toml"])
            self.assertEqual(python["project"]["version"], "1.3.0-alpha.2")
            uv = tomllib.loads(updates[root / "python" / "uv.lock"])["package"]
            self.assertEqual([(p["name"], p["version"]) for p in uv], [("my-app", "1.3.0a2"), ("dependency", "0.9.0")])
            for filename in ("package-lock.json", "npm-shrinkwrap.json"):
                data = json.loads(updates[root / "npm" / filename])
                self.assertEqual(data["version"], "1.3.0-alpha.2")
                self.assertEqual(data["packages"][""]["version"], "1.3.0-alpha.2")
                self.assertEqual(data["packages"]["node_modules/dependency"]["version"], "0.9.0")
                self.assertEqual(data["lockfileVersion"], 3)
            npm = json.loads(updates[root / "npm" / "package.json"])
            self.assertEqual(npm["dependencies"], {"dependency": "0.9.0"})
            cargo = tomllib.loads(updates[root / "cargo" / "Cargo.lock"])
            self.assertEqual(cargo["version"], 4)
            self.assertEqual([p["version"] for p in cargo["package"]], ["1.3.0-alpha.2", "0.9.0", "0.9.0"])
            manifest = tomllib.loads(updates[root / "cargo" / "Cargo.toml"])
            self.assertEqual(manifest["dependencies"]["dependency"], "0.9.0")


if __name__ == "__main__":
    unittest.main()

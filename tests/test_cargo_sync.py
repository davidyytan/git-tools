"""Best-effort Cargo syncing and ecosystem-helper package regressions."""

import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from git_tools.generators.bumpgen import (
    BumpOptions, Version, load_bump_config, plan_version_file_updates, run_bump,
)
from git_tools.generators.utils.version_sync.cargo import sync_cargo_lock, sync_cargo_manifest


class CargoSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".cz.toml").write_text('[tool.commitizen]\nversion = "1.2.3"\nversion_scheme = "semver2"\n')

    def manifest(self, directory=None, text=None):
        directory = directory or self.root
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "Cargo.toml"
        path.write_text(text or '[package]\nname = "app"\nversion = "0.9.0" # app version\n[dependencies]\nserde = "1.2.3"\n')
        return path

    def lock(self, directory=None, extra=""):
        path = (directory or self.root) / "Cargo.lock"
        path.write_text('# generated\nversion = 4\n\n[[package]]\nname = "app"\nversion = "0.9.0"\ndependencies = ["serde"]\n\n[[package]]\nname = "serde"\nversion = "1.2.3"\nsource = "registry+https://example.invalid/index"\n' + extra)
        return path

    def plan(self, version="1.2.4"):
        return plan_version_file_updates(load_bump_config(self.root), Version.parse(version), check_consistency=True)

    def test_root_and_tauri_versions_only(self):
        (self.root / "src-tauri").mkdir()
        cz = self.root / ".cz.toml"
        cz.write_text(cz.read_text() + 'auxiliary_directories = [".", "src-tauri"]\n')
        for directory in (self.root, self.root / "src-tauri"):
            manifest = self.manifest(directory)
            lock = self.lock(directory)
            updates = self.plan("1.3.0-alpha.0")
            self.assertEqual(tomllib.loads(updates[manifest])["package"]["version"], "1.3.0-alpha.0")
            self.assertIn('# app version', updates[manifest])
            self.assertEqual(tomllib.loads(updates[manifest])["dependencies"]["serde"], "1.2.3")
            packages = tomllib.loads(updates[lock])["package"]
            self.assertEqual(packages[0]["version"], "1.3.0-alpha.0")
            self.assertEqual(packages[1]["version"], "1.2.3")
        config = self.root / "src-tauri" / "tauri.conf.json"
        config.write_text('{"version":"../package.json"}')
        self.assertNotIn(config, self.plan())
        self.assertEqual(config.read_text(), '{"version":"../package.json"}')

    def test_no_workspace_recursion_or_shared_version_rewrite(self):
        text = '[workspace]\nmembers = ["crates/*"]\n[workspace.package]\nversion = "1.2.3"\n'
        manifest = self.manifest(text=text)
        member = self.manifest(self.root / "crates" / "child")
        with self.assertLogs('git_tools.generators.bumpgen', level='WARNING'):
            updates = self.plan()
        self.assertNotIn(manifest, updates)
        self.assertNotIn(member, updates)
        self.assertEqual(manifest.read_text(), text)

    def test_invalid_or_inherited_manifest_warns_and_core_continues(self):
        for text in ('[broken', '[package]\nname="app"\nversion.workspace=true\n', '[package]\nname="app"\n', '[package]\nversion=123\n'):
            with self.subTest(text=text):
                path = self.manifest(text=text)
                with self.assertLogs('git_tools.generators.bumpgen', level='WARNING'):
                    updates = self.plan()
                self.assertNotIn(path, updates)
                self.assertIn('version = "1.2.4"', updates[self.root / '.cz.toml'])

    def test_bad_lock_skipped_independently_from_manifest(self):
        manifest = self.manifest()
        lock = self.root / 'Cargo.lock'
        for text in ('[broken', 'version=4\n', '[[package]]\nname="app"\nversion="1.0.0"\n', '[[package]]\nname="app"\nversion="0.9.0"\nsource="registry+https://example.invalid"\n'):
            with self.subTest(text=text):
                lock.write_text(text)
                with self.assertLogs('git_tools.generators.bumpgen', level='WARNING'):
                    updates = self.plan()
                self.assertIn(manifest, updates)
                self.assertNotIn(lock, updates)

    def test_same_named_external_package_not_changed(self):
        self.manifest()
        lock = self.lock(extra='\n[[package]]\nname="app"\nversion="0.9.0"\nsource="registry+https://example.invalid"\n')
        data = tomllib.loads(self.plan()[lock])
        self.assertEqual(data['package'][0]['version'], '1.2.4')
        self.assertEqual(data['package'][2]['version'], '0.9.0')

    def test_ambiguous_local_packages_and_qualified_references_skip(self):
        self.manifest()
        for extra in ('\n[[package]]\nname="app"\nversion="0.9.0"\n', '\n[[package]]\nname="other"\nversion="1.0.0"\ndependencies=["app 0.9.0"]\n'):
            lock = self.lock(extra=extra)
            with self.assertLogs('git_tools.generators.bumpgen', level='WARNING'):
                updates = self.plan()
            self.assertNotIn(lock, updates)

    def test_literal_quotes_comments_line_endings_and_field_order(self):
        manifest = "[package] # crate\r\nversion = '1.2.3' # keep\r\nname = 'app'\r\n"
        updated, changed = sync_cargo_manifest(manifest, '1.2.4')
        self.assertTrue(changed)
        self.assertEqual(updated, manifest.replace('1.2.3', '1.2.4'))
        lock = "version=4\r\n[[package]] # crate\r\nversion='1.2.3' # keep\r\nname='app'\r\n"
        self.assertEqual(sync_cargo_lock(lock, 'app', '1.2.3', '1.2.4')[0], lock.replace('1.2.3', '1.2.4'))
        self.assertFalse(sync_cargo_manifest(updated, '1.2.4')[1])

    def test_explicit_patterns_do_not_override_automatic_cargo_safety(self):
        self.manifest()
        lock = self.lock()
        cz = self.root / '.cz.toml'
        cz.write_text(cz.read_text() + 'version_files=["Cargo.*:version"]\n')
        self.assertEqual(tomllib.loads(self.plan()[lock])['version'], 4)
        self.assertEqual(tomllib.loads(self.plan()[lock])['package'][1]['version'], '1.2.3')

    def test_cargo_write_failure_does_not_block_commit_or_tag(self):
        def git(*args):
            return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True, text=True).stdout
        git('init', '-b', 'master')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'user.name', 'Test')
        git('config', 'commit.gpgsign', 'false')
        git('config', 'tag.gpgsign', 'false')
        self.manifest()
        self.lock()
        git('add', '.')
        git('commit', '-m', 'feat: initial')
        original = Path.write_text
        def fail(path, *args, **kwargs):
            if path.name.startswith('Cargo.'):
                raise PermissionError('denied')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', new=fail), self.assertLogs('git_tools.generators.bumpgen', level='WARNING'):
            result = run_bump(BumpOptions(increment='PATCH', yes=True), cwd=self.root)
        self.assertEqual(str(result), '1.2.4')
        self.assertIn('1.2.4', git('tag'))
        self.assertEqual(git('show', '--pretty=', '--name-only', 'HEAD').strip(), '.cz.toml')

    def test_real_preview_and_successful_bump(self):
        def git(*args):
            return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True, text=True).stdout
        git('init', '-b', 'master')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'user.name', 'Test')
        git('config', 'commit.gpgsign', 'false')
        git('config', 'tag.gpgsign', 'false')
        manifest = self.manifest()
        lock = self.lock()
        git('add', '.')
        git('commit', '-m', 'feat: initial')
        head = git('rev-parse', 'HEAD')
        before = {p: p.read_bytes() for p in (self.root / '.cz.toml', manifest, lock)}
        for preview in ({'dry_run': True}, {'get_next': True}):
            run_bump(BumpOptions(increment='PATCH', yes=True, **preview), cwd=self.root)
            self.assertEqual(git('rev-parse', 'HEAD'), head)
            self.assertEqual(git('tag'), '')
            for path, contents in before.items():
                self.assertEqual(path.read_bytes(), contents)
        run_bump(BumpOptions(increment='PATCH', yes=True), cwd=self.root)
        self.assertEqual(tomllib.loads(manifest.read_text())['package']['version'], '1.2.4')
        self.assertEqual(tomllib.loads(lock.read_text())['package'][0]['version'], '1.2.4')
        self.assertIn('Cargo.toml', git('show', '--pretty=', '--name-only', 'HEAD'))
        self.assertIn('Cargo.lock', git('show', '--pretty=', '--name-only', 'HEAD'))
        self.assertIn('1.2.4', git('tag'))

    def test_preview_writes_nothing_and_does_not_run_cargo(self):
        # Pure planners do not write targets or invoke package managers.
        manifest = self.manifest()
        before = manifest.read_bytes()
        with patch('subprocess.run') as run:
            self.plan()
        run.assert_not_called()
        self.assertEqual(manifest.read_bytes(), before)

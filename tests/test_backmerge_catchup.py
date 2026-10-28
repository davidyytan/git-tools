"""Exercise the documented not-ahead backmerge path with real, local Git history."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest

from git_tools.generators.bumpgen import decide_version_strategy

ROOT = Path(__file__).resolve().parents[1]


class BackmergeCatchupTests(unittest.TestCase):
    def git(self, root: Path, *args: str, merging: bool = False) -> str:
        result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True)
        self.assertIn(result.returncode, (0, 1) if merging else (0,), result.stderr)
        return result.stdout.strip()

    def version(self, root: Path, value: str) -> None:
        (root / ".cz.toml").write_text(
            '[tool.commitizen]\nname = "cz_conventional_commits"\n'
            'tag_format = "$version"\nversion_scheme = "semver2"\n'
            f'version = "{value}"\n', encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            f'[project]\nname = "example-project"\nversion = "{value}"\n',
            encoding="utf-8",
        )

    def commit(self, root: Path, subject: str) -> None:
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", subject)

    def scenario(self, kind: str, meaningful: bool) -> None:
        for flow in ("classic", "variant"):
            for platform in ("github", "azure"):
                with self.subTest(kind=kind, meaningful=meaningful, flow=flow, platform=platform):
                    with tempfile.TemporaryDirectory() as tmp:
                        self.check_history(Path(tmp), kind, meaningful, flow, platform)

    def check_history(self, root: Path, kind: str, meaningful: bool, flow: str, platform: str) -> None:
        base = "0.1.0" if kind == "release" else "0.2.0"
        target = "0.2.0" if kind == "release" else "0.2.1"
        source = f"{kind}/published-fixes" if kind == "hotfix" else f"release/{target}"
        self.git(root, "init", "-b", "master")
        for key, value in (("user.name", "Test User"), ("user.email", "test@example.invalid"),
                           ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
            self.git(root, "config", key, value)
        self.version(root, base)
        (root / "app.txt").write_text("base\n", encoding="utf-8")
        self.commit(root, f"bump: version 0.0.1 -> {base}")
        self.git(root, "tag", base)
        self.git(root, "switch", "-c", "develop")
        self.version(root, f"{target}-alpha.0")
        self.commit(root, f"bump: version {base} -> {target}-alpha.0")
        self.git(root, "tag", f"{target}-alpha.0")
        # Hotfix branches start at stable master; releases start at develop.
        self.git(root, "switch", "-c", source, "master" if kind == "hotfix" else "develop")
        if meaningful:
            (root / "released-fix.txt").write_text("released regression fix\n", encoding="utf-8")
            self.commit(root, "fix: stabilize published code")
        self.version(root, f"{target}-rc.0")
        self.commit(root, f"bump: version {base} -> {target}-rc.0")
        self.git(root, "tag", f"{target}-rc.0")
        self.git(root, "switch", "develop")
        (root / "develop-work.txt").write_text("continued work without Start\n", encoding="utf-8")
        self.version(root, f"{target}-alpha.1")
        self.commit(root, f"bump: version {target}-alpha.0 -> {target}-alpha.1")
        self.git(root, "tag", f"{target}-alpha.1")
        self.git(root, "switch", "master")
        self.git(root, "merge", "--squash", source)
        self.commit(root, f"{kind.title()} {target}")
        self.version(root, target)
        self.commit(root, f"bump: version {target}-rc.0 -> {target}")
        self.git(root, "tag", target)
        published_tags = self.git(root, "tag", "--list")

        self.git(root, "switch", source)
        if platform == "azure":
            # Azure's source synchronization also folds in promoted master history.
            self.git(root, "merge", "--no-ff", "--no-commit", "master", merging=True)
            self.version(root, f"{target}-rc.0")
            self.commit(root, "chore: synchronize promoted master")
        self.git(root, "merge", "--no-ff", "--no-commit", "develop", merging=True)
        self.version(root, f"{target}-alpha.1")
        self.commit(root, "chore: merge develop for backmerge")
        prep = decide_version_strategy(root, source, flow=flow)
        self.assertFalse(prep.skip)
        self.assertFalse(prep.invalid)
        self.assertFalse(prep.create_tag)
        result = subprocess.run(
            [sys.executable, "-m", "git_tools.generators.bumpgen", *shlex.split(prep.args)],
            cwd=root, env={**os.environ, "PYTHONPATH": str(ROOT)},
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git(root, "tag", "--list"), published_tags)

        # Unlike the ahead-alpha example, resolve the boundary to published stable.
        self.git(root, "switch", "develop")
        self.git(root, "switch", "-c", "integration/backmerge-stable")
        self.git(root, "merge", "--no-ff", "--no-commit", source, merging=True)
        self.version(root, target)
        self.commit(root, "chore: prepare stable catch-up")
        self.git(root, "switch", "develop")
        if platform == "github":
            self.git(root, "merge", "--squash", "integration/backmerge-stable")
            self.commit(root, f"Backmerge {kind.title()} {target}")
        else:
            self.git(root, "merge", "--no-ff", "integration/backmerge-stable",
                     "-m", f"Backmerge {kind.title()} {target}")
            self.git(root, "merge-base", "--is-ancestor", source, "develop")
        decision = decide_version_strategy(root, "develop", flow=flow)
        self.assertFalse(decision.invalid)
        self.assertTrue(decision.skip)
        self.assertIn(f"already matches stable line {target}", decision.reason)
        self.assertEqual(tomllib.loads((root / ".cz.toml").read_text())["tool"]["commitizen"]["version"], target)
        self.assertEqual(tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"], target)
        self.assertEqual((root / "develop-work.txt").read_text(), "continued work without Start\n")
        self.assertEqual((root / "released-fix.txt").exists(), meaningful)
        self.assertEqual(self.git(root, "tag", "--list"), published_tags)
        self.assertEqual(self.git(root, "status", "--porcelain"), "")

    def test_release_catchup_retains_meaningful_fixes(self) -> None:
        self.scenario("release", True)

    def test_release_catchup_with_only_version_changes(self) -> None:
        self.scenario("release", False)

    def test_hotfix_catchup_retains_meaningful_fixes(self) -> None:
        self.scenario("hotfix", True)

    def test_hotfix_catchup_with_only_version_changes(self) -> None:
        self.scenario("hotfix", False)


if __name__ == "__main__":
    unittest.main()

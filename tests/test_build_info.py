"""What ``git-tools --version`` and the interactive header report.

``git_tools/build_info.py`` is agent-cli's ``agent_cli/build_info.py`` copied
byte for byte; these are its tests ported to unittest, with the agent-specific
``running``/``version_lines`` cases replaced by git-tools' ``_version_line``
wrapper. Set AGENT_CLI_SOURCE to an agent-cli checkout to also check the copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

import git_tools
from git_tools import build_info, cli
from git_tools.build_info import BuildInfo

needs_git = unittest.skipIf(shutil.which("git") is None, "git is not installed")


def _git(repo: Path, *args: str) -> str:
    # Free of the machine's own git config (signing, hooks, default branch).
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True, env=env,
    )
    return done.stdout.strip()


def _checkout(tmp_path: Path, *, top: Path | None = None) -> Path:
    """A git-tools checkout: its pyproject.toml beside the package folder,
    in a git work tree whose top is ``top`` (a monorepo) or the checkout."""
    repo = tmp_path / "git-tools"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "git-tools"\nversion = "1.2.0-beta.1"\n')
    (repo / "pkg" / "__init__.py").write_text("")
    top = top or repo
    _git(top, "init", "-q")
    _git(top, "add", ".")
    _git(top, "commit", "-qm", "one")
    return repo


class BuildInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp_path = Path(directory.name).resolve()

    def test_a_line_names_the_version_tag_and_commit(self) -> None:
        self.assertEqual(BuildInfo("git-tools", "0.2.0a2").describe(), "0.2.0a2")
        self.assertEqual(BuildInfo("git-tools", "0.2.0", "0.2.0", 0, "abc1234").describe(),
                         "0.2.0 · tag 0.2.0 · commit abc1234")
        self.assertEqual(BuildInfo("git-tools", "0.2.0", "0.2.0", 3, "abc1234", True).describe(),
                         "0.2.0 · tag 0.2.0 +3 · commit abc1234 (dirty)")
        self.assertEqual(BuildInfo("git-tools", "0.2.0", commit="abc1234").describe(),
                         "0.2.0 · no tag · commit abc1234")

    @needs_git
    def test_a_checkout_at_a_tag_then_past_it_then_with_changes(self) -> None:
        repo = _checkout(self.tmp_path)
        init = str(repo / "pkg" / "__init__.py")
        head = _git(repo, "rev-parse", "--short", "HEAD")
        _git(repo, "tag", "1.2.0-beta.1")
        self.assertEqual(build_info.build_info("git-tools", init),
                         BuildInfo("git-tools", "1.2.0-beta.1", "1.2.0-beta.1", 0, head))

        (repo / "pkg" / "__init__.py").write_text("x = 1\n")
        _git(repo, "commit", "-qam", "two")
        head = _git(repo, "rev-parse", "--short", "HEAD")
        self.assertEqual(build_info.build_info("git-tools", init),
                         BuildInfo("git-tools", "1.2.0-beta.1", "1.2.0-beta.1", 1, head))

        (repo / "pkg" / "__init__.py").write_text("x = 2\n")
        self.assertIs(build_info.build_info("git-tools", init).dirty, True)

    @needs_git
    def test_a_checkout_with_no_tag_still_names_its_commit(self) -> None:
        repo = _checkout(self.tmp_path)
        (repo / "pkg" / "__init__.py").write_text("x = 1\n")
        info = build_info.build_info("git-tools", str(repo / "pkg" / "__init__.py"))
        self.assertEqual((info.tag, info.commit, info.dirty), (None, _git(repo, "rev-parse", "--short", "HEAD"), True))
        # The checkout's pyproject.toml, not an editable install's stale metadata.
        self.assertEqual(info.version, "1.2.0-beta.1")

    @needs_git
    def test_a_checkout_inside_a_bigger_repository_names_that_commit(self) -> None:
        repo = _checkout(self.tmp_path, top=self.tmp_path)
        info = build_info.build_info("git-tools", str(repo / "pkg" / "__init__.py"))
        self.assertEqual(info.commit, _git(self.tmp_path, "rev-parse", "--short", "HEAD"))

    @needs_git
    def test_an_installed_package_in_some_git_work_tree_is_not_a_checkout(self) -> None:
        """A wheel in a venv that sits in a git work tree must not report that
        tree's commit, or another project's pyproject version, as its own."""
        for index, beside in enumerate((None, '[project]\nname = "someone-else"\nversion = "7.0"\n')):
            with self.subTest(beside=beside):
                outer = self.tmp_path / f"outer{index}"
                package = outer / "venv" / "site-packages" / "pkg"
                package.mkdir(parents=True)
                (package / "__init__.py").write_text("")
                if beside is not None:
                    (package.parent / "pyproject.toml").write_text(beside)
                _git(outer, "init", "-q")
                self.assertEqual(build_info.build_info("git-tools", str(package / "__init__.py")),
                                 BuildInfo("git-tools", version("git-tools")))

    def test_without_git_a_checkout_is_its_own_version_alone(self) -> None:
        repo = self.tmp_path / "repo"
        (repo / "pkg").mkdir(parents=True)
        (repo / "pyproject.toml").write_text('[project]\nname = "git-tools"\nversion = "9.9.9"\n')

        def no_git(*_args, **_kwargs):
            raise FileNotFoundError("git")

        with patch.object(build_info.subprocess, "run", no_git):
            self.assertEqual(build_info.build_info("git-tools", str(repo / "pkg" / "__init__.py")),
                             BuildInfo("git-tools", "9.9.9"))

    def test_a_package_with_no_metadata_reads_unknown(self) -> None:
        (self.tmp_path / "pkg").mkdir()
        self.assertEqual(build_info.build_info("no-such-git-tools-package", str(self.tmp_path / "pkg" / "__init__.py")),
                         BuildInfo("no-such-git-tools-package", "unknown"))


class VersionLineTests(unittest.TestCase):
    def test_the_line_is_agent_clis_row_for_this_package(self) -> None:
        build = BuildInfo("git-tools", "1.0", "1.0", 2, "bbbbbbb", True)
        with patch.object(cli, "build_info", return_value=build) as found:
            self.assertEqual(cli._version_line(), "git-tools  1.0 · tag 1.0 +2 · commit bbbbbbb (dirty)")
        found.assert_called_once_with("git-tools", git_tools.__file__)

    def test_version_flag_prints_the_line(self) -> None:
        build = BuildInfo("git-tools", "1.0", "1.0", 0, "aaaaaaa")
        with patch.object(cli, "build_info", return_value=build):
            result = CliRunner().invoke(cli.app, ["--version"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "git-tools  1.0 · tag 1.0 · commit aaaaaaa\n")

    def test_this_package_reports_its_own_version(self) -> None:
        info = build_info.build_info("git-tools", git_tools.__file__)
        self.assertEqual(info.name, "git-tools")
        self.assertTrue(info.version)
        self.assertNotEqual(info.version, "unknown")

    def test_the_copy_matches_agent_cli(self) -> None:
        source_root = os.environ.get("AGENT_CLI_SOURCE")
        if not source_root:
            self.skipTest("Set AGENT_CLI_SOURCE for a byte-for-byte comparison")
        upstream = Path(source_root) / "agent_cli" / "build_info.py"
        self.assertEqual(Path(build_info.__file__).read_bytes(), upstream.read_bytes())


if __name__ == "__main__":
    unittest.main()

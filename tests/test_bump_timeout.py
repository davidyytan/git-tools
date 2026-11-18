"""Mock-only timeout regressions; no Git repository or external commands."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import call, patch

import git_tools.generators.bumpgen.git as bump_git
import git_tools.generators.bumpgen.repo as bump_repo
import git_tools.generators.bumpgen.rules as bump_rules
from git_tools.generators.bumpgen.decision import StrategyDecision
from git_tools.generators.bumpgen.errors import GitError


class BumpTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        # Used only as a mocked command's cwd; no repository fixture is needed.
        self.root = Path(__file__).resolve().parent
        self.target = SimpleNamespace(path=Path("pyproject.toml"))
        self.before = '[project]\nname = "demo"\nversion = "1.2.0"\n'
        self.after = '[project]\nname = "demo"\nversion = "1.3.0-alpha.1"\n'
        self.commands = [
            ["git", "rev-parse", "--verify", "--quiet", "HEAD^"],
            ["git", "diff", "--name-only", "HEAD^", "HEAD"],
            ["git", "ls-tree", "HEAD^", "--", "pyproject.toml"],
            ["git", "show", "HEAD^:pyproject.toml"],
            ["git", "ls-tree", "HEAD", "--", "pyproject.toml"],
            ["git", "show", "HEAD:pyproject.toml"],
        ]

    @contextmanager
    def managed_inspection(self, timeout_at: list[str] | None = None):
        outputs = [
            "parent-sha\n",
            "pyproject.toml\n",
            "100644 blob before-sha\tpyproject.toml\n",
            self.before,
            "100644 blob after-sha\tpyproject.toml\n",
            self.after,
        ]
        responses = {tuple(args): output for args, output in zip(self.commands, outputs)}
        subprocess_options = dict(cwd=self.root, text=True, capture_output=True, check=False, timeout=120)

        def fake_run(args, **kwargs):
            self.assertEqual(kwargs, subprocess_options)
            self.assertIn(tuple(args), responses, f"Unexpected subprocess command: {args!r}")
            if args == timeout_at:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"])
            return subprocess.CompletedProcess(args, 0, responses[tuple(args)], "")

        # Keep the real runner, changed-path query, classifier, and strategy.
        # Controlled normalization isolates the conservative inspection policy, not the individual version adapters' ability to erase version fields.
        with (
            patch.object(bump_git.subprocess, "run", side_effect=fake_run) as run,
            patch.object(bump_repo, "load_bump_config", return_value=SimpleNamespace(version_targets=[self.target])) as config,
            patch.object(bump_repo, "_normalized_version_content", return_value="identical version-neutral content") as normalize,
        ):
            yield
            config.assert_called_once_with(self.root)
            expected_commands = self.commands if timeout_at is None else self.commands[:self.commands.index(timeout_at) + 1]
            self.assertEqual(run.call_args_list, [call(args, **subprocess_options) for args in expected_commands])
            expected_blobs = []
            if timeout_at is None or self.commands.index(timeout_at) > 3:
                expected_blobs.append(call(self.before, [self.target]))
            if timeout_at is None:
                expected_blobs.append(call(self.after, [self.target]))
            self.assertEqual(normalize.call_args_list, expected_blobs)

    def test_runner_timeout_raises_even_when_exit_status_check_is_disabled(self) -> None:
        args = ["git", "show", "HEAD:pyproject.toml"]
        for check in (True, False):
            with self.subTest(check=check):
                timeout = subprocess.TimeoutExpired(args, 120)
                with patch.object(bump_git.subprocess, "run", side_effect=timeout) as run:
                    with self.assertRaises(GitError) as caught:
                        bump_git.run_command(args, cwd=self.root, check=check)
                self.assertIs(caught.exception.__cause__, timeout)
                self.assertIn("timed out after 120 seconds", str(caught.exception))
                self.assertIn("Inspect repository state before retrying", str(caught.exception))
                self.assertIn("files, staging, commits or tags may already have changed", str(caught.exception))
                run.assert_called_once_with(args, cwd=self.root, text=True, capture_output=True, check=False, timeout=120)

    def test_managed_inspection_timeout_is_conservatively_meaningful(self) -> None:
        for timeout_at in (None, *self.commands[2:]):
            with self.subTest(timeout_at=timeout_at), self.managed_inspection(timeout_at):
                meaningful = bump_repo.latest_commit_has_meaningful_changes(self.root)
                # The successful control recognizes version-only contents. A runner GitError is absorbed here, not propagated to the caller.
                self.assertIs(meaningful, timeout_at is not None)

    def test_ahead_alpha_backmerge_timeout_selects_bump_instead_of_version_only_skip(self) -> None:
        for kind, target in (("release", "1.2.0"), ("hotfix", "1.2.1")):
            decision = StrategyDecision(
                skip=False,
                invalid=False,
                branch="develop",
                current_version="1.3.0-alpha.1",
                current_release_line="1.3.0",
                current_is_prerelease=True,
                subject=f"Backmerge {kind.title()} {target}",
            )
            for timeout_at in (None, *self.commands[2:]):
                with self.subTest(kind=kind, timeout_at=timeout_at), self.managed_inspection(timeout_at):
                    outcome = bump_rules.decide_develop_strategy(self.root, decision)
                    self.assertFalse(outcome.invalid)
                    self.assertEqual(outcome.error, "")
                    if timeout_at is None:
                        self.assertTrue(outcome.skip)
                        self.assertEqual(outcome.args, "")
                        self.assertIn("version-only or no-op", outcome.reason)
                    else:
                        # Unknown managed content deliberately follows the meaningful-change branch; it is not a timeout abort.
                        self.assertFalse(outcome.skip)
                        self.assertEqual(outcome.mode, f"develop-backmerge-{kind}")
                        self.assertEqual(outcome.args, "--yes --increment PATCH --prerelease alpha --no-tag")
                        self.assertFalse(outcome.create_tag)


if __name__ == "__main__":
    unittest.main()

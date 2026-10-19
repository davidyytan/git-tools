"""Version visibility must be independent of repository state and CLI actions."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from typer.testing import CliRunner

import git_tools
from git_tools import cli


class VersionDisplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_version_flags_print_one_plain_line_and_exit_before_any_action(self) -> None:
        version = "9.8.7+test.1"
        for arguments in (
            ["--version"],
            ["-V"],
            ["--version", "commit"],
            ["-V", "init", "--version", "1.2.3"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(cli, "__version__", version),
                patch.object(cli, "_setup_logging") as logging,
                patch.object(cli, "_has_interactive_terminal") as terminal,
                patch.object(cli.questionary, "select") as select,
                patch.object(cli, "_run_settings_menu") as settings_menu,
                patch("git_tools.generators.commitgen.CommitGenerator") as commit,
                patch("git_tools.generators.initgen.CommitizenInitGenerator") as init,
                patch("subprocess.run") as run,
                patch("subprocess.Popen") as popen,
            ):
                result = self.runner.invoke(cli.app, arguments, color=True)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(result.output, f"git-tools {version}\n")
            self.assertEqual(result.stderr, "")
            for action in (logging, terminal, select, settings_menu, commit, init, run, popen):
                action.assert_not_called()

    def test_noninteractive_help_does_not_print_a_version_header(self) -> None:
        version = "9.8.7+help-header-sentinel"
        for arguments in ([], ["--help"], ["commit", "--help"],
                          ["init", "--help"], ["settings", "--help"]):
            with (
                self.subTest(arguments=arguments),
                patch.object(cli, "__version__", version),
                patch.object(cli, "_has_interactive_terminal", return_value=False),
                patch.object(cli.questionary, "select") as select,
            ):
                result = self.runner.invoke(cli.app, arguments)

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Usage:", result.output)
            self.assertNotIn(version, result.output)
            select.assert_not_called()

    def test_direct_command_does_not_print_a_version_header(self) -> None:
        with (
            patch.object(cli, "__version__", "9.8.7+direct-header-sentinel"),
            patch.object(cli.questionary, "select") as select,
            patch("git_tools.generators.commitgen.CommitGenerator") as generator,
        ):
            result = self.runner.invoke(cli.app, ["commit"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "")
        generator.return_value.generate_commit.assert_called_once_with()
        select.assert_not_called()

    def test_init_version_remains_an_independent_command_option(self) -> None:
        with (
            patch.object(cli, "__version__", "9.8.7+tool-version"),
            patch.object(cli.questionary, "select") as select,
            patch("git_tools.generators.initgen.CommitizenInitGenerator") as generator,
        ):
            result = self.runner.invoke(cli.app, ["init", "--version", "1.2.3"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(result.output, "")
        generator.assert_called_once()
        self.assertEqual(generator.call_args.kwargs["version"], "1.2.3")
        generator.return_value.generate_init.assert_called_once_with()
        select.assert_not_called()

    def test_interactive_header_is_dim_literal_and_once_across_settings_returns(self) -> None:
        version = "9.8.7+[literal]"
        ctx = SimpleNamespace(invoked_subcommand=None, invoke=Mock())
        with (
            patch.object(cli, "__version__", version),
            patch.object(cli, "_setup_logging"),
            patch.object(cli, "_has_interactive_terminal", return_value=True),
            patch.object(cli, "_run_settings_menu") as settings_menu,
            patch.object(cli, "reload_settings") as reload,
            patch.object(cli.questionary, "select") as select,
            patch.object(cli.console, "print") as printed,
        ):
            select.return_value.ask.side_effect = ["settings", "settings", "commit"]
            cli.main(ctx)

        header = call(f"git-tools {version}", style="dim", markup=False)
        self.assertEqual(printed.call_args_list[0], header)
        self.assertEqual(printed.call_args_list.count(header), 1)
        self.assertEqual(settings_menu.call_count, 2)
        self.assertEqual(reload.call_count, 2)
        ctx.invoke.assert_called_once_with(cli.commit, interactive=True)


class PackageVersionTests(unittest.TestCase):
    def test_package_version_comes_from_distribution_metadata(self) -> None:
        # Execute the package initializer in a fresh namespace, not reload():
        # imported CLI modules must retain their original package/version state.
        with patch("importlib.metadata.version", return_value="4.5.6rc1") as metadata:
            namespace = runpy.run_path(str(Path(git_tools.__file__)))

        self.assertEqual(namespace["__version__"], "4.5.6rc1")
        metadata.assert_called_once_with("git-tools")

    def test_missing_distribution_metadata_falls_back_without_reloading_package(self) -> None:
        original_version = git_tools.__version__
        with patch(
            "importlib.metadata.version",
            side_effect=PackageNotFoundError("git-tools"),
        ) as metadata:
            namespace = runpy.run_path(str(Path(git_tools.__file__)))

        self.assertEqual(namespace["__version__"], "unknown")
        self.assertEqual(git_tools.__version__, original_version)
        metadata.assert_called_once_with("git-tools")


if __name__ == "__main__":
    unittest.main()

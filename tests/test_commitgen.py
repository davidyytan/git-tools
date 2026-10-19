from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.generators.commitgen import CommitGenerator, SensitiveFileMatch


class CommitGeneratorTests(unittest.TestCase):
    def test_display_response_omits_raw_response_panel(self) -> None:
        for interactive in (False, True):
            with self.subTest(interactive=interactive):
                generator = CommitGenerator(interactive=interactive)
                response = {"content": "```\nfix: avoid duplicate output\n```"}
                with (
                    patch.object(generator, "display_reasoning"),
                    patch("git_tools.generators.commitgen.generator.console") as console,
                ):
                    generator._display_response(response)

                panels = [call.args[0] for call in console.print.call_args_list if call.args]
                self.assertEqual([panel.title for panel in panels], ["[bold]Commit Message[/bold]"])
                self.assertEqual(panels[0].renderable, "fix: avoid duplicate output")

    def test_system_message_lists_supported_types_and_commit_guidance(self) -> None:
        generator = CommitGenerator(interactive=False)

        system_message = generator._build_system_message(
            include_scope=True,
            include_footer=True,
        )

        self.assertIn("chore: Maintenance or operational changes", system_message)
        self.assertIn("docs: Documentation-only changes", system_message)
        self.assertIn("revert: Reverts a previous commit", system_message)
        self.assertIn("Prefer the most specific type", system_message)
        self.assertIn("use `style` for formatting-only or text-only changes", system_message)
        self.assertIn("use `chore` for maintenance, repo housekeeping", system_message)
        self.assertIn("[optional scope] may be provided", system_message)
        self.assertIn("Include [optional footer(s)] for breaking changes.", system_message)
        self.assertIn(
            "Do not use the literal text BREAKING CHANGE anywhere except in the footer.",
            system_message,
        )

    def test_system_message_can_disable_scope_and_footer(self) -> None:
        generator = CommitGenerator(interactive=False)

        system_message = generator._build_system_message(
            include_scope=False,
            include_footer=False,
        )

        self.assertIn("Do not include the [optional scope].", system_message)
        self.assertIn("Do not include the [optional footer(s)].", system_message)

    def test_parser_preserves_prose_bullets_and_footer_separation(self) -> None:
        generator = CommitGenerator()
        messages = (
            "feat(parser)!: preserve paragraphs\n\nFirst paragraph.  \n\nSecond paragraph.\n\nBREAKING CHANGE: keep this detail\n\nRefs: #42",
            "fix: preserve list indentation\n\n- First detail\n  continuation line  \n\n- Second detail\n    nested context\n\nCloses: #42",
            "fix: preserve paragraph gaps\n\nParagraph one\n\n\nParagraph two\n \t\nRefs: #7  ",
            "fix: preserve CRLF\r\n\r\nFirst paragraph\r\n\r\nSecond paragraph\r\n\r\nRefs: #7",
        )
        for expected in messages:
            for opening, closing in ((None, None), ("```", "```"), ("```text", "```"), ("~~~text", "~~~"), ("````", "`````")):
                with self.subTest(expected=expected, opening=opening):
                    raw = expected if opening is None else f"{opening}\n{expected}\n{closing}"
                    self.assertEqual(generator.parse_commit_message(raw), expected)

    def test_parser_normalizes_only_boundaries_and_header_separator(self) -> None:
        generator = CommitGenerator()
        expected = "fix: retain details\n\n  Indented paragraph  \n\nAnother paragraph\n\nRefs: #42  "
        for raw in (
            expected,
            expected.replace("details\n\n", "details\n", 1),
            expected.replace("details\n\n", "details\n \t\n\n", 1),
            f"\n\n{expected}\n\n",
            f"\n```text\n\n{expected}\n\n```\n\n",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(generator.parse_commit_message(raw), expected)
        self.assertEqual(generator.parse_commit_message("\nfix: subject only\n\n"), "fix: subject only")
        self.assertEqual(generator.parse_commit_message("fix!: breaking subject"), "fix!: breaking subject")

    def test_parser_only_unwraps_complete_matching_outer_fences(self) -> None:
        generator = CommitGenerator()
        message = "fix: preserve every detail\n\nFinal important paragraph"
        invalid = (
            "", "fix:", "fix:  ", "fix\n\nNot a subject", "not a commit",
            f"```text\n{message}",
            f"```text\n{message}\n~~~",
            f"````text\n{message}\n```",
            f"```text\n{message}\n``` trailing detail",
            f"```te`xt\n{message}\n```",
            f"    ```text\n{message}\n```",
            f"```text\n{message}\n    ```",
            f"Here is your commit:\n```\n{message}\n```",
            f"```\n{message}\n```\nFinal important detail",
            f"```\n{message}\n```\nOther detail\n```",
            f"```\n{message}\n```\n\n```\nfix: another message\n```",
        )
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assertIsNone(generator.parse_commit_message(raw))

    def test_parser_never_extracts_inner_fences_or_drops_unmatched_body_fences(self) -> None:
        generator = CommitGenerator()
        message = "fix: keep embedded example\n\nExample:\n```python\nprint('important')\n```\n\nFinal detail"
        self.assertEqual(generator.parse_commit_message(message), message)
        self.assertEqual(generator.parse_commit_message(f"````text\n{message}\n````"), message)
        for suffix in ("\n```", "\n~~~", "\n```text\nunclosed content"):
            with self.subTest(suffix=suffix):
                self.assertEqual(generator.parse_commit_message(message + suffix), message + suffix)

    def test_preserved_message_matches_display_clipboard_and_git_payloads(self) -> None:
        expected = "feat(parser)!: keep all details\n\nFirst paragraph.\n\n- Detail\n  continued detail  \n\nBREAKING CHANGE: preserve footer\n\nRefs: #42  "
        for interactive in (False, True):
            for fenced in (False, True):
                with self.subTest(interactive=interactive, fenced=fenced):
                    generator = CommitGenerator(interactive=interactive, auto_commit=True)
                    raw = f"```text\n{expected}\n```" if fenced else expected
                    response = {"content": raw}
                    with (
                        patch.object(generator, "display_reasoning"),
                        patch("git_tools.generators.commitgen.generator.console") as console,
                    ):
                        generator._display_response(response)
                    panels = [call.args[0] for call in console.print.call_args_list if call.args]
                    self.assertEqual(panels[0].renderable, expected)
                    with patch("git_tools.generators.commitgen.generator.subprocess.run") as run:
                        generator._handle_commit_action(response)
                    run.assert_called_once_with(["git", "commit", "-m", expected], check=True, timeout=30)
                    generator._cli_auto_commit = False
                    with patch.object(generator, "handoff_to_clipboard") as clipboard:
                        generator._handle_commit_action(response)
                    clipboard.assert_called_once_with(expected, leading_space=False)

    def test_noninteractive_sensitive_files_fail_without_prompting(self) -> None:
        generator = CommitGenerator(interactive=False)

        with (
            patch.object(generator, "_detect_sensitive_files", return_value=[".env"]),
            patch.object(generator, "_confirm_commit_sensitive_files") as confirm_mock,
        ):
            allowed = generator._check_sensitive_files()

        self.assertFalse(allowed)
        confirm_mock.assert_not_called()

    def test_noninteractive_sensitive_files_explain_detection_reason(self) -> None:
        generator = CommitGenerator(interactive=False)
        sensitive_match = SensitiveFileMatch(
            path=".env",
            pattern=".env",
            reason="environment/configuration file",
        )

        with (
            patch.object(
                generator,
                "_detect_sensitive_files",
                return_value=[sensitive_match],
            ),
            patch.object(generator, "_confirm_commit_sensitive_files") as confirm_mock,
            patch("git_tools.generators.commitgen.sensitive.error") as error_mock,
        ):
            allowed = generator._check_sensitive_files()

        self.assertFalse(allowed)
        confirm_mock.assert_not_called()
        error_mock.assert_called_once()
        message = error_mock.call_args.args[0]
        self.assertIn(".env", message)
        self.assertIn("environment/configuration file", message)
        self.assertIn("matched pattern: .env", message)

    def test_detect_sensitive_files_returns_match_reasons(self) -> None:
        generator = CommitGenerator(interactive=False)

        with patch.object(
            generator,
            "_get_staged_files",
            return_value=["src/.env.local", "README.md", "certs/client.pem"],
        ):
            matches = generator._detect_sensitive_files()

        self.assertEqual(
            [match.path for match in matches],
            ["src/.env.local", "certs/client.pem"],
        )
        self.assertEqual([match.pattern for match in matches], [".env.*", "*.pem"])
        self.assertEqual(
            [match.reason for match in matches],
            [
                "environment/configuration file",
                "private key, SSH key, or certificate file",
            ],
        )

    def test_noninteractive_commit_defaults_to_direct_commit(self) -> None:
        generator = CommitGenerator(interactive=False)

        with patch("subprocess.run") as run_mock:
            generator._handle_commit_action({"content": "feat: add test coverage"})

        run_mock.assert_called_once_with(
            ["git", "commit", "-m", "feat: add test coverage"],
            check=True,
            timeout=30,
        )

    def test_open_release_respects_copy_policy_without_changing_commit_defaults(self) -> None:
        for interactive in (False, True):
            for copy_flag in (None, False, True):
                with self.subTest(interactive=interactive, copy_flag=copy_flag):
                    generator = CommitGenerator(
                        interactive=interactive,
                        workflow_kind="open-release",
                        auto_commit=False,
                        copy_clipboard=copy_flag,
                    )
                    with (
                        patch.object(generator, "_get_staged_files", return_value=[]),
                        patch.object(generator, "ask_to_copy_to_clipboard") as ask,
                        patch.object(generator, "copy_to_clipboard_auto") as auto,
                        patch("subprocess.run") as run,
                    ):
                        generator.generate_commit()
                    run.assert_not_called()
                    self.assertEqual(ask.call_count, int(interactive and copy_flag is None))
                    self.assertEqual(auto.call_count, int(copy_flag is True or (copy_flag is None and not interactive)))
                    if ask.called:
                        ask.assert_called_once_with("chore: open release")
                    if auto.called:
                        auto.assert_called_once_with("chore: open release", leading_space=False)

    def test_open_release_workflow_subject(self) -> None:
        generator = CommitGenerator(
            interactive=False,
            workflow_kind="open-release",
        )

        with patch.object(generator, "_get_staged_files", return_value=[]), patch(
            "subprocess.run"
        ) as run_mock:
            generator.generate_commit()

        run_mock.assert_called_once_with(
            ["git", "commit", "--allow-empty", "-m", "chore: open release"],
            check=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()

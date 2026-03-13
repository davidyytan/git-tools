from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.generators.commitgen import CommitGenerator


class CommitGeneratorTests(unittest.TestCase):
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

    def test_noninteractive_sensitive_files_fail_without_prompting(self) -> None:
        generator = CommitGenerator(interactive=False)

        with (
            patch.object(generator, "_detect_sensitive_files", return_value=[".env"]),
            patch.object(generator, "_confirm_commit_sensitive_files") as confirm_mock,
        ):
            allowed = generator._check_sensitive_files()

        self.assertFalse(allowed)
        confirm_mock.assert_not_called()

    def test_noninteractive_commit_defaults_to_direct_commit(self) -> None:
        generator = CommitGenerator(interactive=False)

        with patch("git_tools.generators.commitgen.subprocess.run") as run_mock:
            generator._handle_commit_action({"content": "feat: add test coverage"})

        run_mock.assert_called_once_with(
            ["git", "commit", "-m", "feat: add test coverage"],
            check=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()

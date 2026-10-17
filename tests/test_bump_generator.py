from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.generators.bumpgen import BumpGenerator


class BumpGeneratorTests(unittest.TestCase):
    def test_direct_bump_uses_commitizen_like_defaults(self) -> None:
        generator = BumpGenerator()

        with patch("git_tools.generators.bumpgen.generator.run_bump") as run_bump:
            generator.generate_bump()

        options = run_bump.call_args.args[0]
        self.assertIsNone(options.prerelease)
        self.assertFalse(options.yes)
        self.assertFalse(options.gpg_sign)
        self.assertIsNone(options.increment)
        self.assertTrue(options.respect_git_config)

    def test_interactive_bump_prompts_only_for_missing_version_choices(self) -> None:
        generator = BumpGenerator(interactive=True)
        with (
            patch.object(generator, "prompt_select", side_effect=["MINOR", "alpha", "exact"]),
            patch.object(generator, "prompt_confirm") as confirm,
        ):
            options = generator._build_options()
        self.assertEqual(options.increment, "MINOR")
        self.assertEqual(options.prerelease, "alpha")
        self.assertEqual(options.increment_mode, "exact")
        self.assertFalse(options.yes)
        self.assertFalse(options.gpg_sign)
        self.assertFalse(options.dry_run)
        confirm.assert_not_called()

    def test_explicit_choices_skip_wizard_prompts(self) -> None:
        generator = BumpGenerator(increment="PATCH", prerelease="rc", gpg_sign=True, yes=True, interactive=True)
        with patch.object(generator, "prompt_select") as select, patch.object(generator, "prompt_confirm") as confirm:
            options = generator._build_options()
        self.assertEqual(options.increment, "PATCH")
        self.assertEqual(options.prerelease, "rc")
        self.assertTrue(options.gpg_sign)
        self.assertTrue(options.yes)
        select.assert_not_called()
        confirm.assert_not_called()

    def test_get_next_skips_interactive_prompts(self) -> None:
        generator = BumpGenerator(get_next=True, interactive=True)

        with (
            patch.object(generator, "_print_repo_context"),
            patch.object(generator, "_print_summary"),
            patch.object(generator, "prompt_select") as prompt_select,
            patch.object(generator, "prompt_confirm") as prompt_confirm,
            patch("git_tools.generators.bumpgen.generator.run_bump") as run_bump,
        ):
            generator.generate_bump()

        options = run_bump.call_args.args[0]
        self.assertTrue(options.get_next)
        prompt_select.assert_not_called()
        prompt_confirm.assert_not_called()


if __name__ == "__main__":
    unittest.main()

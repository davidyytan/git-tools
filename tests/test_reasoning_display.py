"""Render preserved provider reasoning without changing its wire fields."""
from __future__ import annotations

from copy import deepcopy
import unittest
from unittest.mock import patch

from git_tools.generators.base import BaseGenerator


class ReasoningDisplayTests(unittest.TestCase):
    def test_native_openrouter_text_is_shown_and_opaque_details_are_untouched(self):
        response = {"additional_kwargs": {
            "reasoning": "  routed [reasoning]  ",
            "reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque"}],
        }}
        original = deepcopy(response)
        with patch("git_tools.generators.base.display.console.print") as output:
            BaseGenerator().display_reasoning(response)
        self.assertEqual(output.call_count, 2)
        panel = output.call_args_list[0].args[0]
        self.assertEqual(str(panel.renderable), r"routed \[reasoning]")
        self.assertNotIn("opaque", str(panel.renderable))
        self.assertEqual(response, original)

    def test_reasoning_content_takes_precedence_without_displaying_details(self):
        with patch("git_tools.generators.base.display.console.print") as output:
            BaseGenerator().display_reasoning({"additional_kwargs": {
                "reasoning_content": "main", "reasoning": "other",
            }})
        self.assertEqual(str(output.call_args_list[0].args[0].renderable), "main")

    def test_empty_or_nontext_fields_do_not_render_or_raise(self):
        for additional in (None, [], {}, {"reasoning": []},
                           {"reasoning_content": {}, "reasoning_details": [{"data": "opaque"}]},
                           {"reasoning_content": "  ", "reasoning": ""}):
            with self.subTest(additional=additional), patch("git_tools.generators.base.display.console.print") as output:
                BaseGenerator().display_reasoning({"additional_kwargs": additional})
            output.assert_not_called()


if __name__ == "__main__":
    unittest.main()

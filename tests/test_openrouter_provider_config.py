from __future__ import annotations

import unittest

from git_tools.generators.base import (
    _get_openrouter_extra_body,
    _sanitize_openrouter_provider_config,
)


class OpenRouterProviderConfigTests(unittest.TestCase):
    def test_sanitize_drops_empty_strings_and_lists(self) -> None:
        self.assertEqual(
            _sanitize_openrouter_provider_config(
                {
                    "sort": "",
                    "order": [],
                    "quantizations": ["", "fp16", None],
                    "nested": {"by": "", "partition": "providers"},
                }
            ),
            {
                "quantizations": ["fp16"],
                "nested": {"partition": "providers"},
            },
        )

    def test_extra_body_omits_empty_provider_preferences(self) -> None:
        extra_body = _get_openrouter_extra_body(
            "qwen/qwen3.5-397b-a17b",
            {"usage": {"include": True}},
            {
                "model_name": "qwen/qwen3.5-397b-a17b",
                "data_collection": "deny",
                "provider_config": {
                    "quantizations": [],
                    "order": [],
                    "sort": "",
                },
            },
        )

        self.assertEqual(
            extra_body,
            {
                "usage": {"include": True},
                "provider": {
                    "allow_fallbacks": True,
                    "data_collection": "deny",
                },
            },
        )

    def test_default_openrouter_body_no_longer_forces_throughput_sort(self) -> None:
        extra_body = _get_openrouter_extra_body(
            "deepseek/deepseek-v3.2-exp",
            {"usage": {"include": True}},
            {
                "model_name": "deepseek/deepseek-v3.2-exp",
                "data_collection": "deny",
            },
        )

        self.assertNotIn("sort", extra_body["provider"])
        self.assertEqual(extra_body["provider"]["allow_fallbacks"], True)
        self.assertEqual(extra_body["provider"]["data_collection"], "deny")


if __name__ == "__main__":
    unittest.main()

"""ACRC catalog: the endpoint's own models; VPN stays external (agent-cli's tests, as unittest)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from git_tools.providers import acrc
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog

# Synthetic OpenAI-compatible /models fixture with known and unknown display-name IDs.
LIVE_PAYLOAD = {
    "object": "list",
    "data": [
        {"id": "deepseek-v4.1-flash", "object": "model", "owned_by": "openai",
         "max_input_tokens": 1048576, "max_output_tokens": 1048576},
        {"id": "glm-5-3-flash", "object": "model", "owned_by": "openai"},
        {"id": "mimo-v2.6-pro...temporary", "object": "model", "owned_by": "openai"},
    ],
}
LIVE_IDS = ["deepseek-v4.1-flash", "glm-5-3-flash", "mimo-v2.6-pro...temporary"]


def _live_result() -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_model_catalog(LIVE_PAYLOAD), source="live",
                              fetched_at="2026-10-15T00:00:00+00:00")


class ACRCProviderTests(unittest.TestCase):
    def test_acrc_has_no_catalog_before_discovery(self) -> None:
        self.assertEqual(acrc.catalog(), CatalogFetchResult())
        self.assertEqual(acrc.MODELS, ())
        self.assertEqual(acrc.PROVIDER_ID, "acrc")
        self.assertEqual(acrc.BASE_URL, "https://fmodel.ai.acrc.a-star.edu.sg/v1")
        self.assertEqual(acrc.DEFAULT_MODEL, "deepseek-v4.1-flash")
        self.assertEqual(acrc.PRESET["default_model"], acrc.DEFAULT_MODEL)

    def test_acrc_resolve_catalog_uses_live_ids_verbatim_with_default_first(self) -> None:
        live = _live_result()
        self.assertEqual([e.id for e in live.entries], LIVE_IDS)  # parser sorts by label
        resolved = acrc.resolve_catalog(live)
        self.assertEqual(resolved.source, "live")
        self.assertIsNone(resolved.error)
        self.assertEqual(resolved.fetched_at, live.fetched_at)
        self.assertEqual([e.id for e in resolved.entries], LIVE_IDS)
        self.assertEqual(resolved.entries[0].id, acrc.DEFAULT_MODEL)
        # Static display names overlay discovered IDs only; unknown IDs show as-is.
        self.assertEqual(resolved.entries[0].display_name, "DeepSeek V4.1 Flash")
        self.assertEqual(resolved.entries[1].display_name, "GLM 5-3 Flash")
        self.assertIsNone(resolved.entries[2].display_name)
        self.assertEqual(resolved.entries[2].label, "mimo-v2.6-pro...temporary")

        # The default is pinned first even when the server lists it later.
        shuffled = CatalogFetchResult(entries=tuple(reversed(live.entries)), source="live")
        self.assertEqual([e.id for e in acrc.resolve_catalog(shuffled).entries],
                         ["deepseek-v4.1-flash", "mimo-v2.6-pro...temporary", "glm-5-3-flash"])

    def test_acrc_resolve_catalog_has_no_replacement_choices_when_unavailable(self) -> None:
        for live in (
            CatalogFetchResult(error_kind="network", error="connection refused"),
            CatalogFetchResult(error_kind="auth", error="no api key", status=401),
            CatalogFetchResult(source="live", entries=()),
            CatalogFetchResult(),
        ):
            with self.subTest(live=live):
                resolved = acrc.resolve_catalog(live)
                self.assertEqual(resolved, replace(live, entries=()))


if __name__ == "__main__":
    unittest.main()

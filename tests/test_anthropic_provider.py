"""Anthropic catalog: the native Models API, with its own headers (agent-cli's tests, as unittest)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from git_tools.providers import anthropic
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog

# Shape of GET /v1/models on api.anthropic.com: typed entries with display
# names, including a dated snapshot the built-in list does not know.
LIVE_PAYLOAD = {
    "data": [
        {"type": "model", "id": "claude-sonnet-5-5", "display_name": "Claude Sonnet 5.5",
         "created_at": "2026-06-01T00:00:00Z"},
        {"type": "model", "id": "claude-opus-5-5", "display_name": "Claude Opus 5.5",
         "created_at": "2026-06-01T00:00:00Z"},
        {"type": "model", "id": "claude-sonnet-5-5-20260601",
         "display_name": "Claude Sonnet 5.5 (2026-06-01)", "created_at": "2026-06-01T00:00:00Z"},
        {"type": "model", "id": "claude-haiku-5-5", "created_at": "2026-06-01T00:00:00Z"},
    ],
    "has_more": False,
    "first_id": "claude-sonnet-5-5",
    "last_id": "claude-haiku-5-5",
}
# Default first, then the parser's label order (the unnamed haiku sorts by its
# id, after the display names); the server's own names kept.
LIVE_IDS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5-20260601", "claude-haiku-5-5"]


def _live_result() -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_model_catalog(LIVE_PAYLOAD), source="live",
                              fetched_at="2026-10-15T00:00:00+00:00")


class AnthropicProviderTests(unittest.TestCase):
    def test_anthropic_curated_catalog(self) -> None:
        result = anthropic.catalog()
        self.assertIsNone(result.error)
        self.assertEqual(result.source, "live")
        self.assertEqual(anthropic.PROVIDER_ID, "anthropic")
        self.assertEqual(anthropic.BASE_URL, "https://api.anthropic.com/v1")
        self.assertEqual([entry.id for entry in result.entries],
                         ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"])
        self.assertEqual(result.entries[0].id, anthropic.DEFAULT_MODEL)

    def test_anthropic_fetch_sends_its_own_auth_and_version_headers(self) -> None:
        calls = []

        def fake_fetch(base_url, api_key, *, timeout, headers, query=None):
            calls.append((base_url, api_key, timeout, dict(headers), query))
            return _live_result()

        with patch.object(anthropic, "fetch_model_catalog_sync", fake_fetch):
            result = anthropic.fetch_catalog_sync("https://api.anthropic.com/v1/", "sk-ant-test", timeout=2.5)
        self.assertEqual(result.source, "live")
        # The Models API pages at 20 by default, so the whole list is requested.
        self.assertEqual(calls, [(
            "https://api.anthropic.com/v1/", "sk-ant-test", 2.5,
            {"anthropic-version": "2023-06-01", "x-api-key": "sk-ant-test"},
            "limit=1000",
        )])
        self.assertEqual(anthropic.catalog_headers(""), {"anthropic-version": "2023-06-01"})

    def test_anthropic_resolve_catalog_uses_live_ids_verbatim_with_default_first(self) -> None:
        live = _live_result()
        resolved = anthropic.resolve_catalog(live)
        self.assertEqual(resolved.source, "live")
        self.assertIsNone(resolved.error)
        self.assertEqual(resolved.fetched_at, live.fetched_at)
        self.assertEqual([e.id for e in resolved.entries], LIVE_IDS)
        self.assertEqual(resolved.entries[0].id, anthropic.DEFAULT_MODEL)
        # The server's display names win; the built-in one fills a missing name;
        # an unknown id without a name shows as-is.
        self.assertEqual(resolved.entries[0].display_name, "Claude Opus 5.5")
        self.assertEqual(resolved.entries[1].display_name, "Claude Sonnet 5.5")
        self.assertEqual(resolved.entries[2].display_name, "Claude Sonnet 5.5 (2026-06-01)")
        self.assertEqual(resolved.entries[3].display_name, "Claude Haiku 5.5")
        unnamed = CatalogFetchResult(entries=parse_model_catalog({"data": [{"id": "claude-next-fixture"}]}),
                                     source="live")
        self.assertEqual(anthropic.resolve_catalog(unnamed).entries[0].label, "claude-next-fixture")

    def test_anthropic_resolve_catalog_falls_back_to_the_builtin_list(self) -> None:
        for live in (
            CatalogFetchResult(error_kind="network", error="connection refused"),
            CatalogFetchResult(error_kind="auth", error="invalid x-api-key", status=401),
            CatalogFetchResult(source="live", entries=()),
            CatalogFetchResult(),
        ):
            with self.subTest(live=live):
                resolved = anthropic.resolve_catalog(live)
                self.assertEqual(resolved.entries, anthropic.MODELS)
                self.assertEqual(resolved.source, "live")  # not a stale cache: it is the shipped list
                self.assertEqual(resolved.error, live.error)
                self.assertEqual(resolved.error_kind, live.error_kind)
                self.assertEqual(resolved.status, live.status)


if __name__ == "__main__":
    unittest.main()

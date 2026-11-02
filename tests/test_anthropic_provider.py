"""Anthropic catalog: the native Models API, with its own headers (agent-cli's tests, as unittest)."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from git_tools.providers import anthropic
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog

# Synthetic native /models fixture with server display names, an unnamed ID, and a dated snapshot.
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
# Default first, then the parser's label order (the unnamed haiku sorts by its ID, after the display names); the server's own names are kept.
LIVE_IDS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5-20260601", "claude-haiku-5-5"]


def _live_result() -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_model_catalog(LIVE_PAYLOAD), source="live",
                              fetched_at="2026-10-15T00:00:00+00:00")


class AnthropicProviderTests(unittest.TestCase):
    def test_anthropic_has_no_catalog_before_discovery(self) -> None:
        self.assertEqual(anthropic.catalog(), CatalogFetchResult())
        self.assertEqual(anthropic.MODELS, ())
        self.assertEqual(anthropic.PROVIDER_ID, "anthropic")
        self.assertEqual(anthropic.BASE_URL, "https://api.anthropic.com/v1")
        self.assertEqual(anthropic.DEFAULT_MODEL, "claude-opus-5-5")
        self.assertEqual(anthropic.PRESET["default_model"], anthropic.DEFAULT_MODEL)

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
        # The server's display names win; static labels fill missing names on discovered IDs only; unknown IDs without names show as-is.
        self.assertEqual(resolved.entries[0].display_name, "Claude Opus 5.5")
        self.assertEqual(resolved.entries[1].display_name, "Claude Sonnet 5.5")
        self.assertEqual(resolved.entries[2].display_name, "Claude Sonnet 5.5 (2026-06-01)")
        self.assertEqual(resolved.entries[3].display_name, "Claude Haiku 5.5")
        unnamed = CatalogFetchResult(entries=parse_model_catalog({"data": [{"id": "claude-next-fixture"}]}),
                                     source="live")
        self.assertEqual(anthropic.resolve_catalog(unnamed).entries[0].label, "claude-next-fixture")

    def test_anthropic_resolve_catalog_has_no_replacement_choices_when_unavailable(self) -> None:
        for live in (
            CatalogFetchResult(error_kind="network", error="connection refused"),
            CatalogFetchResult(error_kind="auth", error="invalid x-api-key", status=401),
            CatalogFetchResult(source="live", entries=()),
            CatalogFetchResult(),
        ):
            with self.subTest(live=live):
                resolved = anthropic.resolve_catalog(live)
                self.assertEqual(resolved, replace(live, entries=()))

    def test_anthropic_fetch_preserves_native_auth_failure(self) -> None:
        failed = CatalogFetchResult(error_kind="auth", error="invalid x-api-key", status=403)
        with patch.object(anthropic, "fetch_model_catalog_sync", return_value=failed) as fetch:
            result = anthropic.fetch_catalog_sync(anthropic.BASE_URL, "sk-ant-fixture")
        fetch.assert_called_once_with(
            anthropic.BASE_URL, "sk-ant-fixture", timeout=4.0,
            headers={"anthropic-version": anthropic.API_VERSION, "x-api-key": "sk-ant-fixture"},
            query=anthropic.CATALOG_QUERY,
        )
        self.assertIs(result, failed)
        self.assertEqual(anthropic.resolve_catalog(result), failed)


if __name__ == "__main__":
    unittest.main()

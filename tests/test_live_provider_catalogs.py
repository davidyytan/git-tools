"""Offline contract for live-only catalogs, including the Copilot proxy."""

from __future__ import annotations

import unittest
from dataclasses import replace

from git_tools.providers import acrc, anthropic, copilot, openai
from git_tools.providers.catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDERS = (openai, acrc, anthropic, copilot)
RESOLVING_PROVIDERS = (openai, acrc, anthropic)
FETCHED_AT = "2026-10-15T00:00:00+00:00"


class LiveProviderCatalogTests(unittest.TestCase):
    def test_catalogs_have_no_static_choices_but_keep_profile_defaults(self) -> None:
        for provider, expected_default in zip(PROVIDERS, (
            "gpt-6-astra", "deepseek-v4.1-flash", "claude-opus-5-5", "gpt-4.1",
        )):
            with self.subTest(provider=provider.PROVIDER_ID):
                self.assertEqual(provider.MODELS, ())
                self.assertEqual(provider.catalog(), CatalogFetchResult())
                self.assertEqual(provider.DEFAULT_MODEL, expected_default)
                self.assertEqual(provider.PRESET, {
                    "type": provider.PROVIDER_ID,
                    "base_url": provider.BASE_URL,
                    "default_model": expected_default,
                    "profile": provider.PROFILE,
                })

    def test_copilot_has_no_offline_catalog(self) -> None:
        self.assertEqual(copilot.PROVIDER_ID, "copilot")
        self.assertEqual(copilot.BASE_URL, "http://127.0.0.1:4141/v1")
        self.assertEqual(copilot.catalog().entries, ())
        self.assertEqual(copilot.catalog().source, "none")
        self.assertEqual(copilot.PRESET["default_model"], "gpt-4.1")

    def test_failures_discard_entries_and_preserve_all_fetch_metadata(self) -> None:
        failures = (
            {"error_kind": "network", "error": "connection refused"},
            {"error_kind": "auth", "error": "invalid key", "status": 401},
            {"error_kind": "auth", "error": "payment required", "status": 402},
            {"error_kind": "auth", "error": "forbidden", "status": 403},
            {"error_kind": "server", "error": "service unavailable", "status": 503},
            {"error_kind": "http", "error": "not found", "status": 404},
            {"error_kind": "malformed", "error": "invalid catalog"},
            {"error_kind": "network"},
            {"error": "discovery unavailable"},
            {"status": 500},
        )
        for provider in RESOLVING_PROVIDERS:
            for source in ("none", "live", "cache"):
                for metadata in failures:
                    with self.subTest(provider=provider.PROVIDER_ID, source=source, metadata=metadata):
                        failed = CatalogFetchResult(
                            entries=(ModelCatalogEntry(id=provider.DEFAULT_MODEL),),
                            source=source, fetched_at=FETCHED_AT, **metadata,
                        )
                        self.assertEqual(provider.resolve_catalog(failed), replace(failed, entries=()))

    def test_nonlive_entries_are_not_promoted_to_live_choices(self) -> None:
        for provider in RESOLVING_PROVIDERS:
            for source in ("none", "cache"):
                with self.subTest(provider=provider.PROVIDER_ID, source=source):
                    unavailable = CatalogFetchResult(
                        entries=(ModelCatalogEntry(id=provider.DEFAULT_MODEL),),
                        source=source, fetched_at=FETCHED_AT,
                    )
                    self.assertEqual(provider.resolve_catalog(unavailable), replace(unavailable, entries=()))

    def test_successful_empty_discovery_keeps_live_metadata_without_errors(self) -> None:
        for provider in RESOLVING_PROVIDERS:
            with self.subTest(provider=provider.PROVIDER_ID):
                empty = CatalogFetchResult(source="live", status=200, fetched_at=FETCHED_AT)
                self.assertEqual(provider.resolve_catalog(empty), empty)

    def test_live_choices_preserve_server_names_and_order_except_default_pinning(self) -> None:
        for provider, named_id, unknown_id in (
            (openai, "gpt-6.1-sol", "o9-fixture"),
            (acrc, "glm-5-3-flash", "unknown-acrc-fixture"),
            (anthropic, "claude-sonnet-5-5", "claude-unknown-fixture"),
        ):
            with self.subTest(provider=provider.PROVIDER_ID):
                unknown = ModelCatalogEntry(id=unknown_id, display_name="Z server label")
                named = ModelCatalogEntry(id=named_id, display_name="A server label")
                default = ModelCatalogEntry(id=provider.DEFAULT_MODEL, display_name="Server default label")
                live = CatalogFetchResult(
                    entries=(unknown, named, default), source="live", status=200, fetched_at=FETCHED_AT,
                )
                self.assertEqual(provider.resolve_catalog(live), replace(live, entries=(default, unknown, named)))
                without_default = replace(live, entries=(unknown, named))
                self.assertEqual(provider.resolve_catalog(without_default), without_default)
                self.assertNotIn(provider.DEFAULT_MODEL, [entry.id for entry in provider.resolve_catalog(without_default).entries])


if __name__ == "__main__":
    unittest.main()

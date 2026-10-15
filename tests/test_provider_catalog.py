"""Shared catalog transport and cache (agent-cli's tests, as unittest)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from git_tools.providers import qwen
from git_tools.providers.catalog import (
    CatalogFetchResult,
    ModelCatalogEntry,
    load_cached_catalog,
    parse_model_catalog,
    save_cached_catalog,
)


class ProviderCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)

    def test_parse_sparse_openai_catalog_keeps_id_only_compatibility(self) -> None:
        self.assertEqual(parse_model_catalog({"data": [{"id": "gpt-5.4"}]}),
                         (ModelCatalogEntry(id="gpt-5.4"),))

    def test_catalog_cache_is_scoped_to_provider_base_and_api_key(self) -> None:
        path = self.tmp_path / "model-catalog.json"
        live = CatalogFetchResult(
            entries=(ModelCatalogEntry(id="gpt-5.4", display_name="GPT 5.4"),),
            source="live",
            fetched_at="2026-07-17T00:00:00+00:00",
        )
        save_cached_catalog(path, provider="custom", base_url="https://EXAMPLE.COM/v1/",
                            api_key="key-a", result=live)

        cached = load_cached_catalog(path, provider="custom", base_url="https://example.com/v1",
                                     api_key="key-a")
        other_key = load_cached_catalog(path, provider="custom", base_url="https://example.com/v1",
                                        api_key="key-b")

        self.assertEqual(cached.source, "cache")
        self.assertEqual(cached.entries, (ModelCatalogEntry(id="gpt-5.4", display_name="GPT 5.4"),))
        self.assertEqual(cached.fetched_at, "2026-07-17T00:00:00+00:00")
        self.assertEqual(other_key.entries, ())
        self.assertNotIn("key-a", path.read_text(encoding="utf-8"))

    def test_catalog_cache_preserves_case_sensitive_url_path(self) -> None:
        path = self.tmp_path / "model-catalog.json"
        live = CatalogFetchResult(entries=(ModelCatalogEntry(id="model"),), source="live")
        save_cached_catalog(path, provider="custom", base_url="https://EXAMPLE.COM/coding/V1/",
                            api_key="key", result=live)

        self.assertTrue(load_cached_catalog(path, provider="custom",
                                            base_url="https://example.com/coding/V1", api_key="key").entries)
        self.assertFalse(load_cached_catalog(path, provider="custom",
                                             base_url="https://example.com/coding/v1", api_key="key").entries)

    def test_catalog_cache_ignores_unknown_version(self) -> None:
        path = self.tmp_path / "model-catalog.json"
        live = CatalogFetchResult(entries=(ModelCatalogEntry(id="model"),), source="live")
        save_cached_catalog(path, provider="custom", base_url="https://example.com/v1",
                            api_key="key", result=live)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["version"] = 999
        path.write_text(json.dumps(payload), encoding="utf-8")

        self.assertEqual(load_cached_catalog(path, provider="custom", base_url="https://example.com/v1",
                                             api_key="key").entries, ())

    def test_qwen_curated_catalog_leads_with_the_default_model(self) -> None:
        """The qwen catalog is a constant, not a fetch: the picker renders it in
        this order, so the default must come first."""
        result = qwen.catalog()
        self.assertEqual(result.source, "live")
        self.assertEqual([entry.id for entry in result.entries], ["qwen3.8-max", "qwen3.8-max-preview"])
        self.assertEqual(result.entries[0].id, qwen.DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()

"""Kimi Code catalog codec, cache and thinking choices (agent-cli's tests, as unittest)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from git_tools.providers.catalog import CatalogFetchResult
from git_tools.providers.kimi_code import (
    KimiCodeModelEntry,
    default_choice_index,
    load_cached_kimi_code_catalog,
    parse_kimi_code_catalog,
    resolve_catalog,
    save_cached_kimi_code_catalog,
    thinking_choices,
)


class KimiCodeProviderTests(unittest.TestCase):
    def test_parse_current_kimi_code_catalog_preserves_metadata(self) -> None:
        entries = parse_kimi_code_catalog({"data": [{
            "id": "k3", "display_name": "K3", "context_length": 262144, "protocol": "kimi",
            "supports_reasoning": True, "supports_image_in": True, "supports_video_in": False,
            "supports_tool_use": True, "supports_thinking_type": "both",
            "think_efforts": {"support": True, "valid_efforts": ["max"], "default_effort": "max"},
        }]})

        self.assertEqual(entries, (KimiCodeModelEntry(
            id="k3", display_name="K3", context_length=262144, protocol="kimi",
            supports_reasoning=True, supports_image_in=True, supports_video_in=False,
            supports_tool_use=True, supports_thinking_type="both",
            valid_efforts=("max",), default_effort="max",
        ),))

    def test_kimi_cache_sanitizes_current_schema_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model-catalog.json"
            live = CatalogFetchResult(entries=(KimiCodeModelEntry(id="k3", valid_efforts=("max",)),), source="live")
            save_cached_kimi_code_catalog(path, base_url="https://API.KIMI.COM/coding/V1/",
                                          api_key="key-a", result=live)

            payload = json.loads(path.read_text(encoding="utf-8"))
            record = next(iter(payload["catalogs"].values()))
            record["entries"] = [{"id": "k3", "supports_thinking_type": "future-value",
                                  "valid_efforts": "max", "context_length": True}]
            path.write_text(json.dumps(payload), encoding="utf-8")

            sanitized = load_cached_kimi_code_catalog(path, base_url="https://api.kimi.com/coding/V1",
                                                      api_key="key-a")
        self.assertEqual(sanitized.entries, (KimiCodeModelEntry(id="k3"),))

    def test_kimi_catalog_fallback_distinguishes_authoritative_failures(self) -> None:
        cached = CatalogFetchResult(entries=(KimiCodeModelEntry(id="k3"),), source="cache",
                                    fetched_at="2026-07-17T00:00:00+00:00")

        for kind in ("auth", "network", "server", "malformed"):
            with self.subTest(kind=kind):
                resolved = resolve_catalog(CatalogFetchResult(error_kind=kind, error="failed"), cached)
                self.assertEqual(resolved.source, "cache")
                self.assertEqual(resolved.entries, cached.entries)
                self.assertEqual(resolved.error_kind, kind)

        authoritative = resolve_catalog(
            CatalogFetchResult(error_kind="http", error="bad request", status=400), cached)
        self.assertEqual(authoritative.source, "none")
        self.assertEqual(authoritative.entries, ())
        self.assertEqual(authoritative.status, 400)

    def test_thinking_choices_require_current_three_state_metadata(self) -> None:
        self.assertEqual(thinking_choices(KimiCodeModelEntry(id="current", supports_thinking_type="both")),
                         (("off", False, None), ("on", True, None)))
        self.assertEqual(thinking_choices(KimiCodeModelEntry(id="missing-current-field", supports_reasoning=True)), ())

    def test_default_choice_matches_current_kimi_code_resolution(self) -> None:
        entry = KimiCodeModelEntry(id="k3", supports_reasoning=True, supports_thinking_type="both",
                                   valid_efforts=("low", "high", "max"), default_effort="max")
        choices = thinking_choices(entry)
        self.assertEqual(default_choice_index(entry, choices, current_thinking=None, current_effort=None),
                         3)  # off, low, high, max

        invalid_default = KimiCodeModelEntry(id="k3", supports_reasoning=True, supports_thinking_type="both",
                                             valid_efforts=("low", "high", "max"), default_effort="ultra")
        invalid_choices = thinking_choices(invalid_default)
        self.assertEqual(default_choice_index(invalid_default, invalid_choices,
                                              current_thinking=None, current_effort=None),
                         2)  # middle declared effort: high

        disabled_default = KimiCodeModelEntry(id="toggle", supports_reasoning=False, supports_thinking_type="both")
        disabled_choices = thinking_choices(disabled_default)
        self.assertEqual(default_choice_index(disabled_default, disabled_choices,
                                              current_thinking=None, current_effort=None), 0)


if __name__ == "__main__":
    unittest.main()

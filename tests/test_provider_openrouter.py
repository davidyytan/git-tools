"""OpenRouter upstream-provider (endpoint) discovery (agent-cli's tests, as unittest).

The pin exists to keep every turn on ONE upstream prompt cache, so these cover
the parsing and ordering the picker relies on.
"""

from __future__ import annotations

import unittest

from git_tools.providers.openrouter import (
    DEFAULT_ENDPOINT_TAG,
    DEFAULT_MODEL,
    UNPINNED,
    OpenRouterEndpoint,
    parse_endpoints,
)


def _payload(*endpoints: dict) -> dict:
    return {"data": {"id": DEFAULT_MODEL, "endpoints": list(endpoints)}}


def _endpoint(tag: str, prompt: str, **extra) -> dict:
    base = {
        "tag": tag,
        "provider_name": tag.split("/")[0].title(),
        "context_length": 1048576,
        "pricing": {"prompt": prompt, "completion": "0.0000002"},
    }
    base.update(extra)
    return base


class OpenRouterEndpointTests(unittest.TestCase):
    def test_endpoints_are_ordered_cheapest_input_first(self) -> None:
        entries = parse_endpoints(_payload(
            _endpoint("fireworks", "0.00000014"),
            _endpoint("deepinfra/fp4", "0.00000008"),
            _endpoint("together", "0.00000014"),
        ))
        self.assertEqual([entry.tag for entry in entries][0], "deepinfra/fp4")

    def test_variant_tag_is_preserved_as_the_routing_slug(self) -> None:
        """`deepinfra/fp4` pins quantization too, so the variant must survive."""
        (entry,) = parse_endpoints(_payload(_endpoint("deepinfra/fp4", "0.00000008")))
        self.assertEqual(entry.tag, "deepinfra/fp4")
        self.assertEqual(entry.id, "deepinfra/fp4")

    def test_caching_is_derived_from_price_not_the_implicit_flag(self) -> None:
        """OpenRouter reports supports_implicit_caching=false for providers that
        demonstrably do cache (DeepInfra), so a discounted cache-read price is the
        signal used instead."""
        (entry,) = parse_endpoints(_payload(_endpoint(
            "deepinfra/fp4", "0.00000008",
            pricing={"prompt": "0.00000008", "completion": "0.00000018", "input_cache_read": "0.000000016"},
            supports_implicit_caching=False,
        )))
        self.assertIs(entry.caches, True)
        self.assertIn("cached", entry.detail_text())

    def test_no_cache_price_means_no_caching_claim(self) -> None:
        (entry,) = parse_endpoints(_payload(_endpoint("mancer/fp8", "0.000000175")))
        self.assertIs(entry.caches, False)
        self.assertNotIn("cached", entry.detail_text())

    def test_unpriced_endpoint_sorts_last_and_renders_without_price(self) -> None:
        entries = parse_endpoints(_payload(
            {"tag": "mystery", "provider_name": "Mystery"},
            _endpoint("deepinfra/fp4", "0.00000008"),
        ))
        self.assertEqual([entry.tag for entry in entries], ["deepinfra/fp4", "mystery"])
        self.assertEqual(entries[-1].price_text(), "")

    def test_entries_without_a_tag_are_dropped(self) -> None:
        entries = parse_endpoints(_payload({"provider_name": "No Tag"}, _endpoint("deepinfra/fp4", "0.00000008")))
        self.assertEqual([entry.tag for entry in entries], ["deepinfra/fp4"])

    def test_malformed_payloads_raise(self) -> None:
        with self.assertRaises(ValueError):
            parse_endpoints({"data": {}})
        with self.assertRaises(ValueError):
            parse_endpoints({"nope": 1})

    def test_detail_text_summarizes_the_row(self) -> None:
        (entry,) = parse_endpoints(_payload(_endpoint(
            "deepinfra/fp4", "0.00000008", quantization="fp4", uptime_last_30m=97.55,
            pricing={"prompt": "0.00000008", "completion": "0.00000018", "input_cache_read": "0.000000016"},
        )))
        detail = entry.detail_text()
        self.assertIn("$0.080/$0.180 per M", detail)
        self.assertIn("1024k ctx", detail)
        self.assertIn("fp4", detail)
        self.assertIn("98% up", detail)

    def test_defaults_point_at_the_measured_cheapest_caching_endpoint(self) -> None:
        self.assertEqual(DEFAULT_MODEL, "deepseek/deepseek-v4-flash-0731")
        self.assertEqual(DEFAULT_ENDPOINT_TAG, "deepinfra/fp4")
        self.assertEqual(UNPINNED, "any")

    def test_unknown_quantization_is_not_shown(self) -> None:
        (entry,) = parse_endpoints(_payload(_endpoint("digitalocean", "0.00000008", quantization="unknown")))
        self.assertNotIn("unknown", entry.detail_text())

    def test_endpoint_label_falls_back_to_the_tag(self) -> None:
        entry = OpenRouterEndpoint(tag="deepinfra/fp4", provider_name="")
        self.assertEqual(entry.label, "deepinfra/fp4")


if __name__ == "__main__":
    unittest.main()

"""OpenAI catalog: the platform's models, chat ones only (agent-cli's tests, as unittest)."""

from __future__ import annotations

import unittest

from git_tools.providers import openai
from git_tools.providers.catalog import CatalogFetchResult, parse_model_catalog

# Shape of GET /v1/models on the platform: a plain OpenAI list without display
# names, chat models beside ids no chat completion can use.
LIVE_PAYLOAD = {
    "object": "list",
    "data": [
        {"id": "gpt-6.1-sol", "object": "model", "owned_by": "system"},
        {"id": "o3-pro", "object": "model", "owned_by": "system"},
        {"id": "gpt-6-astra", "object": "model", "owned_by": "system"},
        {"id": "gpt-6-astra-realtime", "object": "model", "owned_by": "system"},
        {"id": "gpt-6-astra-audio-preview", "object": "model", "owned_by": "system"},
        {"id": "gpt-4o-mini-tts", "object": "model", "owned_by": "system"},
        {"id": "gpt-4o-transcribe", "object": "model", "owned_by": "system"},
        {"id": "gpt-image-1", "object": "model", "owned_by": "system"},
        {"id": "whisper-1", "object": "model", "owned_by": "openai-internal"},
        {"id": "text-embedding-3-large", "object": "model", "owned_by": "system"},
        {"id": "omni-moderation-latest", "object": "model", "owned_by": "system"},
        {"id": "dall-e-3", "object": "model", "owned_by": "system"},
        {"id": "tts-1", "object": "model", "owned_by": "openai-internal"},
    ],
}
CHAT_IDS = ["gpt-6-astra", "gpt-6.1-sol", "o3-pro"]  # default first, then by label


def _live_result() -> CatalogFetchResult:
    return CatalogFetchResult(entries=parse_model_catalog(LIVE_PAYLOAD), source="live",
                              fetched_at="2026-10-15T00:00:00+00:00")


class OpenAIProviderTests(unittest.TestCase):
    def test_openai_curated_catalog(self) -> None:
        result = openai.catalog()
        self.assertIsNone(result.error)
        self.assertEqual(result.source, "live")
        self.assertEqual(openai.PROVIDER_ID, "openai")
        self.assertEqual(openai.BASE_URL, "https://api.openai.com/v1")
        self.assertEqual([entry.id for entry in result.entries], ["gpt-6-astra", "gpt-6.1-sol"])
        self.assertEqual(result.entries[0].id, openai.DEFAULT_MODEL)

    def test_is_chat_model(self) -> None:
        for model_id, expected in [
            ("gpt-6-astra", True), ("gpt-6.1-sol", True), ("chatgpt-6-latest", True),
            ("o3-pro", True), ("o4-mini", True),
            ("gpt-6-astra-realtime", False), ("gpt-6-astra-audio-preview", False),
            ("gpt-4o-mini-tts", False), ("gpt-4o-transcribe", False), ("gpt-4o-search-preview", False),
            ("gpt-image-1", False), ("gpt-3.5-turbo-instruct", False), ("whisper-1", False),
            ("text-embedding-3-large", False), ("omni-moderation-latest", False),
            ("dall-e-3", False), ("tts-1", False), ("computer-use-preview", False),
        ]:
            with self.subTest(model_id=model_id):
                self.assertIs(openai.is_chat_model(model_id), expected)

    def test_openai_resolve_catalog_keeps_chat_models_verbatim_with_default_first(self) -> None:
        live = _live_result()
        self.assertEqual(len(live.entries), len(LIVE_PAYLOAD["data"]))
        resolved = openai.resolve_catalog(live)
        self.assertEqual(resolved.source, "live")
        self.assertIsNone(resolved.error)
        self.assertEqual(resolved.fetched_at, live.fetched_at)
        self.assertEqual([e.id for e in resolved.entries], CHAT_IDS)
        # Built-in display names overlay matching ids; unknown ids show as-is.
        self.assertEqual(resolved.entries[0].display_name, "GPT-6 Astra")
        self.assertEqual(resolved.entries[1].display_name, "GPT-6.1 Sol")
        self.assertIsNone(resolved.entries[2].display_name)
        self.assertEqual(resolved.entries[2].label, "o3-pro")

        # The default is pinned first even when the platform lists it later.
        shuffled = CatalogFetchResult(entries=tuple(reversed(live.entries)), source="live")
        self.assertEqual([e.id for e in openai.resolve_catalog(shuffled).entries],
                         ["gpt-6-astra", "o3-pro", "gpt-6.1-sol"])

    def test_openai_resolve_catalog_falls_back_to_the_builtin_list(self) -> None:
        for live in (
            CatalogFetchResult(error_kind="network", error="connection refused"),
            CatalogFetchResult(error_kind="auth", error="Incorrect API key provided", status=401),
            CatalogFetchResult(source="live", entries=()),
            CatalogFetchResult(),
        ):
            with self.subTest(live=live):
                resolved = openai.resolve_catalog(live)
                self.assertEqual(resolved.entries, openai.MODELS)
                self.assertEqual(resolved.source, "live")  # not a stale cache: it is the shipped list
                self.assertEqual(resolved.error, live.error)
                self.assertEqual(resolved.error_kind, live.error_kind)
                self.assertEqual(resolved.status, live.status)

    def test_openai_resolve_catalog_falls_back_when_nothing_listed_is_a_chat_model(self) -> None:
        live = CatalogFetchResult(entries=parse_model_catalog({"data": [{"id": "whisper-1"}, {"id": "tts-1"}]}),
                                  source="live")
        resolved = openai.resolve_catalog(live)
        self.assertEqual(resolved.entries, openai.MODELS)
        self.assertIsNone(resolved.error)


if __name__ == "__main__":
    unittest.main()

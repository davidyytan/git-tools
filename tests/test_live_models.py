"""Tests for live model discovery (CLIProxyAPI /models refresh)."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from git_tools.settings import mappings
from git_tools.settings.mappings import (
    PROVIDERS,
    fetch_live_models,
    refresh_live_models,
)


def _fake_urlopen_response(payload) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__.return_value = response
    cm.__exit__.return_value = False
    return cm


class TestFetchLiveModels(unittest.TestCase):
    def test_parses_openai_models_shape_sorted_and_deduped(self) -> None:
        payload = {
            "data": [
                {"id": "gpt-5.6-sol"},
                {"id": "gpt-5.4"},
                {"id": "gpt-5.6-sol"},  # duplicate
                {"id": ""},  # blank id dropped
                "junk",  # non-dict dropped
            ]
        }
        with patch(
            "urllib.request.urlopen", return_value=_fake_urlopen_response(payload)
        ) as urlopen:
            models = fetch_live_models("http://127.0.0.1:8317/v1", "key")

        self.assertEqual(models, ["gpt-5.4", "gpt-5.6-sol"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8317/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer key")

    def test_returns_empty_on_error_bad_shape_or_missing_base_url(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertEqual(fetch_live_models("http://x/v1", "k"), [])
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_urlopen_response({"unexpected": 1}),
        ):
            self.assertEqual(fetch_live_models("http://x/v1", "k"), [])
        self.assertEqual(fetch_live_models("", "k"), [])


class TestRefreshLiveModels(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = copy.deepcopy(PROVIDERS["cliproxyapi"]["models"])
        mappings._LIVE_REFRESHED.discard("cliproxyapi")

    def tearDown(self) -> None:
        PROVIDERS["cliproxyapi"]["models"] = self._saved
        mappings._LIVE_REFRESHED.discard("cliproxyapi")

    def test_non_live_provider_is_noop(self) -> None:
        before = copy.deepcopy(PROVIDERS["openrouter"]["models"])
        self.assertFalse(refresh_live_models("openrouter"))
        self.assertEqual(PROVIDERS["openrouter"]["models"], before)

    def test_failed_fetch_keeps_static_catalogue(self) -> None:
        with patch.object(mappings, "fetch_live_models", return_value=[]):
            self.assertFalse(refresh_live_models("cliproxyapi"))
        self.assertEqual(PROVIDERS["cliproxyapi"]["models"], self._saved)
        # A failed refresh must not memoize; the next call retries the fetch.
        with patch.object(
            mappings, "fetch_live_models", return_value=["gpt-5.6-sol"]
        ) as fetch:
            self.assertTrue(refresh_live_models("cliproxyapi"))
        self.assertEqual(fetch.call_count, 1)

    def test_live_merge_keeps_static_priority_drops_ghosts_adds_new(self) -> None:
        live = ["codex-auto-review", "gpt-5.5", "gpt-5.6-sol", "gpt-image-2"]
        fake_config = SimpleNamespace(base_url="http://x/v1", api_key="k")
        with (
            patch(
                "git_tools.settings.settings.load_provider_config",
                return_value=fake_config,
            ),
            patch.object(mappings, "fetch_live_models", return_value=live) as fetch,
        ):
            self.assertTrue(refresh_live_models("cliproxyapi"))

        models = PROVIDERS["cliproxyapi"]["models"]
        # Static-order priority for entries still served (gpt-5.6-sol stays the
        # default first entry); the gpt-5.4 ghost is dropped; new live ids
        # append after.
        self.assertEqual(
            list(models),
            ["gpt-5.6-sol", "gpt-5.5", "codex-auto-review", "gpt-image-2"],
        )
        # Static metadata preserved; live gpt-5* entries are effort-capable,
        # non-gpt-5 live entries are not.
        self.assertEqual(models["gpt-5.6-sol"]["reasoning_effort"], "xhigh")
        self.assertNotIn("reasoning_effort", models["codex-auto-review"])
        self.assertNotIn("reasoning_effort", models["gpt-image-2"])
        # The fetch used the provider's configured endpoint and key.
        self.assertEqual(fetch.call_args.args, ("http://x/v1", "k"))

    def test_refresh_memoizes_per_process_until_forced(self) -> None:
        with patch.object(
            mappings, "fetch_live_models", return_value=["gpt-5.6-sol"]
        ) as fetch:
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(refresh_live_models("cliproxyapi", force=True))
            self.assertEqual(fetch.call_count, 2)


class TestLiveProviderModelTrust(unittest.TestCase):
    """Live providers trust the configured model as-is (the endpoint's
    catalogue is authoritative, not the static fallback) — a live-only model
    must never be silently displaced by the fallback default."""

    def test_settings_state_keeps_live_only_model(self) -> None:
        from git_tools.cli import _resolve_current_model

        # Not in the static fallback list — only the live endpoint serves it.
        self.assertEqual(
            _resolve_current_model("cliproxyapi", "gpt-5.6-terra"), "gpt-5.6-terra"
        )
        # Unset still falls back to the provider default.
        self.assertEqual(
            _resolve_current_model("cliproxyapi", None), "gpt-5.6-sol"
        )

    def test_generator_default_keeps_live_only_model(self) -> None:
        from git_tools.generators.base import BaseGenerator
        from git_tools.settings import settings as settings_module

        models = PROVIDERS["cliproxyapi"]["models"]
        with patch.object(
            settings_module.settings, "default_model", "gpt-5.6-terra"
        ):
            resolved = BaseGenerator._get_default_model(
                BaseGenerator.__new__(BaseGenerator), models, "cliproxyapi"
            )
        self.assertEqual(resolved, "gpt-5.6-terra")


if __name__ == "__main__":
    unittest.main()

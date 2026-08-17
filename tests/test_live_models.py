"""Tests for provider-wide live model discovery and manual fallbacks."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from git_tools.settings import mappings
from git_tools.settings.mappings import (
    LIVE_MODEL_PROVIDERS,
    PROVIDERS,
    add_user_model,
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
        self.assertEqual(request.get_header("Accept"), "application/json")
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
        self._saved_models = {
            provider: copy.deepcopy(PROVIDERS[provider]["models"])
            for provider in PROVIDERS
        }
        self._saved_fallbacks = copy.deepcopy(mappings._FALLBACK_MODELS)
        self._saved_user_models = copy.deepcopy(mappings._USER_MODELS)
        mappings._LIVE_REFRESHED.clear()
        mappings._LIVE_REFRESH_IDENTITIES.clear()

    def tearDown(self) -> None:
        for provider, models in self._saved_models.items():
            PROVIDERS[provider]["models"] = models
        mappings._FALLBACK_MODELS.clear()
        mappings._FALLBACK_MODELS.update(self._saved_fallbacks)
        mappings._USER_MODELS.clear()
        mappings._USER_MODELS.update(self._saved_user_models)
        mappings._LIVE_REFRESHED.clear()
        mappings._LIVE_REFRESH_IDENTITIES.clear()

    def test_every_registered_provider_supports_dynamic_catalogs(self) -> None:
        self.assertEqual(set(LIVE_MODEL_PROVIDERS), set(PROVIDERS))

        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                fake_config = SimpleNamespace(
                    base_url=f"https://{provider}.example/v1",
                    api_key=f"{provider}-key",
                )
                with (
                    patch(
                        "git_tools.settings.settings.load_provider_config",
                        return_value=fake_config,
                    ),
                    patch.object(
                        mappings,
                        "fetch_live_models",
                        return_value=[f"{provider}-live-model"],
                    ),
                ):
                    self.assertTrue(refresh_live_models(provider, force=True))
                self.assertIn(
                    f"{provider}-live-model", PROVIDERS[provider]["models"]
                )

    def test_unknown_provider_is_noop(self) -> None:
        self.assertFalse(refresh_live_models("unknown"))

    def test_failed_fetch_keeps_static_catalogue(self) -> None:
        before = copy.deepcopy(PROVIDERS["cliproxyapi"]["models"])
        with patch.object(mappings, "fetch_live_models", return_value=[]):
            self.assertFalse(refresh_live_models("cliproxyapi"))
        self.assertEqual(PROVIDERS["cliproxyapi"]["models"], before)
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
            patch.object(mappings, "_load_user_model_map", return_value={}),
        ):
            self.assertTrue(refresh_live_models("cliproxyapi"))

        models = PROVIDERS["cliproxyapi"]["models"]
        # Static-order priority for entries still served (gpt-5.6-sol stays the
        # default first entry); the gpt-5.4 ghost is dropped; new live IDs append.
        self.assertEqual(
            list(models),
            ["gpt-5.6-sol", "gpt-5.5", "codex-auto-review", "gpt-image-2"],
        )
        # Static metadata is preserved; live gpt-5* entries are effort-capable,
        # while unrelated live entries are not.
        self.assertEqual(models["gpt-5.6-sol"]["reasoning_effort"], "xhigh")
        self.assertNotIn("reasoning_effort", models["codex-auto-review"])
        self.assertNotIn("reasoning_effort", models["gpt-image-2"])
        self.assertEqual(fetch.call_args.args, ("http://x/v1", "k"))

    def test_openrouter_live_entries_keep_privacy_default(self) -> None:
        fake_config = SimpleNamespace(
            base_url="https://openrouter.example/v1", api_key="or-key"
        )
        with (
            patch(
                "git_tools.settings.settings.load_provider_config",
                return_value=fake_config,
            ),
            patch.object(
                mappings,
                "fetch_live_models",
                return_value=["vendor/new-model"],
            ),
            patch.object(mappings, "_load_user_model_map", return_value={}),
        ):
            self.assertTrue(refresh_live_models("openrouter"))

        self.assertEqual(
            PROVIDERS["openrouter"]["models"]["vendor/new-model"][
                "data_collection"
            ],
            "deny",
        )

    def test_manual_model_survives_live_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            fake_config = SimpleNamespace(base_url="https://x/v1", api_key="k")
            with (
                patch.object(mappings, "USER_MODELS_PATH", path),
                patch(
                    "git_tools.settings.settings.load_provider_config",
                    return_value=fake_config,
                ),
                patch.object(
                    mappings,
                    "fetch_live_models",
                    return_value=["kimi-live"],
                ),
            ):
                self.assertTrue(add_user_model("kimicode", "kimi-manual"))
                self.assertTrue(refresh_live_models("kimicli", force=True))

            self.assertIn("kimi-manual", PROVIDERS["kimicli"]["models"])
            self.assertIn("kimi-live", PROVIDERS["kimicli"]["models"])
            self.assertEqual(json.loads(path.read_text())["kimicli"], ["kimi-manual"])

    def test_failed_fetch_after_identity_change_drops_old_live_catalog(self) -> None:
        config = SimpleNamespace(base_url="http://x/v1", api_key="k1")
        with (
            patch(
                "git_tools.settings.settings.load_provider_config",
                side_effect=lambda _provider: config,
            ),
            patch.object(
                mappings,
                "fetch_live_models",
                side_effect=[["gpt-5.6-sol", "old-endpoint-only"], []],
            ),
            patch.object(mappings, "_load_user_model_map", return_value={}),
        ):
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertIn(
                "old-endpoint-only", PROVIDERS["cliproxyapi"]["models"]
            )

            config.base_url = "http://new/v1"
            self.assertFalse(refresh_live_models("cliproxyapi"))

        self.assertNotIn("old-endpoint-only", PROVIDERS["cliproxyapi"]["models"])
        self.assertEqual(
            list(PROVIDERS["cliproxyapi"]["models"]),
            ["gpt-5.6-sol", "gpt-5.5", "gpt-5.4"],
        )
        self.assertNotIn("cliproxyapi", mappings._LIVE_REFRESHED)

    def test_refresh_memoizes_by_provider_endpoint_and_api_key(self) -> None:
        config = SimpleNamespace(base_url="http://x/v1", api_key="k1")
        with (
            patch(
                "git_tools.settings.settings.load_provider_config",
                side_effect=lambda _provider: config,
            ),
            patch.object(
                mappings, "fetch_live_models", return_value=["gpt-5.6-sol"]
            ) as fetch,
        ):
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 1)

            config.api_key = "k2"
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 2)

            config.base_url = "http://y/v1"
            self.assertTrue(refresh_live_models("cliproxyapi"))
            self.assertEqual(fetch.call_count, 3)

            self.assertTrue(refresh_live_models("cliproxyapi", force=True))
            self.assertEqual(fetch.call_count, 4)


class TestLiveProviderModelTrust(unittest.TestCase):
    """Dynamic providers trust configured model IDs as endpoint authority."""

    def test_settings_state_keeps_live_only_model_for_each_provider(self) -> None:
        from git_tools.cli import _resolve_current_model

        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(
                    _resolve_current_model(provider, "provider-live-only"),
                    "provider-live-only",
                )

    def test_unset_model_still_uses_provider_fallback_default(self) -> None:
        from git_tools.cli import _resolve_current_model

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

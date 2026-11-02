"""Offline discovery-to-picker/generation regressions; run with isolated HOME/XDG paths before importing git-tools."""

from contextlib import contextmanager
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rich.console import Console

from git_tools import cli
from git_tools.generators.base import BaseGenerator
from git_tools.providers.catalog import CatalogFetchResult, ModelCatalogEntry
from git_tools.providers.kimi_code import KimiCodeModelEntry
from git_tools.settings import mappings
from git_tools.settings import settings as config


LIVE_WITHOUT_CACHE = tuple(provider for provider in mappings.LIVE_MODEL_PROVIDERS if provider != "kimicli")
LIVE = CatalogFetchResult(entries=(ModelCatalogEntry(id="gpt-discovered-only"),), source="live")
EMPTY = CatalogFetchResult(source="live")
NETWORK_FAILURE = CatalogFetchResult(error_kind="network", error="offline fixture")


class NoStaticModelFallbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.saved = self.root / "settings.env"
        self.saved.write_text('GIT_TOOLS_PROVIDER="openai"\nGIT_TOOLS_MODEL_MAIN="saved-manual-id"\nGIT_TOOLS_OPENAI_MODEL_MAIN="saved-manual-id"\nGIT_TOOLS_DEFAULT_MODEL="legacy-manual-id"\n', encoding="utf-8")
        self.original_settings = self.saved.read_bytes()
        self.provider_config = SimpleNamespace(base_url="https://fixture.invalid/v1", api_key="fixture-key")
        for provider in mappings.LIVE_MODEL_PROVIDERS:
            self.addCleanup(mappings.restore_provider_catalog, provider, mappings.snapshot_provider_catalog(provider))
            mappings.PROVIDERS[provider]["models"] = {}
        mappings._LIVE_REFRESHED.clear()
        mappings._LIVE_REFRESH_IDENTITIES.clear()
        mappings._LIVE_REFRESH_ERRORS.clear()
        for patcher in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(mappings, "MODEL_CATALOG_PATH", self.root / "catalog.json"),
            patch.object(config, "DEFAULT_SETTINGS_PATH", self.saved),
            patch.object(config, "_get_env_file_paths", return_value=[self.saved]),
            patch.object(config, "load_provider_config", return_value=self.provider_config),
            patch.object(config.settings, "main_model", "saved-manual-id"),
            patch.object(config.settings, "default_model", "legacy-manual-id"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    @contextmanager
    def fetched(self, provider, result):
        name = {"anthropic": "_fetch_anthropic_models_sync", "kimicli": "_fetch_kimi_code_models_sync"}.get(provider, "_fetch_models_sync")
        with patch.object(mappings, name, return_value=result) as fetch:
            yield fetch

    def assert_saved_model_untouched(self, provider):
        self.assertEqual(self.saved.read_bytes(), self.original_settings)
        self.assertEqual(config.settings.effective_main_model, "saved-manual-id")
        self.assertEqual(config.settings.default_model, "legacy-manual-id")
        self.assertEqual(cli._resolve_current_model(provider, "saved-manual-id"), "saved-manual-id")
        self.assertEqual(BaseGenerator._get_default_model(BaseGenerator.__new__(BaseGenerator), mappings.PROVIDERS[provider]["models"], provider), "saved-manual-id")
        self.assertEqual(os.environ, {})

    def status_text(self, provider, live):
        output = io.StringIO()
        with patch.object(cli, "console", Console(file=output, width=300, color_system=None)):
            cli._print_model_catalog_status(provider, live)
        return output.getvalue()

    def test_initial_definitions_seed_only_curated_catalogs(self):
        for provider in mappings.LIVE_MODEL_PROVIDERS:
            with self.subTest(provider=provider):
                self.assertEqual(mappings._BUILTIN_PROVIDERS[provider]["models"], {})
                self.assertTrue(mappings._BUILTIN_PROVIDERS[provider]["default_model"])
        for provider in ("qwen", "zcode"):
            self.assertTrue(mappings._BUILTIN_PROVIDERS[provider]["models"])

    def test_failures_replace_discovery_with_no_catalog_and_do_not_save_models(self):
        failures = (
            NETWORK_FAILURE,
            CatalogFetchResult(error_kind="auth", error="fixture authentication denied", status=401),
            CatalogFetchResult(error_kind="http", error="fixture unavailable", status=503),
            CatalogFetchResult(error_kind="malformed", error="fixture invalid catalog"),
        )
        with patch.object(config, "save_settings") as save:
            for provider in LIVE_WITHOUT_CACHE:
                for failure in failures:
                    with self.subTest(provider=provider, failure=failure.error_kind):
                        with self.fetched(provider, LIVE):
                            self.assertTrue(mappings.refresh_live_models(provider, force=True))
                        self.assertEqual(list(mappings.PROVIDERS[provider]["models"]), ["gpt-discovered-only"])
                        with self.fetched(provider, failure) as fetch:
                            self.assertFalse(mappings.refresh_live_models(provider, force=True))
                            self.assertFalse(mappings.refresh_live_models(provider))
                        self.assertEqual(fetch.call_count, 2)
                        self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                        error = mappings.get_live_model_refresh_error(provider)
                        self.assertEqual((error.kind, error.message, error.status), (failure.error_kind, failure.error, failure.status))
                        self.assertFalse(error.retained_live_catalog)
                        rows = cli._build_model_choices(provider, current_model="saved-manual-id")
                        self.assertEqual([row.value for row in rows], ["saved-manual-id", cli.ADD_MODEL_SENTINEL])
                        self.assertIn("not in catalog", rows[0].title)
                        self.assert_saved_model_untouched(provider)
            save.assert_not_called()

    def test_configuration_failure_clears_live_entries_without_seeding_or_saving(self):
        for provider in mappings.LIVE_MODEL_PROVIDERS:
            with self.subTest(provider=provider):
                with patch.object(mappings, "resolve_provider_catalog", return_value=LIVE):
                    self.assertTrue(mappings.refresh_live_models(provider, force=True))
                with patch.object(config, "load_provider_config", side_effect=ValueError("private-rejected-credential")), patch.object(mappings, "resolve_provider_catalog") as resolve:
                    self.assertFalse(mappings.refresh_live_models(provider))
                resolve.assert_not_called()
                self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                self.assertNotIn(provider, mappings._LIVE_REFRESHED)
                self.assertNotIn(provider, mappings._LIVE_REFRESH_IDENTITIES)
                error = mappings.get_live_model_refresh_error(provider)
                self.assertEqual(error.kind, "configuration")
                self.assertNotIn("private-rejected-credential", error.message)
                self.assert_saved_model_untouched(provider)

    def test_successful_empty_catalog_replaces_old_entries_clears_errors_and_memoizes(self):
        for provider in LIVE_WITHOUT_CACHE:
            with self.subTest(provider=provider):
                with self.fetched(provider, LIVE):
                    self.assertTrue(mappings.refresh_live_models(provider, force=True))
                with self.fetched(provider, EMPTY) as fetch:
                    self.assertTrue(mappings.refresh_live_models(provider, force=True))
                    self.assertTrue(mappings.refresh_live_models(provider))
                self.assertEqual(fetch.call_count, 1)
                self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                self.assertIsNone(mappings.get_live_model_refresh_error(provider))
                text = self.status_text(provider, True)
                self.assertIn("live discovery succeeded", text)
                self.assertIn("no selectable models", text)
                self.assertIn("manual entry", text)
                self.assertNotIn("failed", text)
                self.assertNotIn("live from the provider", text)
                self.assert_saved_model_untouched(provider)
                with self.fetched(provider, NETWORK_FAILURE):
                    self.assertFalse(mappings.refresh_live_models(provider, force=True))
                with self.fetched(provider, EMPTY) as fetch:
                    self.assertTrue(mappings.refresh_live_models(provider))
                    self.assertTrue(mappings.refresh_live_models(provider))
                self.assertEqual(fetch.call_count, 1)
                self.assertIsNone(mappings.get_live_model_refresh_error(provider))

    def test_openai_filtered_empty_is_successful_empty_not_fallback_or_auth_failure(self):
        nonchat = CatalogFetchResult(entries=(ModelCatalogEntry(id="whisper-1"), ModelCatalogEntry(id="text-embedding-3-large")), source="live", status=200)
        with self.fetched("openai", nonchat) as fetch:
            self.assertTrue(mappings.refresh_live_models("openai", force=True))
            self.assertTrue(mappings.refresh_live_models("openai"))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(mappings.PROVIDERS["openai"]["models"], {})
        self.assertIsNone(mappings.get_live_model_refresh_error("openai"))
        text = self.status_text("openai", True)
        self.assertIn("live discovery succeeded", text)
        self.assertIn("no selectable models", text)
        self.assertNotIn("failed", text)
        self.assert_saved_model_untouched("openai")

    def test_live_source_with_error_metadata_is_not_memoized_as_empty_success(self):
        for result in (CatalogFetchResult(source="live", error="fixture discovery failed"), CatalogFetchResult(source="live", status=503)):
            with self.subTest(error=result.error, status=result.status), self.fetched("openai", result) as fetch:
                self.assertFalse(mappings.refresh_live_models("openai", force=True))
                self.assertFalse(mappings.refresh_live_models("openai"))
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual(mappings.PROVIDERS["openai"]["models"], {})
                self.assertEqual(mappings.get_live_model_refresh_error("openai").status, result.status)
                self.assertNotIn("openai", mappings._LIVE_REFRESHED)

    def test_registry_discards_entries_carried_by_failed_results(self):
        failures = (
            CatalogFetchResult(entries=LIVE.entries, source="live", error_kind="network", error="fixture failure"),
            CatalogFetchResult(entries=LIVE.entries, source="live", error="fixture failure without kind"),
            CatalogFetchResult(entries=LIVE.entries, source="live", status=503),
            CatalogFetchResult(entries=LIVE.entries, source="none", error_kind="auth", error="fixture refusal", status=401),
        )
        for provider in mappings.LIVE_MODEL_PROVIDERS:
            for failure in failures:
                with self.subTest(provider=provider, error=failure.error, status=failure.status), patch.object(mappings, "resolve_provider_catalog", return_value=failure):
                    self.assertFalse(mappings.refresh_live_models(provider, force=True))
                    self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                    self.assertFalse(mappings.get_live_model_refresh_error(provider).retained_live_catalog)
                    self.assert_saved_model_untouched(provider)

    def test_registry_does_not_accept_non_kimi_cached_entries(self):
        cached = CatalogFetchResult(entries=LIVE.entries, source="cache", error_kind="network", error="fixture failure")
        for provider in LIVE_WITHOUT_CACHE:
            with self.subTest(provider=provider), patch.object(mappings, "resolve_provider_catalog", return_value=cached):
                self.assertFalse(mappings.refresh_live_models(provider, force=True))
                self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                self.assertFalse(mappings.get_live_model_refresh_error(provider).retained_live_catalog)
                self.assert_saved_model_untouched(provider)

    def test_empty_success_identity_changes_and_force_trigger_new_discovery(self):
        with self.fetched("openai", EMPTY) as fetch:
            self.assertTrue(mappings.refresh_live_models("openai"))
            self.assertTrue(mappings.refresh_live_models("openai"))
            self.assertEqual(fetch.call_count, 1)
            self.provider_config.api_key = "second-fixture-key"
            self.assertTrue(mappings.refresh_live_models("openai"))
            self.provider_config.base_url = "https://second-fixture.invalid/v1"
            self.assertTrue(mappings.refresh_live_models("openai"))
            self.assertTrue(mappings.refresh_live_models("openai", force=True))
            self.assertEqual(fetch.call_count, 4)
        self.assertEqual(mappings.PROVIDERS["openai"]["models"], {})

    def test_changed_endpoint_or_account_failure_drops_previous_catalog(self):
        for provider in LIVE_WITHOUT_CACHE:
            for attribute, changed in (("api_key", "next-account-key"), ("base_url", "https://next-endpoint.invalid/v1")):
                with self.subTest(provider=provider, attribute=attribute):
                    self.provider_config.base_url = "https://fixture.invalid/v1"
                    self.provider_config.api_key = "fixture-key"
                    with self.fetched(provider, LIVE):
                        self.assertTrue(mappings.refresh_live_models(provider, force=True))
                    setattr(self.provider_config, attribute, changed)
                    with self.fetched(provider, NETWORK_FAILURE):
                        self.assertFalse(mappings.refresh_live_models(provider))
                    self.assertEqual(mappings.PROVIDERS[provider]["models"], {})
                    self.assert_saved_model_untouched(provider)

    def test_empty_success_snapshot_restores_memoized_empty_state(self):
        with self.fetched("openai", EMPTY):
            self.assertTrue(mappings.refresh_live_models("openai"))
        snapshot = mappings.snapshot_provider_catalog("openai")
        with self.fetched("openai", NETWORK_FAILURE):
            self.assertFalse(mappings.refresh_live_models("openai", force=True))
        mappings.restore_provider_catalog("openai", snapshot)
        with self.fetched("openai", LIVE) as fetch:
            self.assertTrue(mappings.refresh_live_models("openai"))
        fetch.assert_not_called()
        self.assertEqual(mappings.PROVIDERS["openai"]["models"], {})
        self.assertIsNone(mappings.get_live_model_refresh_error("openai"))

    def test_genuine_kimi_cache_is_the_only_retained_failure_catalog_and_is_labeled_cached(self):
        live = CatalogFetchResult(entries=(KimiCodeModelEntry(id="account-only-kimi", supports_thinking_type="both"),), source="live")
        with self.fetched("kimicli", live):
            self.assertTrue(mappings.refresh_live_models("kimicli", force=True))
        cached_bytes = mappings.MODEL_CATALOG_PATH.read_bytes()
        with self.fetched("kimicli", NETWORK_FAILURE) as fetch:
            self.assertFalse(mappings.refresh_live_models("kimicli", force=True))
            self.assertFalse(mappings.refresh_live_models("kimicli"))
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(list(mappings.PROVIDERS["kimicli"]["models"]), ["account-only-kimi"])
        self.assertEqual(mappings.MODEL_CATALOG_PATH.read_bytes(), cached_bytes)
        self.assertTrue(mappings.get_live_model_refresh_error("kimicli").retained_live_catalog)
        with patch.object(cli, "warning") as warning:
            cli._print_model_catalog_status("kimicli", False)
        self.assertIn("last successful cached catalog", warning.call_args.args[0])
        self.assertNotIn("no discovered models", warning.call_args.args[0])
        self.provider_config.api_key = "different-account-key"
        with self.fetched("kimicli", NETWORK_FAILURE):
            self.assertFalse(mappings.refresh_live_models("kimicli"))
        self.assertEqual(mappings.PROVIDERS["kimicli"]["models"], {})
        self.assertFalse(mappings.get_live_model_refresh_error("kimicli").retained_live_catalog)
        self.assert_saved_model_untouched("kimicli")

    def test_auth_status_keeps_actual_auth_diagnostic_and_manual_entry(self):
        with self.fetched("openai", CatalogFetchResult(error_kind="auth", error="fixture refusal", status=401)):
            self.assertFalse(mappings.refresh_live_models("openai"))
        with patch.object(cli, "warning") as warning:
            cli._print_model_catalog_status("openai", False)
        text = warning.call_args.args[0]
        self.assertIn("HTTP 401", text)
        self.assertIn("OPENAI_API_KEY", text)
        self.assertIn("no discovered models", text)
        self.assertIn("manual entry", text)
        self.assertNotIn("fallback", text)

    def test_failed_status_offers_manual_entry_without_claiming_static_models(self):
        with self.fetched("openai", NETWORK_FAILURE):
            self.assertFalse(mappings.refresh_live_models("openai"))
        with patch.object(cli, "warning") as warning:
            cli._print_model_catalog_status("openai", False)
        text = warning.call_args.args[0]
        self.assertIn("network", text)
        self.assertIn("no discovered models", text)
        self.assertIn("manual entry", text)
        self.assertNotIn("fallback", text)

    def test_manual_entry_on_empty_or_failed_discovery_does_not_mutate_catalog_or_save(self):
        for result in (EMPTY, NETWORK_FAILURE):
            with self.subTest(source=result.source, error=result.error_kind):
                with self.fetched("openai", result), patch.object(cli, "_ask_model_choice", return_value=cli.ADD_MODEL_SENTINEL), patch.object(cli, "_ask_with_back", return_value=" manual-new-id "), patch.object(cli.questionary, "text"), patch.object(config, "save_settings") as save:
                    selected = cli._choose_provider_model("openai", "saved-manual-id")
                self.assertEqual(selected, "manual-new-id")
                self.assertEqual(mappings.PROVIDERS["openai"]["models"], {})
                save.assert_not_called()
                self.assert_saved_model_untouched("openai")

    def test_noninteractive_generation_reports_empty_success_and_keeps_configured_id(self):
        generator = BaseGenerator(interactive=False)
        with self.fetched("openai", EMPTY), patch.object(generator, "get_provider_config", return_value=self.provider_config), patch.object(cli, "_print_model_catalog_status") as status:
            model, _, _ = generator.select_model_params("openai")
        status.assert_called_once_with("openai", True)
        self.assertEqual(model, "saved-manual-id")
        self.assert_saved_model_untouched("openai")

    def test_empty_generation_keeps_cli_id_or_single_provider_default(self):
        with patch.object(config.settings, "main_model", None), patch.object(config.settings, "default_model", None):
            for provider in LIVE_WITHOUT_CACHE:
                for override in (None, "explicit-cli-id"):
                    with self.subTest(provider=provider, override=override):
                        generator = BaseGenerator(model=override, interactive=False)
                        with self.fetched(provider, EMPTY), patch.object(generator, "get_provider_config", return_value=self.provider_config), patch.object(cli, "_print_model_catalog_status"), patch.object(generator.logger, "warning") as warning:
                            model, _, _ = generator.select_model_params(provider)
                        self.assertEqual(warning.call_count, int(override is not None))
                        self.assertEqual(model, override or mappings.PROVIDERS[provider]["default_model"])
                        self.assertEqual(mappings.PROVIDERS[provider]["models"], {})


if __name__ == "__main__":
    unittest.main()

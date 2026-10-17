"""Settings editors keep provider-scoped knobs consistent with the chosen model.

OpenRouter upstream availability and Kimi effort tiers are per model, so a
model change or a direct value must be checked against the model actually
selected, not against whatever an earlier model allowed.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import typer

from git_tools.cli import _ask_model_choice, _edit_effort, _edit_kimi_thinking, _edit_model
from git_tools.settings import mappings
from git_tools.settings import settings as settings_module

_OLD_MODEL = "anthropic/claude-sonnet-4.6"
_NEW_MODEL = "vendor/model"


def _endpoints(*tags: str):
    from git_tools.providers.openrouter import OpenRouterEndpoint

    return [OpenRouterEndpoint(tag=tag, provider_name=tag.split("/")[0].title()) for tag in tags]


def _openrouter_state(pin: str | None = "old-upstream") -> dict:
    return {"provider": "openrouter", "model": _OLD_MODEL,
            "openrouter_provider": pin, "api_configured": True}


class ModelChangeOpenRouterPinTests(unittest.TestCase):
    """Changing the main model never silently reuses a pin chosen for another model."""

    def setUp(self) -> None:
        for target in ("git_tools.cli.console",):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_direct_change_clears_pin_the_new_model_is_not_served_by(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._list_openrouter_upstreams", return_value=["new-upstream"]) as listed,
              patch.object(settings_module, "save_settings") as save,
              patch("git_tools.cli.warning") as warn):
            _edit_model(state, _NEW_MODEL)

        listed.assert_called_once_with(_NEW_MODEL)
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL,
                                      "GIT_TOOLS_OPENROUTER_PROVIDER": ""})
        self.assertEqual(state["model"], _NEW_MODEL)
        self.assertIsNone(state["openrouter_provider"])
        self.assertIn(f"old-upstream does not serve {_NEW_MODEL}", warn.call_args.args[0])

    def test_direct_change_keeps_pin_that_serves_the_new_model(self) -> None:
        state = _openrouter_state(pin="deepinfra")
        with (patch("git_tools.cli._list_openrouter_upstreams", return_value=["deepinfra/fp4", "novita"]),
              patch.object(settings_module, "save_settings") as save,
              patch("git_tools.cli.warning") as warn):
            _edit_model(state, _NEW_MODEL)

        # A bare provider pin still matches a quantization-variant tag.
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL})
        self.assertEqual(state["openrouter_provider"], "deepinfra")
        warn.assert_not_called()

    def test_direct_change_keeps_unverifiable_pin_with_warning(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._list_openrouter_upstreams", return_value=[]),
              patch.object(settings_module, "save_settings") as save,
              patch("git_tools.cli.warning") as warn):
            _edit_model(state, _NEW_MODEL)

        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL})
        self.assertEqual(state["openrouter_provider"], "old-upstream")
        self.assertIn("Could not verify", warn.call_args.args[0])

    def test_direct_change_to_same_model_does_not_touch_pin(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._list_openrouter_upstreams") as listed,
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state, _OLD_MODEL)

        listed.assert_not_called()
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _OLD_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _OLD_MODEL})
        self.assertEqual(state["openrouter_provider"], "old-upstream")

    def test_direct_change_without_pin_skips_the_lookup(self) -> None:
        state = _openrouter_state(pin=None)
        with (patch("git_tools.cli._list_openrouter_upstreams") as listed,
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state, _NEW_MODEL)

        listed.assert_not_called()
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL})
        self.assertIsNone(state["openrouter_provider"])

    def test_interactive_change_reasks_upstream_for_the_new_model_and_saves_both(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._choose_provider_model", return_value=_NEW_MODEL),
              patch("git_tools.cli._list_openrouter_endpoints", return_value=_endpoints("new-upstream")),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="new-upstream"),
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state)

        self.assertIn(_NEW_MODEL, select.call_args.args[0])
        offered = [choice.value for choice in select.call_args.kwargs["choices"]]
        self.assertIn("new-upstream", offered)
        # A pin the live list says does not serve the model is not offered.
        self.assertNotIn("old-upstream", offered)
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL,
                                      "GIT_TOOLS_OPENROUTER_PROVIDER": "new-upstream"})
        self.assertEqual(state["model"], _NEW_MODEL)
        self.assertEqual(state["openrouter_provider"], "new-upstream")

    def test_interactive_change_defaults_to_the_current_pin_when_still_served(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._choose_provider_model", return_value=_NEW_MODEL),
              patch("git_tools.cli._list_openrouter_endpoints", return_value=_endpoints("other", "old-upstream")),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="old-upstream"),
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state)

        self.assertEqual(select.call_args.kwargs["default"], "old-upstream")
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL})
        self.assertEqual(state["openrouter_provider"], "old-upstream")

    def test_interactive_change_cancelled_at_upstream_saves_nothing(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._choose_provider_model", return_value=_NEW_MODEL),
              patch("git_tools.cli._list_openrouter_endpoints", return_value=_endpoints("new-upstream")),
              patch("git_tools.cli.questionary.select"),
              patch("git_tools.cli._ask_with_back", return_value=None),
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state)

        save.assert_not_called()
        self.assertEqual(state["model"], _OLD_MODEL)
        self.assertEqual(state["openrouter_provider"], "old-upstream")

    def test_interactive_change_offers_current_pin_when_the_list_is_unavailable(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._choose_provider_model", return_value=_NEW_MODEL),
              patch("git_tools.cli._list_openrouter_endpoints", return_value=_endpoints()),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="old-upstream"),
              patch("git_tools.cli.warning") as warn,
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state)

        self.assertIn("Could not list OpenRouter upstreams", warn.call_args.args[0])
        offered = [choice.value for choice in select.call_args.kwargs["choices"]]
        self.assertEqual(offered[0], "old-upstream")
        self.assertEqual(select.call_args.kwargs["default"], "old-upstream")
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL})
        self.assertEqual(state["openrouter_provider"], "old-upstream")

    def test_interactive_unpinned_choice_clears_the_old_pin(self) -> None:
        state = _openrouter_state()
        with (patch("git_tools.cli._choose_provider_model", return_value=_NEW_MODEL),
              patch("git_tools.cli._list_openrouter_endpoints", return_value=_endpoints("new-upstream")),
              patch("git_tools.cli.questionary.select"),
              patch("git_tools.cli._ask_with_back", return_value="any"),
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state)

        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": _NEW_MODEL,
                                      "GIT_TOOLS_MODEL_MAIN": _NEW_MODEL,
                                      "GIT_TOOLS_OPENROUTER_PROVIDER": ""})
        self.assertIsNone(state["openrouter_provider"])

    def test_other_providers_never_touch_routing(self) -> None:
        state = {"provider": "kimicli", "model": "kimi-k2.5",
                 "openrouter_provider": None, "api_configured": True}
        with (patch("git_tools.cli._list_openrouter_upstreams") as listed,
              patch.object(settings_module, "save_settings") as save):
            _edit_model(state, "kimi-for-coding")

        listed.assert_not_called()
        save.assert_called_once_with({"GIT_TOOLS_DEFAULT_MODEL": "kimi-for-coding",
                                      "GIT_TOOLS_MODEL_MAIN": "kimi-for-coding"})


class ModelPickerTests(unittest.TestCase):
    """Large catalogs keep the arrow-key list and add type-to-filter.

    The previous free-text autocomplete pre-typed the current model's title, so
    nothing else matched until the whole line was erased and Enter re-saved the
    current model: in practice the main model could not be changed.
    """

    def test_large_catalog_is_a_filterable_list_with_current_model_preselected(self) -> None:
        models = {f"model-{i}": {"model_name": f"model-{i}"} for i in range(30)}
        with (patch.dict(mappings.PROVIDERS["openai"], {"models": models}),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="model-7")):
            chosen = _ask_model_choice("openai", current_model="model-3", default_model="model-3")

        self.assertEqual(chosen, "model-7")
        kwargs = select.call_args.kwargs
        self.assertTrue(kwargs["use_search_filter"])
        self.assertFalse(kwargs["use_jk_keys"])
        self.assertEqual(kwargs["default"], "model-3")
        self.assertEqual(kwargs["choices"][0].value, "model-3")
        self.assertIn("filter", kwargs["instruction"])

    def test_searchable_list_titles_can_all_be_filtered(self) -> None:
        # questionary's filter is `search.lower() in choice.title.lower()` over
        # every row, so a styled (list) title anywhere crashes the first keystroke.
        models = {f"model-{i}": {"model_name": f"model-{i}"} for i in range(30)}
        models["gpt-6.1-sol"] = {"model_name": "gpt-6.1-sol", "display_name": "GPT-6.1 Sol"}
        with (patch.dict(mappings.PROVIDERS["openai"], {"models": models}),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="model-7")):
            _ask_model_choice("openai", current_model="model-3", default_model="model-3")

        choices = select.call_args.kwargs["choices"]
        self.assertTrue(all(isinstance(choice.title, str) for choice in choices))
        hits = [choice.value for choice in choices if "sol" in choice.title.lower()]
        self.assertEqual(hits, ["gpt-6.1-sol"])
        self.assertEqual(choices[-1].title, "← Back")

    def test_small_catalog_keeps_the_plain_list(self) -> None:
        models = {"gpt-6-astra": {"model_name": "gpt-6-astra"}, "gpt-6.1-sol": {"model_name": "gpt-6.1-sol"}}
        with (patch.dict(mappings.PROVIDERS["openai"], {"models": models}),
              patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value="gpt-6.1-sol")):
            chosen = _ask_model_choice("openai", current_model="gpt-6-astra", default_model="gpt-6-astra")

        self.assertEqual(chosen, "gpt-6.1-sol")
        self.assertFalse(select.call_args.kwargs["use_search_filter"])
        self.assertEqual(select.call_args.kwargs["default"], "gpt-6-astra")

    def test_escape_backs_out_without_a_choice(self) -> None:
        with (patch("git_tools.cli.questionary.select"),
              patch("git_tools.cli._ask_with_back", return_value=None)):
            self.assertIsNone(_ask_model_choice("openai", current_model="gpt-6-astra", default_model="gpt-6-astra"))


class StyledMenuTests(unittest.TestCase):
    """Rows carry colour per part but still read as the same text."""

    def test_effort_rows_mark_the_configured_tier(self) -> None:
        from git_tools.cli import _build_effort_choices
        from git_tools.generators.base import plain_title

        rows = {choice.value: plain_title(choice.title)
                for choice in _build_effort_choices("openai", "gpt-6-astra", "high")}
        self.assertEqual(rows["high"], "high (current)")
        self.assertEqual(rows["low"], "low")
        self.assertEqual(rows[""], "Unset")

    def test_openai_effort_row_only_for_reasoning_models(self) -> None:
        from git_tools.cli import _build_settings_choices

        base = {"provider": "openai", "api_configured": True, "support_model": "follow-main",
                "temperature": 0.6, "max_tokens": 32000, "max_retries": 1, "reasoning_effort": None}
        values = lambda model: [c.value for c in _build_settings_choices({**base, "model": model})]
        self.assertIn("effort", values("gpt-6-astra"))
        self.assertNotIn("effort", values("gpt-4.1"))

    def test_settings_rows_show_routing_and_thinking_values(self) -> None:
        from git_tools.cli import _build_settings_choices
        from git_tools.generators.base import plain_title

        base = {"api_configured": False, "support_model": "follow-main", "temperature": 0.6,
                "max_tokens": 32000, "max_retries": 1, "reasoning_effort": None}
        rows = {c.value: plain_title(c.title) for c in _build_settings_choices(
            {**base, "provider": "openrouter", "model": "vendor/model", "openrouter_provider": "deepinfra"})}
        self.assertEqual(rows["openrouter-provider"], "OpenRouter upstream routing: deepinfra")
        self.assertEqual(rows["api-key"], "API Key (openrouter): not set")
        for stored, shown in ((None, "default"), (True, "on"), (False, "off"), ("odd", "default")):
            rows = {c.value: plain_title(c.title) for c in _build_settings_choices(
                {**base, "provider": "kimicli", "model": "kimi-k2.5", "kimi_thinking": stored})}
            self.assertEqual(rows["kimi-thinking"], f"Kimi thinking: {shown}")


class CommitFormatEditorTests(unittest.TestCase):
    def test_group_choices_use_existing_direct_editor_keys(self) -> None:
        from git_tools.cli import _BACK, _SETTINGS_EDITORS, _build_commit_format_choices
        from git_tools.generators.base import plain_title

        rows = _build_commit_format_choices({"commit_include_scope": True, "commit_include_body": False,
                                              "commit_body_style": "prose", "commit_include_footer": True})
        self.assertEqual([row.value for row in rows],
                         ["commit-scope", "commit-body", "commit-body-style", "commit-footer", _BACK])
        self.assertEqual([plain_title(row.title) for row in rows],
                         ["Scope: on", "Description (body): off", "Description style: Prose", "Footer: on", "← Back"])
        for row in rows[:-1]:
            self.assertIn(row.value, _SETTINGS_EDITORS)

    def test_style_editor_only_saves_accepted_enum(self) -> None:
        from git_tools.cli import _edit_commit_body_style

        state = {"commit_body_style": "bullets"}
        with patch.object(settings_module, "save_setting") as save, patch("git_tools.cli.console"):
            _edit_commit_body_style(state, "prose")
        save.assert_called_once_with("GIT_TOOLS_COMMIT_BODY_STYLE", "prose")
        self.assertEqual(state["commit_body_style"], "prose")
        with patch.object(settings_module, "save_setting") as save:
            with self.assertRaises(typer.Exit):
                _edit_commit_body_style(state, "invalid")
        save.assert_not_called()
        self.assertEqual(state["commit_body_style"], "prose")


class DirectEffortCatalogTests(unittest.TestCase):
    """`git-tools settings effort <value>` accepts exactly what the picker offers."""

    def setUp(self) -> None:
        tiered = {"model_name": "kimi-tiered", "supports_thinking_type": "both",
                  "think_efforts": {"support": True, "valid_efforts": ["low", "high"]}}
        patcher = patch.dict(mappings.PROVIDERS["kimicli"]["models"], {"kimi-tiered": tiered})
        patcher.start()
        self.addCleanup(patcher.stop)
        # The catalog is injected directly here; the live-refresh path has its
        # own test below, so the refresh is stubbed to keep the injection intact.
        for target in ("git_tools.cli.console", "git_tools.cli.refresh_live_models"):
            stub = patch(target)
            stub.start()
            self.addCleanup(stub.stop)
        self.state = {"provider": "kimicli", "model": "kimi-tiered",
                      "reasoning_effort": "low", "api_configured": True}

    def test_rejects_an_effort_outside_the_model_catalog(self) -> None:
        with (patch.object(settings_module, "save_setting") as save,
              patch("git_tools.cli.error") as err):
            with self.assertRaises(typer.Exit):
                _edit_effort(self.state, "xhigh")

        save.assert_not_called()
        self.assertEqual(self.state["reasoning_effort"], "low")
        self.assertIn("kimi-tiered", err.call_args.args[0])
        self.assertIn("low, high", err.call_args.args[0])

    def test_accepts_an_effort_the_model_catalog_declares(self) -> None:
        with patch.object(settings_module, "save_setting") as save:
            _edit_effort(self.state, "High")

        save.assert_called_once_with("GIT_TOOLS_REASONING_EFFORT", "high")
        self.assertEqual(self.state["reasoning_effort"], "high")

    def test_interactive_editor_survives_a_saved_tier_the_catalog_dropped(self) -> None:
        # Kimi's catalog declares low/high here; a saved "medium" must not make
        # questionary reject the default. The real select is constructed.
        self.state["reasoning_effort"] = "medium"
        with (patch.object(settings_module, "save_setting") as save,
              patch("git_tools.cli._ask_with_back", return_value="") as ask,
              patch("git_tools.cli.warning") as warn):
            _edit_effort(self.state)

        self.assertIn("medium", warn.call_args.args[0])
        question = ask.call_args.args[0]
        self.assertTrue(hasattr(question, "application"))
        save.assert_called_once_with("GIT_TOOLS_REASONING_EFFORT", "")
        self.assertIsNone(self.state["reasoning_effort"])

    def test_unset_is_always_accepted(self) -> None:
        with patch.object(settings_module, "save_setting") as save:
            _edit_effort(self.state, "unset")

        save.assert_called_once_with("GIT_TOOLS_REASONING_EFFORT", "")
        self.assertIsNone(self.state["reasoning_effort"])

    def test_global_ladder_applies_when_the_catalog_declares_nothing(self) -> None:
        state = {"provider": "kimicli", "model": "kimi-k2.5",
                 "reasoning_effort": None, "api_configured": True}
        with patch.object(settings_module, "save_setting") as save:
            _edit_effort(state, "xhigh")

        save.assert_called_once_with("GIT_TOOLS_REASONING_EFFORT", "xhigh")

    def test_global_ladder_still_rejects_unknown_values(self) -> None:
        state = {"provider": "openrouter", "model": "vendor/model",
                 "reasoning_effort": None, "api_configured": True}
        with (patch.object(settings_module, "save_setting") as save,
              patch("git_tools.cli.error")):
            with self.assertRaises(typer.Exit):
                _edit_effort(state, "ultra")

        save.assert_not_called()
        self.assertIsNone(state["reasoning_effort"])


class DirectEffortLiveCatalogTests(unittest.TestCase):
    """The direct setter loads Kimi's live catalog itself, as the CLI path does.

    `git-tools settings effort <value>` never opens the model picker, so the
    account-aware efforts would otherwise never be fetched and the built-in
    entries (which declare none) would let any tier through.
    """

    def test_direct_effort_is_checked_against_the_freshly_fetched_catalog(self) -> None:
        provider = "kimicli"
        snapshot = mappings.snapshot_provider_catalog(provider)
        self.addCleanup(mappings.restore_provider_catalog, provider, snapshot)
        mappings._LIVE_REFRESHED.discard(provider)
        from git_tools.providers.catalog import CatalogFetchResult
        from git_tools.providers.kimi_code import parse_kimi_code_catalog

        live = CatalogFetchResult(entries=parse_kimi_code_catalog({"data": [
            {"id": "kimi-k2.5", "supports_thinking_type": "both",
             "think_efforts": {"support": True, "valid_efforts": ["low", "high"]}}]}), source="live")
        state = {"provider": provider, "model": "kimi-k2.5", "reasoning_effort": None, "api_configured": True}
        config = SimpleNamespace(api_key="live-test", base_url="https://live-test.invalid/v1")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp) / "catalog.json"),
            patch("git_tools.settings.settings.load_provider_config", return_value=config),
            patch.object(mappings, "_fetch_kimi_code_models_sync", return_value=live) as fetch,
            patch.object(settings_module, "save_setting") as save,
            patch("git_tools.cli.console"),
            patch("git_tools.cli.error") as err,
        ):
            with self.assertRaises(typer.Exit):
                _edit_effort(state, "xhigh")
            fetch.assert_called_once()
            _edit_effort(state, "high")

        self.assertIn("low, high", err.call_args.args[0])
        save.assert_called_once_with("GIT_TOOLS_REASONING_EFFORT", "high")
        self.assertEqual(state["reasoning_effort"], "high")


if __name__ == "__main__":
    unittest.main()


class KimiThinkingEditorTests(unittest.TestCase):
    """Turning Kimi thinking off never leaves a tier behind (agent-cli picks both together)."""

    def setUp(self) -> None:
        tiered = {"model_name": "kimi-tiered", "supports_thinking_type": "both",
                  "think_efforts": {"support": True, "valid_efforts": ["low", "high"]}}
        patcher = patch.dict(mappings.PROVIDERS["kimicli"]["models"], {"kimi-tiered": tiered})
        patcher.start()
        self.addCleanup(patcher.stop)
        for target in ("git_tools.cli.console", "git_tools.cli.refresh_live_models"):
            stub = patch(target)
            stub.start()
            self.addCleanup(stub.stop)
        self.state = {"provider": "kimicli", "model": "kimi-tiered", "reasoning_effort": "high",
                      "kimi_thinking": None, "api_configured": True}

    def test_disabling_clears_the_effort_override_in_one_save(self) -> None:
        with (patch.object(settings_module, "save_settings") as save_all,
              patch.object(settings_module, "save_setting") as save_one):
            _edit_kimi_thinking(self.state, "disabled")

        save_all.assert_called_once_with({"GIT_TOOLS_KIMI_THINKING": "false",
                                          "GIT_TOOLS_REASONING_EFFORT": ""})
        save_one.assert_not_called()
        self.assertIsNone(self.state["reasoning_effort"])
        self.assertIs(self.state["kimi_thinking"], False)

    def test_disabling_without_an_override_saves_only_the_flag(self) -> None:
        self.state["reasoning_effort"] = None
        with (patch.object(settings_module, "save_settings") as save_all,
              patch.object(settings_module, "save_setting") as save_one):
            _edit_kimi_thinking(self.state, "disabled")

        save_one.assert_called_once_with("GIT_TOOLS_KIMI_THINKING", "false")
        save_all.assert_not_called()

    def test_enabling_warns_when_the_saved_tier_is_not_declared(self) -> None:
        self.state["reasoning_effort"] = "xhigh"
        with (patch.object(settings_module, "save_setting") as save,
              patch("git_tools.cli.warning") as warn):
            _edit_kimi_thinking(self.state, "enabled")

        save.assert_called_once_with("GIT_TOOLS_KIMI_THINKING", "true")
        self.assertEqual(self.state["reasoning_effort"], "xhigh")
        self.assertIn("xhigh", warn.call_args.args[0])
        self.assertIn("low, high", warn.call_args.args[0])

    def test_enabling_with_a_declared_tier_is_silent(self) -> None:
        with (patch.object(settings_module, "save_setting"),
              patch("git_tools.cli.warning") as warn):
            _edit_kimi_thinking(self.state, "enabled")

        warn.assert_not_called()
        self.assertEqual(self.state["reasoning_effort"], "high")


class ProviderProfileTests(unittest.TestCase):
    """Every provider keeps its own profile; a switch back restores it (agent-cli)."""

    def setUp(self) -> None:
        import os
        from typer.testing import CliRunner

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.env"
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("GIT_TOOLS_") and not key.endswith(("_BASE_URL", "_API_KEY"))}
        # The settings classes bind their env-file list at import time, so the
        # temp file must be bound into them too; otherwise the state loader
        # keeps reading the real ~/.git-tools/settings.env.
        bound = [settings_module.GitToolsSettings] + [
            getattr(settings_module, name) for name in settings_module.ALLOWED_CONFIG_CLASSES]
        for patcher in (
            patch.dict("os.environ", values=env, clear=True),
            patch.object(settings_module, "DEFAULT_SETTINGS_PATH", self.path),
            patch("git_tools.cli.refresh_live_models", return_value=False),
            patch("git_tools.cli._print_model_catalog_status"),
            *[patch.dict(cls.model_config, {"env_file": self.path}) for cls in bound],
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.runner = CliRunner()

    def run_settings(self, *args: str) -> str:
        from git_tools.cli import app

        result = self.runner.invoke(app, ["settings", *args])
        self.assertEqual(result.exit_code, 0, result.output)
        return self.path.read_text()

    def test_each_provider_keeps_its_profile_across_switches(self) -> None:
        content = self.run_settings("provider", "openai")
        self.assertIn('GIT_TOOLS_API_BASE="https://api.openai.com/v1"', content)
        self.assertNotIn("OPENAI_BASE_URL", content)  # the default is not remembered

        self.run_settings("main-model", "my-openai-model")
        self.run_settings("effort", "xhigh")
        content = self.run_settings("api-base", "https://custom.invalid/v1")
        self.assertIn('GIT_TOOLS_OPENAI_MODEL_MAIN="my-openai-model"', content)
        self.assertIn('GIT_TOOLS_OPENAI_REASONING_EFFORT="xhigh"', content)
        self.assertIn('OPENAI_BASE_URL="https://custom.invalid/v1"', content)

        content = self.run_settings("provider", "cliproxyapi")
        self.assertIn('GIT_TOOLS_MODEL_MAIN="gpt-6-astra"', content)  # a clean slate: the provider default
        self.assertIn('GIT_TOOLS_REASONING_EFFORT=""', content)
        self.assertIn('GIT_TOOLS_API_BASE="http://127.0.0.1:8317/v1"', content)
        self.assertIn('GIT_TOOLS_OPENAI_MODEL_MAIN="my-openai-model"', content)  # untouched
        content = self.run_settings("effort", "low")
        self.assertIn('GIT_TOOLS_CLIPROXYAPI_REASONING_EFFORT="low"', content)

        content = self.run_settings("provider", "openai")
        self.assertIn('GIT_TOOLS_PROVIDER="openai"', content)
        self.assertIn('GIT_TOOLS_MODEL_MAIN="my-openai-model"', content)
        self.assertIn('GIT_TOOLS_REASONING_EFFORT="xhigh"', content)
        self.assertIn('GIT_TOOLS_API_BASE="https://custom.invalid/v1"', content)

        content = self.run_settings("api-base", "https://api.openai.com/v1")
        self.assertNotIn("OPENAI_BASE_URL", content)  # back to the default: forgotten

        content = self.run_settings("provider", "cliproxyapi")
        self.assertIn('GIT_TOOLS_MODEL_MAIN="gpt-6-astra"', content)
        self.assertIn('GIT_TOOLS_REASONING_EFFORT="low"', content)
        self.assertIn('GIT_TOOLS_API_BASE="http://127.0.0.1:8317/v1"', content)

    def test_profile_keys_mirroring_and_removal(self) -> None:
        from git_tools.settings.settings import (
            _mirror_profile,
            _render_settings_updates,
            provider_base_url_env,
            provider_profile_key,
            saved_provider_profile,
        )

        self.assertEqual(provider_base_url_env("openai"), "OPENAI_BASE_URL")
        self.assertEqual(provider_base_url_env("kimicode"), "KIMICLI_BASE_URL")
        self.assertEqual(provider_profile_key("kimi", "MODEL_MAIN"), "GIT_TOOLS_KIMICLI_MODEL_MAIN")
        self.assertEqual(_render_settings_updates('A="1"\nOPENAI_BASE_URL="x"\nB="2"\n', {"OPENAI_BASE_URL": None}),
                         'A="1"\nB="2"\n')
        # The provider being switched to owns the mirrors.
        self.assertEqual(_mirror_profile({"GIT_TOOLS_PROVIDER": "anthropic", "GIT_TOOLS_MODEL_MAIN": "m",
                                          "GIT_TOOLS_API_BASE": "https://api.anthropic.com/v1"}), {
            "GIT_TOOLS_PROVIDER": "anthropic", "GIT_TOOLS_MODEL_MAIN": "m",
            "GIT_TOOLS_API_BASE": "https://api.anthropic.com/v1",
            "GIT_TOOLS_ANTHROPIC_MODEL_MAIN": "m", "ANTHROPIC_BASE_URL": None,
        })
        # Otherwise the saved current provider does.
        self.path.write_text('GIT_TOOLS_PROVIDER="qwen"\nGIT_TOOLS_QWEN_REASONING_EFFORT="high"\n')
        self.assertEqual(_mirror_profile({"GIT_TOOLS_API_BASE": "https://plan.invalid/v1"}),
                         {"GIT_TOOLS_API_BASE": "https://plan.invalid/v1", "QWEN_BASE_URL": "https://plan.invalid/v1"})
        self.assertEqual(saved_provider_profile("qwen")["reasoning_effort"], "high")
        self.assertIsNone(saved_provider_profile("qwen")["model"])
        with patch.dict("os.environ", {"GIT_TOOLS_QWEN_REASONING_EFFORT": "low"}):
            self.assertEqual(saved_provider_profile("qwen")["reasoning_effort"], "low")


class CombinedKimiPickerTests(unittest.TestCase):
    """Thinking and tier are one choice, built from the catalog entry (agent-cli's picker)."""

    def setUp(self) -> None:
        models = {
            "tiered": {"model_name": "tiered", "supports_thinking_type": "both", "supports_reasoning": True,
                       "think_efforts": {"support": True, "valid_efforts": ["low", "high", "max"],
                                         "default_effort": "high"}},
            "always": {"model_name": "always", "supports_thinking_type": "only"},
            "never": {"model_name": "never", "supports_thinking_type": "no"},
        }
        patcher = patch.dict(mappings.PROVIDERS["kimicli"]["models"], models)
        patcher.start()
        self.addCleanup(patcher.stop)
        for target in ("git_tools.cli.console", "git_tools.cli.refresh_live_models"):
            stub = patch(target)
            stub.start()
            self.addCleanup(stub.stop)

    def test_the_catalog_decides_without_asking_where_it_can(self) -> None:
        from git_tools.cli import _pick_kimi_thinking
        from git_tools.generators.base import plain_title

        with patch("git_tools.cli._ask_with_back") as ask:
            self.assertEqual(_pick_kimi_thinking("kimicli", "never", None, "high"), (False, None))
            # An incomplete record is not guessed from; the same model keeps its choice.
            self.assertEqual(_pick_kimi_thinking("kimicli", "unknown", None, None), (None, None))
            self.assertEqual(_pick_kimi_thinking("kimicli", "unknown", True, "low", keep_current=True), (True, "low"))
        ask.assert_not_called()
        # A thinking-only model without tiers still offers its one row, as agent-cli does.
        with (patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value=0)):
            self.assertEqual(_pick_kimi_thinking("kimicli", "always", None, None), (True, None))
        self.assertEqual([plain_title(c.title) for c in select.call_args.kwargs["choices"][:-1]], ["on"])

    def test_one_list_of_off_and_tiers_with_agent_clis_default(self) -> None:
        from git_tools.cli import _pick_kimi_thinking
        from git_tools.generators.base import plain_title

        with (patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value=1)):
            self.assertEqual(_pick_kimi_thinking("kimicli", "tiered", None, None), (True, "low"))
        rows = [plain_title(choice.title) for choice in select.call_args.kwargs["choices"][:-1]]
        self.assertEqual(rows, ["off", "low", "high", "max"])  # nothing current: no marker
        self.assertEqual(select.call_args.kwargs["default"].value, 2)  # the model's default tier, high

        with (patch("git_tools.cli.questionary.select") as select,
              patch("git_tools.cli._ask_with_back", return_value=0)):
            self.assertEqual(_pick_kimi_thinking("kimicli", "tiered", True, "max"), (False, None))
        rows = [plain_title(choice.title) for choice in select.call_args.kwargs["choices"][:-1]]
        self.assertEqual(rows[3], "max (current)")

        with patch("git_tools.cli._ask_with_back", return_value=None):
            self.assertIsNone(_pick_kimi_thinking("kimicli", "tiered", None, None))

    def test_interactive_editor_saves_both_keys_from_one_choice(self) -> None:
        state = {"provider": "kimicli", "model": "tiered", "reasoning_effort": None,
                 "kimi_thinking": None, "api_configured": True}
        with (patch("git_tools.cli._pick_kimi_thinking", return_value=(True, "max")),
              patch.object(settings_module, "save_settings") as save):
            _edit_kimi_thinking(state)
        save.assert_called_once_with({"GIT_TOOLS_KIMI_THINKING": "true", "GIT_TOOLS_REASONING_EFFORT": "max"})
        self.assertEqual((state["kimi_thinking"], state["reasoning_effort"]), (True, "max"))

        with (patch("git_tools.cli._pick_kimi_thinking", return_value=(False, None)),
              patch.object(settings_module, "save_settings") as save):
            _edit_kimi_thinking(state)
        save.assert_called_once_with({"GIT_TOOLS_KIMI_THINKING": "false", "GIT_TOOLS_REASONING_EFFORT": ""})

    def test_direct_value_accepts_a_tier(self) -> None:
        state = {"provider": "kimicli", "model": "tiered", "reasoning_effort": None,
                 "kimi_thinking": False, "api_configured": True}
        with patch.object(settings_module, "save_settings") as save:
            _edit_kimi_thinking(state, "high")
        save.assert_called_once_with({"GIT_TOOLS_KIMI_THINKING": "true", "GIT_TOOLS_REASONING_EFFORT": "high"})
        self.assertEqual((state["kimi_thinking"], state["reasoning_effort"]), (True, "high"))


class UpstreamRowTests(unittest.TestCase):
    def test_rows_carry_agent_clis_details(self) -> None:
        from git_tools.cli import _upstream_choice
        from git_tools.generators.base import plain_title
        from git_tools.providers.openrouter import parse_endpoints

        (entry,) = parse_endpoints({"data": {"id": "m", "endpoints": [{
            "tag": "deepinfra/fp4", "provider_name": "DeepInfra", "context_length": 1048576,
            "quantization": "fp4", "uptime_last_30m": 97.55,
            "pricing": {"prompt": "0.00000008", "completion": "0.00000018", "input_cache_read": "0.000000016"},
        }]}})
        self.assertEqual(plain_title(_upstream_choice(entry, "deepinfra/fp4").title),
                         "DeepInfra [deepinfra/fp4] — $0.080/$0.180 per M · 1024k ctx · fp4 · cached · 98% up (current)")
        self.assertEqual(_upstream_choice(entry, None).value, "deepinfra/fp4")

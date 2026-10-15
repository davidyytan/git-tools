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

from git_tools.cli import _ask_model_choice, _edit_effort, _edit_model
from git_tools.settings import mappings
from git_tools.settings import settings as settings_module

_OLD_MODEL = "anthropic/claude-sonnet-4.6"
_NEW_MODEL = "vendor/model"


def _openrouter_state(pin: str | None = "old-upstream") -> dict:
    return {"provider": "openrouter", "model": _OLD_MODEL,
            "openrouter_provider": pin, "api_configured": True}


class ModelChangeOpenRouterPinTests(unittest.TestCase):
    """Changing the main model never silently reuses a pin chosen for another model."""

    def setUp(self) -> None:
        for target in ("git_tools.cli._remember_manual_model", "git_tools.cli.console"):
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
              patch("git_tools.cli._list_openrouter_upstreams", return_value=["new-upstream"]),
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
              patch("git_tools.cli._list_openrouter_upstreams", return_value=["other", "old-upstream"]),
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
              patch("git_tools.cli._list_openrouter_upstreams", return_value=["new-upstream"]),
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
              patch("git_tools.cli._list_openrouter_upstreams", return_value=[]),
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
              patch("git_tools.cli._list_openrouter_upstreams", return_value=["new-upstream"]),
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

    def test_settings_rows_show_routing_and_thinking_values(self) -> None:
        from git_tools.cli import _build_settings_choices
        from git_tools.generators.base import plain_title

        base = {"api_configured": False, "support_model": "follow-main", "temperature": 0.6,
                "max_tokens": 32000, "max_retries": 1, "reasoning_effort": None}
        rows = {c.value: plain_title(c.title) for c in _build_settings_choices(
            {**base, "provider": "openrouter", "model": "vendor/model", "openrouter_provider": "deepinfra"})}
        self.assertEqual(rows["openrouter-provider"], "OpenRouter upstream routing: deepinfra")
        self.assertEqual(rows["api-key"], "API Key (openrouter): not set")
        for stored, shown in ((None, "default"), (True, "enabled"), (False, "disabled"), ("odd", "default")):
            rows = {c.value: plain_title(c.title) for c in _build_settings_choices(
                {**base, "provider": "kimicli", "model": "kimi-k2.5", "kimi_thinking": stored})}
            self.assertEqual(rows["kimi-thinking"], f"Kimi thinking: {shown}")


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
        live = mappings.LiveModelList(
            ["kimi-k2.5"],
            metadata={"kimi-k2.5": {"supports_thinking_type": "both",
                                    "think_efforts": {"support": True, "valid_efforts": ["low", "high"]}}},
        )
        state = {"provider": provider, "model": "kimi-k2.5", "reasoning_effort": None, "api_configured": True}
        config = SimpleNamespace(api_key="live-test", base_url="https://live-test.invalid/v1")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(mappings, "MODEL_CATALOG_PATH", Path(tmp) / "catalog.json"),
            patch("git_tools.settings.settings.load_provider_config", return_value=config),
            patch.object(mappings, "_load_user_model_map", return_value={}),
            patch.object(mappings, "fetch_live_models", return_value=live) as fetch,
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

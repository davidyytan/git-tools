"""Provider, API-key, model, and sampling-parameter resolution."""

from typing import Any, Dict, Optional, Tuple

import questionary

from git_tools.settings.mappings import PROVIDERS, refresh_live_models
from git_tools.settings.settings import normalize_provider_name, settings
from git_tools.navigation import NavigationBack

from .terminal import TYPER_STYLE, console, error, print_panel, success, warning
from rich.markup import escape


class ModelSelectionMixin:
    """Resolve provider config and generation parameters from CLI or saved defaults."""

    def display_generation_settings(self, *, input_budget: int, details: str = "") -> None:
        """Show reused preferences without discovery, credentials, or more prompts."""
        if not self._interactive:
            return
        model = self._cli_model if self._cli_model is not None else settings.effective_main_model
        temperature = (self._cli_temperature if self._cli_temperature is not None
                       else settings.default_temperature)
        output_budget = (self._cli_max_tokens if self._cli_max_tokens is not None
                         else settings.default_max_tokens)
        lines = [
            f"Provider: {self.select_provider()}",
            f"Model: {model or 'provider default'}",
            f"Temperature: {temperature} (model capabilities may override)",
            f"Output token budget: {output_budget}",
            f"Input diff budget: {input_budget}",
        ]
        if details:
            lines.append(details)
        print_panel(escape("\n".join(lines)), title="Effective Generation Settings")

    def select_provider(self) -> str:
        """Resolve the configured provider."""
        providers = list(PROVIDERS.keys())
        return settings.default_provider if settings.default_provider in providers else providers[0]

    def ensure_api_key_configured(self, provider: str = "cliproxyapi") -> bool:
        """Check if API key is configured, offer setup if not.

        Args:
            provider: Provider name to check

        Returns:
            True if API key is available (existing or newly set up), False otherwise
        """
        from git_tools.settings.settings import (
            check_api_key_configured,
            provider_label,
            provider_api_key_env,
            save_setting,
        )

        provider = normalize_provider_name(provider)
        is_configured, _ = check_api_key_configured(provider)
        if is_configured:
            return True

        # No API key configured
        warning("No API key configured.")

        # In non-interactive mode, can't prompt for setup
        if not self._interactive:
            error("Run 'git-tools settings' to configure your API key.")
            return False

        # Interactive mode - offer setup
        console.print()
        if self.prompt_confirm(f"Set up your {provider_label(provider)} API key now?", default=True):
            from git_tools.settings.settings import DEFAULT_SETTINGS_PATH
            key = self.prompt_password(f"Enter your {provider_label(provider)} API key").strip()
            if key and save_setting(provider_api_key_env(provider), key):
                console.print()
                success(f"API key saved to {DEFAULT_SETTINGS_PATH}")
                console.print()
                return True
            else:
                console.print()
                warning("API key setup cancelled.")
        else:
            console.print()

        return False

    def get_provider_config(self, provider: str) -> Any:
        """Load provider config ONLY when requested"""
        provider_lower = normalize_provider_name(provider)
        if provider_lower not in self._provider_configs:
            from git_tools.settings.settings import load_provider_config

            self._provider_configs[provider_lower] = load_provider_config(provider_lower)
        return self._provider_configs[provider_lower]

    def select_model_params(
        self, provider: str
    ) -> Tuple[str, Optional[float], Optional[int]]:
        """Resolve CLI overrides, then saved settings/provider defaults.

        Interactive generation reuses the configuration from ``git-tools settings``;
        only workflow decisions and external-generation consent need prompts.
        """
        provider = normalize_provider_name(provider)
        self.get_provider_config(provider)
        # Live catalogs contain only discovered entries (or Kimi's scoped cache); saved/manual IDs and the provider's single default remain independent of discovery.
        live = refresh_live_models(provider)
        # Show empty successful catalogs even in noninteractive generation, without misreporting them as failed discovery.
        if self._interactive or not live or not PROVIDERS[provider]["models"]:
            from git_tools.cli import _print_model_catalog_status

            _print_model_catalog_status(provider, live)
            console.print()
        models = PROVIDERS[provider]["models"]

        # Configuration is chosen once in settings, not on every invocation.
        if self._cli_model is not None:
            selected_model = self._resolve_cli_model(models)
        else:
            selected_model = self._get_default_model(models, provider)
        if provider == "cliproxyapi":
            self._note_implicit_cliproxyapi()
            if live:
                self._require_account_group(selected_model, models)

        # Use explicit None checks so --temp 0.0 remains a valid override.
        temperature = (
            self._cli_temperature
            if self._cli_temperature is not None
            else settings.default_temperature
        )
        max_tokens = (
            self._cli_max_tokens
            if self._cli_max_tokens is not None
            else settings.default_max_tokens
        )

        return selected_model, temperature, max_tokens

    def _note_implicit_cliproxyapi(self) -> None:
        """Say so when CLIProxyAPI is in use only because it became the default, while an OpenRouter key is set: that is how settings from before the change look (OpenRouter was the default), and their OpenRouter model id would otherwise read as an account group."""
        from git_tools.settings.settings import effective_value

        if effective_value("GIT_TOOLS_PROVIDER", "GIT_TOOLS_DEFAULT_PROVIDER")[0] or not effective_value("OPENROUTER_API_KEY")[0]:
            return
        warning(
            "git-tools now defaults to CLIProxyAPI (it was OpenRouter), and no provider is chosen in your settings, "
            "though an OpenRouter key is set. To keep using OpenRouter, run `git-tools settings provider openrouter --non-interactive`; "
            "to use CLIProxyAPI, choose it with `git-tools settings provider cliproxyapi`."
        )
        console.print()

    def _require_account_group(self, model: str, models: Dict[str, Any]) -> None:
        """Stop before anything is sent when CLIProxyAPI cannot serve ``model`` from its account groups.

        Once agent-proxy keeps every account in a group, the proxy serves only ``<group>/<model>`` ids and refuses a plain one, so commands such as ``git-tools commit`` need a group chosen once in settings first. Checked only against a catalog that was just discovered and lists something; an unreadable or empty one is left to the request (and its ``model_not_found`` hint).
        """
        from git_tools.providers.cliproxyapi import split_model_group

        served = {str(config.get("model_name") or key) for key, config in models.items()}
        if not served or model in served:
            return
        groups = sorted({group for group in (split_model_group(item, "cliproxyapi")[0] for item in served) if group})
        group, name = split_model_group(model, "cliproxyapi")
        setup = ("Choose an account group and a model once with `git-tools settings provider cliproxyapi` "
                 "(or `git-tools settings` → provider → Main model)")
        if group is None and groups and name not in served:
            raise ValueError(
                f"CLIProxyAPI keeps its accounts in groups ({', '.join(groups)}) and serves no {name} without one. "
                f"{setup}, or pass a grouped model, for example `--model {groups[0]}/{name}`."
            )
        if group is not None and group not in groups:
            raise ValueError(
                f'CLIProxyAPI serves nothing in the account group "{group}": no account in it is logged in, or the group is gone. '
                f"{setup}: log an account into the group there, or pick another group."
                + (f" Groups served now: {', '.join(groups)}." if groups else "")
            )

    def _get_default_model(self, models: Dict[str, Any], provider: str = "") -> str:
        """Resolve the configured ID, then the provider's single default, independently of discovery."""
        # Check if settings default_model exists in available models
        if settings.effective_main_model:
            # Check if it's a model key
            if settings.effective_main_model in models:
                return models[settings.effective_main_model]["model_name"]
            # Check if it's a full model name
            for model_data in models.values():
                if model_data["model_name"] == settings.effective_main_model:
                    return settings.effective_main_model
            # Manual/live providers trust the configured ID even when discovery is empty or omits it; the endpoint validates generation requests.
            provider_lower = normalize_provider_name(provider)
            if PROVIDERS[provider_lower].get("allow_manual_model"):
                return settings.effective_main_model
        # A provider's single default is configuration, not a discovered catalog entry; curated providers also lead their list with it.
        if provider:
            default = PROVIDERS[normalize_provider_name(provider)].get("default_model")
            if default:
                return default
        return list(models.values())[0]["model_name"]

    def _resolve_cli_model(self, models: Dict[str, Any]) -> str:
        """Resolve CLI model parameter to actual model name.

        Accepts either model key (e.g., 'claude-sonnet') or full model name.
        """
        # Check if it's a model key
        if self._cli_model in models:
            return models[self._cli_model]["model_name"]

        # Check if it's a full model name
        for model_data in models.values():
            if model_data["model_name"] == self._cli_model:
                return self._cli_model

        # Model not found, log warning and use as-is (provider will validate)
        self.logger.warning(
            f"Model '{self._cli_model}' is not in the current provider catalog; using the explicit ID as-is"
        )
        return self._cli_model

    def _interactive_model_selection(
        self, models: Dict[str, Any], provider: str | None = None
    ) -> str:
        """Use the settings picker, including search and invocation-only manual IDs."""
        from git_tools.cli import ADD_MODEL_SENTINEL, _ask_model_choice, _ask_with_back

        provider = normalize_provider_name(provider or self.select_provider())
        current = self._get_default_model(models, provider)
        selected = _ask_model_choice(provider, current_model=current, default_model=current)
        if selected == ADD_MODEL_SENTINEL:
            selected = _ask_with_back(questionary.text(
                f"Enter {provider} model ID:", default=current,
                style=TYPER_STYLE, qmark="❯", instruction="",
            ))
        if selected is None or not selected.strip():
            raise NavigationBack  # Back is distinct from Ctrl+C; never select a fallback.
        return selected.strip()

    def _get_temperature_input(
        self, default: Optional[float] = None
    ) -> Optional[float]:
        """Handle temperature input validation."""
        if default is None:
            default = 0.5

        min_temp, max_temp = settings.default_temperature_range

        while True:
            temp_input = self.prompt_text(
                f"Enter temperature ({min_temp}-{max_temp})",
                str(default),
            )
            if not temp_input.strip():
                return default
            try:
                temperature = float(temp_input)
                if min_temp <= temperature <= max_temp:
                    return temperature
                console.print()
                warning(f"Temperature must be between {min_temp} and {max_temp}.")
            except ValueError:
                console.print()
                warning("Please enter a valid number.")
            console.print()

    def _get_max_tokens_input(self, default: Optional[int] = None) -> Optional[int]:
        """Handle max tokens input validation."""
        if default is None:
            default = settings.default_max_tokens

        while True:
            tokens_input = self.prompt_text(
                "Enter max tokens (> 0)",
                str(default),
            )
            if not tokens_input.strip():
                return default
            try:
                tokens = int(tokens_input)
                if tokens > 0:
                    return tokens
                console.print()
                warning("Max tokens must be greater than 0.")
            except ValueError:
                console.print()
                warning("Please enter a valid integer.")
            console.print()

    def get_token_limit(self, default: int = None, context: str = "diff") -> int:
        """Get token limit from user with validation."""
        if default is None:
            default = settings.default_token_limit

        token_input = self.prompt_text(
            f"Enter maximum token count for {context}",
            str(default),
        )
        try:
            return int(token_input) if token_input else default
        except ValueError:
            console.print()
            warning(f"Invalid input. Using default of {default} tokens.")
            return default

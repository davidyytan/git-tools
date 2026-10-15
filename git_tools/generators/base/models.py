"""Provider, API-key, model, and sampling-parameter resolution."""

from typing import Any, Dict, Optional, Tuple

import questionary

from git_tools.settings.mappings import PROVIDERS, refresh_live_models
from git_tools.settings.settings import normalize_provider_name, settings

from .terminal import TYPER_STYLE, error, success, warning


class ModelSelectionMixin:
    """Resolve provider config and model parameters from CLI, prompts, or defaults."""

    def select_provider(self) -> str:
        """Resolve the configured provider."""
        providers = list(PROVIDERS.keys())
        return settings.default_provider if settings.default_provider in providers else providers[0]

    def ensure_api_key_configured(self, provider: str = "openrouter") -> bool:
        """Check if API key is configured, offer setup if not.

        Args:
            provider: Provider name to check

        Returns:
            True if API key is available (existing or newly set up), False otherwise
        """
        from git_tools.settings.settings import (
            check_api_key_configured,
            provider_label,
            setup_api_key,
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
        if self.prompt_confirm(f"Set up your {provider_label(provider)} API key now?", default=True):
            from git_tools.settings.settings import DEFAULT_SETTINGS_PATH
            if setup_api_key(provider):
                success(f"API key saved to {DEFAULT_SETTINGS_PATH}")
                return True
            else:
                warning("API key setup cancelled.")

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
        """Handle model selection and parameter input flow.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses provider defaults
        """
        provider = normalize_provider_name(provider)
        provider_config = self.get_provider_config(provider)
        # Live providers resolve models against the endpoint's real catalogue
        # (one fetch per process; static fallback when the endpoint is down).
        live = refresh_live_models(provider)
        # Share diagnostics with settings so stale/fallback choices are explicit.
        if self._interactive or not live:
            from git_tools.cli import _print_model_catalog_status

            _print_model_catalog_status(provider, live)
        models = PROVIDERS[provider]["models"]

        # Model selection: CLI param > interactive prompt > default
        if self._cli_model is not None:
            selected_model = self._resolve_cli_model(models)
        elif self._interactive:
            selected_model = self._interactive_model_selection(models, provider)
        else:
            selected_model = self._get_default_model(models, provider)

        # Temperature: CLI param > interactive prompt > settings default
        if self._cli_temperature is not None:
            temperature = self._cli_temperature
        elif self._interactive:
            temperature = self._get_temperature_input(settings.default_temperature)
        else:
            temperature = settings.default_temperature

        # Max tokens: CLI param > interactive prompt > settings default
        if self._cli_max_tokens is not None:
            max_tokens = self._cli_max_tokens
        elif self._interactive:
            max_tokens = self._get_max_tokens_input(settings.default_max_tokens)
        else:
            max_tokens = settings.default_max_tokens

        return selected_model, temperature, max_tokens

    def _get_default_model(self, models: Dict[str, Any], provider: str = "") -> str:
        """Get the default model - from settings first, then first available."""
        # Check if settings default_model exists in available models
        if settings.effective_main_model:
            # Check if it's a model key
            if settings.effective_main_model in models:
                return models[settings.effective_main_model]["model_name"]
            # Check if it's a full model name
            for model_data in models.values():
                if model_data["model_name"] == settings.effective_main_model:
                    return settings.effective_main_model
            # Open-ended (OpenRouter) and live-discovered providers trust the
            # configured model as-is: the endpoint validates it, not the
            # static fallback list.
            provider_lower = normalize_provider_name(provider)
            if PROVIDERS[provider_lower].get("allow_manual_model"):
                return settings.effective_main_model
        # Fallback to the provider module's default model (its curated list
        # leads with it; live-only providers have no list to lead), then to
        # the first listed model.
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
            f"Model '{self._cli_model}' not found in configured models, using as-is"
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
            raise KeyboardInterrupt  # Cancel; never silently pick a different model.
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
                warning(f"Temperature must be between {min_temp} and {max_temp}.")
            except ValueError:
                warning("Please enter a valid number.")

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
                warning("Max tokens must be greater than 0.")
            except ValueError:
                warning("Please enter a valid integer.")

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
            warning(f"Invalid input. Using default of {default} tokens.")
            return default

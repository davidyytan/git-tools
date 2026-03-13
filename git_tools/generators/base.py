# git_tools/generators/base.py
"""Base generator class with shared functionality for all LLM-powered generators.

Provides common methods for LLM interaction, git operations, token counting,
diff processing, and user interaction.
"""

import logging
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import questionary
import tiktoken
from questionary import Style
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from git_tools.config.config import settings
from git_tools.config.mappings import PROVIDERS

# Rich console for styled output
# - soft_wrap: prevents trailing spaces from creating phantom lines
# - force_terminal: ensures consistent TTY detection
# - width offset: fixes off-by-one terminal width issue on some terminals (Rich issue #7)
_auto_width = Console(force_terminal=True).width
_width_offset = settings.console_width_offset
console = Console(soft_wrap=True, force_terminal=True, width=_auto_width + _width_offset if _auto_width else None)

# ============================================================================
# Styling constants (matches Typer's rich_utils.py exactly)
# ============================================================================
STYLE_BORDER = "dim"  # STYLE_OPTIONS_PANEL_BORDER
ALIGN_PANEL = "left"
STYLE_PRIMARY = "bold cyan"  # STYLE_OPTION, STYLE_COMMANDS_TABLE_FIRST_COLUMN
STYLE_SUCCESS = "bold cyan"  # Same as STYLE_OPTION
STYLE_WARNING = "yellow"  # STYLE_USAGE
STYLE_ERROR = "red"  # STYLE_ERRORS_PANEL_BORDER, STYLE_ABORTED
STYLE_DIM = "dim"  # STYLE_OPTION_DEFAULT, STYLE_HELPTEXT


def info(message: str) -> None:
    """Print info message."""
    console.print(f"[{STYLE_SUCCESS}]• {message}[/{STYLE_SUCCESS}]")


def success(message: str) -> None:
    """Print success message."""
    console.print(f"[{STYLE_SUCCESS}]✓ {message}[/{STYLE_SUCCESS}]")


def warning(message: str) -> None:
    """Print warning message (yellow, needs attention)."""
    console.print(f"[{STYLE_WARNING}]⚠ {message}[/{STYLE_WARNING}]")


def error(message: str) -> None:
    """Print error message (red, needs action)."""
    console.print(f"[{STYLE_ERROR}]✗ {message}[/{STYLE_ERROR}]")


def print_panel(content: str, title: str = "", border_style: str = STYLE_BORDER) -> None:
    """Print content in a Typer-style panel."""
    console.print(Panel(content.strip(), title=f"[bold]{title}[/bold]" if title else "", border_style=border_style, title_align=ALIGN_PANEL))


# Style for questionary prompts (matches Typer's STYLE_OPTION = "bold cyan")
# Note: prompt_toolkit uses "ansicyan" not "cyan", and "noreverse" prevents filled background
TYPER_STYLE = Style([
    ("qmark", ""),
    ("question", ""),
    ("answer", "bold ansicyan"),
    ("pointer", "bold ansicyan"),
    ("highlighted", "bold ansicyan noreverse"),
    ("selected", "noreverse"),  # No cyan - we reorder choices instead of using questionary's default
    ("instruction", ""),
    ("text", ""),
    ("disabled", ""),
])

# Note: Logging is configured in main.py at application startup

# Initialize tiktoken encoder once at module level
_ENCODER = tiktoken.get_encoding("cl100k_base")
_SPECIAL_TOKENS = _ENCODER.special_tokens_set


def _escape_special_tokens(text: str) -> str:
    """Escape tiktoken special tokens to prevent them from being encoded as single tokens.

    Args:
        text: The text that may contain special tokens

    Returns:
        Text with special tokens escaped (e.g., <|endoftext|> -> <\\|endoftext\\|>)
    """
    for token in _SPECIAL_TOKENS:
        if token in text:
            escaped = token.replace("|", "\\|")
            text = text.replace(token, escaped)
    return text


def count_tokens(text: str) -> int:
    """Count tokens in a string using cl100k_base encoding.

    Args:
        text: The text to count tokens for

    Returns:
        Number of tokens in the text
    """
    return len(_ENCODER.encode(_escape_special_tokens(text)))


def _get_openrouter_extra_body(
    model_name: str,
    base_extra_body: Dict[str, Any],
    model_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return model-specific extra_body for OpenRouter.

    Reads provider configuration from mappings.json if available, otherwise
    falls back to the provided base_extra_body.

    Args:
        model_name: The model name/identifier
        base_extra_body: Default extra_body configuration
        model_config: Optional model configuration from mappings.json

    Returns:
        Dict with provider routing configuration
    """
    extra_body = base_extra_body.copy()
    provider_preferences: Dict[str, Any] = {
        "allow_fallbacks": True,
        "data_collection": model_config.get("data_collection", "deny") if model_config else "deny",
    }

    # Empty strings and empty arrays should behave like "unspecified" so
    # OpenRouter can use its default routing instead of an accidental filter.
    if model_config and "provider_config" in model_config:
        provider_preferences.update(
            _sanitize_openrouter_provider_config(model_config["provider_config"])
        )

    if provider_preferences:
        extra_body["provider"] = provider_preferences

    return extra_body


def _sanitize_openrouter_provider_config(provider_config: Any) -> Dict[str, Any]:
    """Drop empty provider preference values before sending them to OpenRouter."""
    if not isinstance(provider_config, dict):
        return {}

    sanitized: Dict[str, Any] = {}
    for key, value in provider_config.items():
        if value is None:
            continue

        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                sanitized[key] = stripped
            continue

        if isinstance(value, list):
            filtered = []
            for item in value:
                if item is None:
                    continue
                if isinstance(item, str):
                    item = item.strip()
                    if not item:
                        continue
                filtered.append(item)
            if filtered:
                sanitized[key] = filtered
            continue

        if isinstance(value, dict):
            nested = _sanitize_openrouter_provider_config(value)
            if nested:
                sanitized[key] = nested
            continue

        sanitized[key] = value

    return sanitized


class BaseGenerator:
    """Base class for all LLM-powered generators."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        token_limit: Optional[int] = None,
        interactive: bool = False,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._provider_configs = {}  # Cache for loaded provider configs
        self.chatclient = None

        # Interactive mode: True = prompt for missing params, False = use defaults
        self._interactive = interactive

        # CLI parameters (None means use default or prompt based on interactive mode)
        self._cli_model = model
        self._cli_temperature = temperature
        self._cli_max_tokens = max_tokens
        self._cli_token_limit = token_limit

    def _load_prompt_template(self, filename: str) -> str:
        """Load prompt template from file.

        Args:
            filename: Name of the prompt file (e.g., 'commitgen_prompt.txt')

        Returns:
            Contents of the prompt file
        """
        try:
            from pathlib import Path

            prompts_dir = Path(__file__).parent.parent / "prompts"
            with open(prompts_dir / filename, "r") as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to load prompt template {filename}: {str(e)}")
            raise e

    def _render_prompt_template(self, filename: str, **kwargs: Any) -> str:
        """Load and optionally format a prompt template from file."""
        template = self._load_prompt_template(filename)
        return template.format(**kwargs) if kwargs else template

    def prompt_text(self, message: str, default: str = "") -> str:
        """Prompt for text input using questionary for consistent styling."""
        result = questionary.text(
            f"{message}:",
            default=default,
            style=TYPER_STYLE,
            qmark="❯",
            instruction="",
        ).ask()
        return result if result is not None else default

    def prompt_confirm(self, message: str, default: bool = True) -> bool:
        """Prompt for yes/no confirmation using select menu."""
        # Order choices so desired default is first (cursor starts there naturally)
        if default:
            choices = ["Yes", "No"]
        else:
            choices = ["No", "Yes"]
        result = self.prompt_select(message, choices)
        return result == "Yes"

    def prompt_select(self, message: str, choices: List[str], default: str = None) -> str:
        """Prompt for selection from choices with questionary (arrow-key navigation).

        If default is specified, reorders choices so default appears first
        (cursor naturally starts at first item, avoiding questionary's default styling issue).
        """
        # Reorder choices so default is first if specified
        if default and default in choices:
            choices = [default] + [c for c in choices if c != default]

        result = questionary.select(
            f"{message}:",
            choices=choices,
            style=TYPER_STYLE,
            qmark="❯",
            pointer="›",
            instruction="",
        ).ask()
        return result if result is not None else choices[0]

    def get_user_input(self, prompt: str, default: Optional[str] = None) -> str:
        """Get input from user with default value support (legacy wrapper)."""
        # Handle yes/no prompts
        if "yes/no" in prompt.lower() or "[y]" in prompt.lower():
            result = self.prompt_confirm(prompt.replace(" [yes/no]", "").replace("[yes/no]", ""), default == "yes")
            return "yes" if result else "no"

        return self.prompt_text(prompt, default or "")

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
        from git_tools.config.config import check_api_key_configured, setup_api_key

        is_configured, _ = check_api_key_configured(provider)
        if is_configured:
            return True

        # No API key configured
        warning("No API key configured.")

        # In non-interactive mode, can't prompt for setup
        if not self._interactive:
            error("Run 'git-tools config' to configure your API key.")
            return False

        # Interactive mode - offer setup
        provider_label = {
            "openrouter": "OpenRouter",
            "kimicli": "Kimi CLI",
        }.get(provider.lower(), provider)
        if self.prompt_confirm(f"Set up your {provider_label} API key now?", default=True):
            from git_tools.config.config import DEFAULT_CONFIG_PATH
            if setup_api_key(provider):
                success(f"API key saved to {DEFAULT_CONFIG_PATH}")
                return True
            else:
                warning("API key setup cancelled.")

        return False

    def get_provider_config(self, provider: str) -> Any:
        """Load provider config ONLY when requested"""
        provider_lower = provider.lower()
        if provider_lower not in self._provider_configs:
            from git_tools.config.config import load_provider_config

            self._provider_configs[provider_lower] = load_provider_config(provider)
        return self._provider_configs[provider_lower]

    def select_model_params(
        self, provider: str
    ) -> Tuple[str, Optional[float], Optional[int]]:
        """Handle model selection and parameter input flow.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses provider defaults
        """
        provider_config = self.get_provider_config(provider)
        models = PROVIDERS[provider]["models"]

        # Model selection: CLI param > interactive prompt > default
        if self._cli_model is not None:
            selected_model = self._resolve_cli_model(models)
        elif self._interactive:
            selected_model = self._interactive_model_selection(models)
        else:
            selected_model = self._get_default_model(models)

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

    def _get_default_model(self, models: Dict[str, Any]) -> str:
        """Get the default model - from settings first, then first available."""
        # Check if settings default_model exists in available models
        if settings.default_model:
            # Check if it's a model key
            if settings.default_model in models:
                return models[settings.default_model]["model_name"]
            # Check if it's a full model name
            for model_data in models.values():
                if model_data["model_name"] == settings.default_model:
                    return settings.default_model
        # Fallback to first model
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

    def _interactive_model_selection(self, models: Dict[str, Any]) -> str:
        """Interactive model selection with questionary."""
        # Build choices list
        choices = [model["model_name"] for model in models.values()]

        # Use settings.default_model if it's in the available choices
        default = None
        if settings.default_model in choices:
            default = settings.default_model
        else:
            # Check if it's a model key that maps to a model_name
            for model_key, model_data in models.items():
                if model_key == settings.default_model or model_data["model_name"] == settings.default_model:
                    default = model_data["model_name"]
                    break

        return self.prompt_select("Select model", choices, default)

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

    def ask_to_copy_to_clipboard(self, content: str) -> None:
        """Ask user to copy parsed content to clipboard."""
        try:
            import pyperclip
        except ImportError:
            self.logger.warning(
                "pyperclip not installed. Clipboard functionality unavailable."
            )
            warning("Install pyperclip for clipboard support: uv add pyperclip")
            return

        if self.prompt_confirm("Copy to clipboard?", default=True):
            try:
                pyperclip.copy(content)
                console.print()
                success("Copied to clipboard!")
            except Exception as e:
                self.logger.error(f"Clipboard error: {e}")
                error("Failed to copy content.")
        else:
            console.print()
            success("Generation complete.")

    def copy_to_clipboard_auto(self, content: str) -> None:
        """Copy content to clipboard without prompting (for local mode)."""
        try:
            import pyperclip
            pyperclip.copy(content)
            console.print()
            success("Copied to clipboard!")
        except ImportError:
            self.logger.warning("pyperclip not installed. Clipboard functionality unavailable.")
            warning("Install pyperclip for clipboard support: uv add pyperclip")
        except Exception as e:
            self.logger.error(f"Clipboard error: {e}")
            error("Failed to copy content.")

    def _initialize_service(
        self,
        provider: str,
        model: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> bool:
        """Initialize LangChain chat client for the selected provider"""
        try:
            provider_config = self.get_provider_config(provider)
            model_details = PROVIDERS[provider]["models"].get(model, {})
            model_to_use = model_details.get("model_name", model)

            if provider == "openrouter":
                self.chatclient = self._create_openrouter_client(
                    model_to_use, provider_config, temperature, max_tokens
                )
            elif provider == "kimicli":
                self.chatclient = self._create_kimicli_client(
                    model_to_use, provider_config, temperature, max_tokens
                )
            else:
                raise ValueError(f"Unsupported provider: {provider}")

            return True

        except Exception as e:
            # Log error type without full message to avoid potential credential leaks
            self.logger.error(
                f"Failed to initialize {provider} service: {type(e).__name__}"
            )
            self.logger.debug(f"Initialization error details: {e}")
            return False

    def _add_optional_params(
        self,
        kwargs: Dict[str, Any],
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> None:
        """Add optional parameters to kwargs dict using settings as fallback."""
        kwargs["temperature"] = temperature if temperature is not None else settings.default_temperature
        kwargs["max_tokens"] = max_tokens if max_tokens is not None else settings.default_max_tokens
        kwargs["max_retries"] = settings.default_max_retries

    def _create_openrouter_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for OpenRouter"""
        from langchain_openai import ChatOpenAI

        base_extra_body: Dict[str, Any] = {
            "usage": {"include": True},
        }

        # Get model config from PROVIDERS to pass provider_config
        model_config = None
        for model_key, model_data in PROVIDERS["openrouter"]["models"].items():
            if model_data.get("model_name") == model_to_use:
                model_config = model_data
                break

        extra_body = _get_openrouter_extra_body(
            model_to_use, base_extra_body, model_config
        )

        kwargs = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "extra_body": extra_body,
        }

        self._add_optional_params(kwargs, temperature, max_tokens)
        return ChatOpenAI(**kwargs)

    def _create_kimicli_client(
        self,
        model_to_use: str,
        provider_config: Any,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ):
        """Create ChatOpenAI client for the Kimi CLI-compatible endpoint."""
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": model_to_use,
            "api_key": provider_config.api_key,
            "base_url": provider_config.base_url,
            "default_headers": {"User-Agent": "KimiCLI/1.3"},
            "extra_body": {
                "thinking": {"type": "disabled"},
            },
        }

        self._add_optional_params(kwargs, temperature, max_tokens)
        return ChatOpenAI(**kwargs)

    def get_staged_diff(self) -> Optional[str]:
        """Get staged changes using git diff.

        Returns:
            Staged diff content or None if error occurs
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--staged"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Error getting git diff: {e}")
            return None

    def _process_diff_with_size_limiting(
        self, full_diff: str, max_token_count: Optional[int]
    ) -> Tuple[str, List[str]]:
        """Process a diff with optional size limiting and quota allocation.

        When context limit is exceeded, drops the smallest files above min_file_token_threshold
        first, working up the list until we fit within the limit. Then applies proportional
        allocation to remaining files.

        Args:
            full_diff: The complete diff content
            max_token_count: If set, truncates diffs to stay within this token count

        Returns:
            Tuple of (processed_diff, quota_breakdown)
        """
        # If no token count limit, return raw diff
        if max_token_count is None:
            return full_diff, []

        # Parse diff into files and drop LFS files
        file_diffs, dropped_lfs_files = self._parse_diff_files(full_diff)

        # Calculate total token count
        total_tokens = sum(count_tokens(diff) for _, diff in file_diffs)

        # If under limit, return full diff with quota breakdown (no dropping needed)
        if total_tokens <= max_token_count:
            return self._create_quota_breakdown_for_full_diff(
                file_diffs, max_token_count, full_diff, dropped_lfs_files
            )

        # Drop files to fit within context limit and calculate quotas
        file_quotas, dropped_files = self._calculate_proportional_quotas(
            file_diffs, max_token_count
        )
        truncated_diffs = self._truncate_diffs_to_quotas(file_diffs, file_quotas)
        quota_breakdown = self._create_detailed_quota_breakdown(
            file_diffs, file_quotas, dropped_files, dropped_lfs_files
        )

        return "\n\n".join(truncated_diffs), quota_breakdown

    def _parse_diff_files(
        self, full_diff: str
    ) -> Tuple[List[Tuple[str, str]], List[str]]:
        """Parse diff content into individual file diffs, dropping LFS files completely.

        Returns:
            Tuple of (file_diffs, dropped_lfs_files)
            - file_diffs: List of (filename, diff) tuples (LFS files excluded)
            - dropped_lfs_files: List of LFS filenames that were dropped
        """
        file_diffs = []
        current_file = []
        current_file_name = None
        is_lfs_file = False
        dropped_lfs_files = []

        for line in full_diff.split("\n"):
            if line.startswith("diff --git"):
                if current_file and not is_lfs_file:
                    # Only add non-LFS files
                    file_diffs.append((current_file_name, "\n".join(current_file)))
                elif is_lfs_file:
                    dropped_lfs_files.append(current_file_name)

                current_file = [line]
                is_lfs_file = False
                try:
                    current_file_name = line.split(" ")[2][
                        2:
                    ]  # Extract filename from diff header
                except IndexError:
                    self.logger.warning(f"Malformed diff header: {line}")
                    continue
            elif line.startswith(
                "+version https://git-lfs.github.com/spec/"
            ) or line.startswith("-version https://git-lfs.github.com/spec/"):
                is_lfs_file = True
            else:
                current_file.append(line)

        # Handle the last file
        if current_file and not is_lfs_file:
            file_diffs.append((current_file_name, "\n".join(current_file)))
        elif is_lfs_file:
            dropped_lfs_files.append(current_file_name)

        if dropped_lfs_files:
            self.logger.info(
                f"Dropping {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}"
            )

        return file_diffs, dropped_lfs_files

    def _create_quota_breakdown_for_full_diff(
        self,
        file_diffs: List[Tuple[str, str]],
        max_token_count: int,
        full_diff: str,
        dropped_lfs_files: List[str],
    ) -> Tuple[str, List[str]]:
        """Create quota breakdown when full diff is under the token limit."""
        quota_breakdown = []

        if dropped_lfs_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}\n"
            )

        diff_sizes = {filename: count_tokens(diff) for filename, diff in file_diffs}
        total_size = sum(diff_sizes.values()) if diff_sizes else 1

        for filename, diff in file_diffs:
            diff_tokens = count_tokens(diff)
            proportion = diff_tokens / total_size
            quota = max(1, int(proportion * max_token_count))
            quota_breakdown.append(
                f"- {filename}: Original diff size: {diff_tokens} tokens, Quota allocated: {quota} tokens"
            )

        return full_diff, quota_breakdown

    def _calculate_proportional_quotas(
        self, file_diffs: List[Tuple[str, str]], max_token_count: int
    ) -> Tuple[Dict[str, int], List[str]]:
        """Calculate quotas using proportional mode with smart file dropping.

        When total tokens exceed max_token_count, drops the smallest files above
        min_file_token_threshold first, working up the list until we fit within
        the limit. Files below min_file_token_threshold are never dropped.

        Returns:
            Tuple of (file_quotas, dropped_files)
        """
        # Calculate token sizes for all files
        diff_sizes = {filename: count_tokens(diff) for filename, diff in file_diffs}
        total_tokens = sum(diff_sizes.values())

        dropped_files = []

        # If we're over the limit, drop files starting from smallest above threshold
        if total_tokens > max_token_count:
            # Helper to check if file has protected extension
            protected_extensions = set(settings.protected_file_extensions)

            def is_protected_extension(filename: str) -> bool:
                return any(filename.endswith(ext) for ext in protected_extensions)

            # Separate files into droppable and protected
            # Protected if: below token threshold OR has protected extension
            droppable_files = [
                (f, s)
                for f, s in diff_sizes.items()
                if s >= settings.min_file_token_threshold
                and not is_protected_extension(f)
            ]
            protected_files = [
                (f, s)
                for f, s in diff_sizes.items()
                if s < settings.min_file_token_threshold
                or is_protected_extension(f)
            ]

            # Sort droppable files by size (smallest first)
            droppable_files.sort(key=lambda x: x[1])

            # Drop files one at a time starting from smallest until under limit
            for filename, size in droppable_files:
                if total_tokens <= max_token_count:
                    break
                dropped_files.append(filename)
                total_tokens -= size
                del diff_sizes[filename]

            if dropped_files:
                self.logger.info(
                    f"Dropping {len(dropped_files)} file(s) to fit context limit: {', '.join(dropped_files)}"
                )

        # If all files are dropped, return empty quotas
        if not diff_sizes:
            self.logger.warning("All files were dropped. No files to process.")
            return {}, dropped_files

        # Calculate proportional quotas for remaining files
        total_size = sum(diff_sizes.values())

        file_quotas = {}
        for filename, size in diff_sizes.items():
            proportion = size / total_size
            file_quotas[filename] = max(1, int(proportion * max_token_count))

        # Adjust for rounding errors
        total_allocated = sum(file_quotas.values())
        if total_allocated < max_token_count:
            largest_file = max(diff_sizes.items(), key=lambda x: x[1])[0]
            file_quotas[largest_file] += max_token_count - total_allocated

        return file_quotas, dropped_files

    def _truncate_diffs_to_quotas(
        self, file_diffs: List[Tuple[str, str]], file_quotas: Dict[str, int]
    ) -> List[str]:
        """Truncate each file's diff to its allocated quota.

        Only processes files that exist in file_quotas (dropped files are skipped).
        """
        truncated_diffs = []
        for filename, diff in file_diffs:
            # Skip files that were dropped
            if filename not in file_quotas:
                continue

            quota = file_quotas[filename]
            diff_tokens = count_tokens(diff)

            if diff_tokens > quota:
                # Use tiktoken to decode truncated tokens back to text
                encoded = _ENCODER.encode(_escape_special_tokens(diff))
                truncated_tokens = encoded[:quota]
                truncated_diff = _ENCODER.decode(truncated_tokens)
                truncated_diffs.append(
                    f"# Truncated diff for {filename} (original: {diff_tokens} tokens)\n{truncated_diff}"
                )
            else:
                truncated_diffs.append(diff)
        return truncated_diffs

    def _create_detailed_quota_breakdown(
        self,
        file_diffs: List[Tuple[str, str]],
        file_quotas: Dict[str, int],
        dropped_files: List[str],
        dropped_lfs_files: List[str],
    ) -> List[str]:
        """Create detailed breakdown of file quotas."""
        quota_breakdown = []

        if dropped_lfs_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}\n"
            )

        if dropped_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_files)} file(s) to fit context limit: {', '.join(dropped_files)}\n"
            )

        for filename, quota in file_quotas.items():
            diff_tokens = count_tokens(
                next(diff for f, diff in file_diffs if f == filename)
            )
            quota_breakdown.append(
                f"- {filename}: Original diff size: {diff_tokens} tokens, Quota allocated: {quota} tokens"
            )
        return quota_breakdown

    def get_branch_diffs(
        self, base_branch: str, max_token_count: Optional[int] = None
    ) -> Optional[Tuple[str, List[str]]]:
        """Get unified diff between base branch and HEAD (committed changes only).

        Uses git diff base_branch...HEAD which compares the merge-base with HEAD,
        excluding any staged or uncommitted changes.

        Args:
            base_branch: The base branch to compare against
            max_token_count: If set, enables size-aware mode and truncates diffs to stay within this token count
        """
        try:
            full_diff = subprocess.check_output(
                ["git", "diff", f"{base_branch}...HEAD"], text=True, timeout=60
            ).strip()

            return self._process_diff_with_size_limiting(full_diff, max_token_count)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Diff error: {e}")
            return None

    def get_staged_diff_enhanced(
        self, max_token_count: Optional[int] = None
    ) -> Optional[Tuple[str, List[str]]]:
        """Get staged changes with optional size limiting and advanced processing.

        Args:
            max_token_count: If set, enables size-aware mode and truncates diffs to stay within this token count
        """
        try:
            full_diff = subprocess.check_output(
                ["git", "diff", "--staged"], text=True, timeout=60
            ).strip()

            return self._process_diff_with_size_limiting(full_diff, max_token_count)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Staged diff error: {e}")
            return None

    def get_diff_processing_params(self, default_token_count: int) -> int:
        """Unified method to get diff processing parameters.

        Uses CLI token_limit if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses default

        Args:
            default_token_count: Default token count limit for this generator type

        Returns:
            max_token_count: The token limit for diff processing
        """
        if self._cli_token_limit is not None:
            return self._cli_token_limit
        if self._interactive:
            return self.get_token_limit(default=default_token_count, context="diff")
        return default_token_count

    def display_quota_breakdown(
        self, quota_breakdown: List[str], max_token_count: int
    ) -> None:
        """Unified method to display quota breakdown with sorting.

        Args:
            quota_breakdown: List of quota breakdown lines
            max_token_count: Maximum token count limit used
        """
        if not quota_breakdown:
            return

        # Separate dropped files messages from quota allocations
        dropped_messages = [
            line for line in quota_breakdown if line.startswith("\nDropped")
        ]
        quota_lines = [
            line for line in quota_breakdown if not line.startswith("\nDropped")
        ]

        # Sort quota lines by original diff size (descending)
        sorted_quotas = sorted(
            quota_lines,
            key=lambda x: int(x.split("Original diff size: ")[1].split(" tokens")[0])
            if "Original diff size:" in x
            else 0,
            reverse=True,
        )

        # Build panel content
        lines = []
        for msg in dropped_messages:
            lines.append(f"[{STYLE_WARNING}]⚠ {msg.strip()}[/{STYLE_WARNING}]")

        for line in sorted_quotas:
            if "Original diff size:" in line:
                parts = line.split(":")
                filename = parts[0].replace("- ", "").strip()
                try:
                    orig = line.split("Original diff size: ")[1].split(" tokens")[0]
                    alloc = line.split("Quota allocated: ")[1].split(" tokens")[0]
                    lines.append(f"[{STYLE_DIM}]•[/{STYLE_DIM}] {filename} [{STYLE_DIM}]({orig} → {alloc})[/{STYLE_DIM}]")
                except (IndexError, ValueError):
                    lines.append(f"[{STYLE_DIM}]• {line}[/{STYLE_DIM}]")
            else:
                lines.append(f"[{STYLE_DIM}]{line}[/{STYLE_DIM}]")

        # Filter out empty lines and strip each line to prevent phantom newlines
        clean_lines = [line.strip() for line in lines if line.strip()]
        console.print(Panel(
            "\n".join(clean_lines),
            title=f"[bold]File Quota[/bold] [{STYLE_DIM}]{max_token_count:,} tokens[/{STYLE_DIM}]",
            border_style=STYLE_BORDER,
            title_align=ALIGN_PANEL,
        ))

    def invoke_llm(
        self,
        messages: List[Dict[str, str]],
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Unified method to invoke LLM and format response with retry logic.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            max_retries: Maximum number of retry attempts (default: from provider config or 1)
            retry_delay: Delay between retries in seconds (default: from provider config or 1.0)

        Returns:
            Formatted response dict with 'content', 'response_metadata', 'additional_kwargs'
        """
        # Get retry settings from settings if not specified
        if max_retries is None:
            max_retries = settings.default_max_retries

        if retry_delay is None:
            retry_delay = settings.default_retry_delay

        last_error = None
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                if attempt > 0:
                    warning(f"Retrying LLM request (attempt {attempt + 1}/{max_retries + 1})...")

                with console.status("Generating response from LLM...", spinner="dots"):
                    response = self.chatclient.invoke(messages)

                output = {"content": response.content}

                if response.response_metadata:
                    output["response_metadata"] = response.response_metadata

                if response.additional_kwargs:
                    output["additional_kwargs"] = response.additional_kwargs

                return output

            except Exception as e:
                last_error = e
                self.logger.warning(
                    f"LLM invocation attempt {attempt + 1} failed: {type(e).__name__}"
                )

                # Don't retry on certain errors (e.g., auth errors, invalid requests)
                error_str = str(e).lower()
                if any(
                    term in error_str
                    for term in [
                        "unauthorized",
                        "invalid_api_key",
                        "authentication",
                        "forbidden",
                    ]
                ):
                    self.logger.error(f"Non-retryable error: {type(e).__name__}")
                    break

                # Wait before retrying (except on last attempt)
                if attempt < max_retries:
                    self.logger.info(f"Waiting {retry_delay}s before retry...")
                    time.sleep(retry_delay)

        self.logger.error(
            f"LLM invocation failed after {max_retries + 1} attempts: {last_error}"
        )
        return None

    def display_token_usage(self, response: Dict[str, Any]) -> None:
        """Unified method to display token usage and cost information.

        Args:
            response: Response dict from LLM invocation
        """
        token_usage = response.get("response_metadata", {}).get("token_usage")
        if not token_usage:
            return

        # Build token usage content
        lines = []
        prompt_tokens = token_usage.get("prompt_tokens")
        completion_tokens = token_usage.get("completion_tokens")
        total_tokens = token_usage.get("total_tokens")
        reasoning_tokens = token_usage.get("completion_tokens_details", {}).get("reasoning_tokens")

        if prompt_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Prompt:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{prompt_tokens:,}[/{STYLE_PRIMARY}]")
        if completion_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Completion:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{completion_tokens:,}[/{STYLE_PRIMARY}]")
        if reasoning_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Reasoning:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{reasoning_tokens:,}[/{STYLE_PRIMARY}]")
        if total_tokens is not None:
            lines.append(f"[bold]Total:[/bold] [{STYLE_PRIMARY}]{total_tokens:,}[/{STYLE_PRIMARY}]")

        # Cost information
        cost = token_usage.get("cost")
        upstream_cost = token_usage.get("cost_details", {}).get("upstream_inference_cost")

        if cost is not None or upstream_cost is not None:
            lines.append("")
            if cost is not None:
                lines.append(f"[{STYLE_DIM}]Cost:[/{STYLE_DIM}] [{STYLE_SUCCESS}]${cost:.6f}[/{STYLE_SUCCESS}]")
            if upstream_cost is not None:
                lines.append(f"[{STYLE_DIM}]Upstream:[/{STYLE_DIM}] [{STYLE_SUCCESS}]${upstream_cost:.6f}[/{STYLE_SUCCESS}]")
            total_cost = (cost or 0) + (upstream_cost or 0)
            lines.append(f"[bold]Total Cost:[/bold] [{STYLE_SUCCESS}]${total_cost:.6f}[/{STYLE_SUCCESS}]")

        console.print(Panel("\n".join(lines).strip(), title="[bold]Token Usage[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))

    def display_reasoning(self, response: Dict[str, Any]) -> None:
        """Display reasoning content if available in response.

        Args:
            response: Response dict from LLM invocation
        """
        reasoning_content = response.get("additional_kwargs", {}).get(
            "reasoning_content"
        )
        if reasoning_content:
            console.print(Panel(escape(reasoning_content.strip()), title="[bold]Reasoning[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))

    @staticmethod
    def extract_code_block(
        content: str, pattern: str = r"```[\w]*(?:\n|\s)(.*?)```"
    ) -> Optional[str]:
        """Extract content from code blocks.

        Handles both formats:
        ```
        code here
        ```

        and:
        ```python
        code here
        ```
        """
        content = content.rstrip()
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else None

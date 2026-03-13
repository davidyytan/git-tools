"""Configuration module for LLM provider settings.

This module provides Pydantic-based configuration classes for different LLM providers,
loading API keys from environment files and validating settings.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings

from .mappings import PROVIDERS

# Whitelist of allowed configuration classes for security
ALLOWED_CONFIG_CLASSES = {"OpenRouterConfig", "KimiCLIConfig"}

# Default config file location (XDG standard)
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "git-tools" / "config.env"


def _get_env_file_paths() -> list[Path]:
    """Get environment file search paths.

    Search order (last found wins in pydantic-settings):
    1. {cwd}/git-tools.env (local development, lowest priority)
    2. ~/.config/git-tools/config.env (XDG standard, highest priority)

    Environment variables (e.g., OPENROUTER_API_KEY) always take precedence.

    Returns:
        List of Path objects to search for env file
    """
    return [
        Path.cwd() / "git-tools.env",
        Path.home() / ".config" / "git-tools" / "config.env",
    ]


def _get_provider_definition(provider: str) -> dict[str, Any]:
    provider_lower = provider.lower()
    if provider_lower not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    return PROVIDERS[provider_lower]


def _get_provider_api_key_envs(provider: str) -> list[str]:
    provider_def = _get_provider_definition(provider)
    envs = []
    primary_env = provider_def.get("api_key_env")
    fallback_env = provider_def.get("api_key_env_fallback")
    if primary_env:
        envs.append(primary_env)
    if fallback_env and fallback_env not in envs:
        envs.append(fallback_env)
    if not envs:
        envs.append(f"{provider.upper()}_API_KEY")
    return envs


def _get_provider_label(provider: str) -> str:
    labels = {
        "openrouter": "OpenRouter",
        "kimicli": "Kimi CLI",
    }
    return labels.get(provider.lower(), provider.title())


def check_api_key_configured(provider: str = "openrouter") -> tuple[bool, str | None]:
    """Check if API key is available without triggering validation error.

    Args:
        provider: Provider name (default: "openrouter")

    Returns:
        Tuple of (is_configured, key_value_or_none)
    """
    env_vars = _get_provider_api_key_envs(provider)

    # Check environment variable first
    for env_var in env_vars:
        if key := os.environ.get(env_var):
            return True, key

    # Check .env files
    for env_var in env_vars:
        pattern = re.compile(rf'^{env_var}\s*=\s*["\']?([^"\'#\n]+)["\']?', re.MULTILINE)
        for path in _get_env_file_paths():
            if path.exists():
                try:
                    content = path.read_text()
                    if match := pattern.search(content):
                        return True, match.group(1).strip()
                except OSError:
                    continue

    return False, None


def save_setting(key: str, value: str) -> bool:
    """Save a setting to the config file.

    Args:
        key: Environment variable name (e.g., 'GIT_TOOLS_DEFAULT_MODEL')
        value: Value to save

    Returns:
        True if saved successfully, False otherwise
    """
    # Ensure config directory exists
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content or start fresh
    if DEFAULT_CONFIG_PATH.exists():
        content = DEFAULT_CONFIG_PATH.read_text()
        pattern = re.compile(rf'^{key}\s*=.*$', re.MULTILINE)
        if pattern.search(content):
            # Update existing key
            content = pattern.sub(f'{key}="{value}"', content)
        else:
            # Append new key
            content = content.rstrip() + f'\n{key}="{value}"\n'
    else:
        content = f'{key}="{value}"\n'

    DEFAULT_CONFIG_PATH.write_text(content)
    return True


def setup_api_key(provider: str = "openrouter") -> bool:
    """Prompt user for API key and save to config file.

    Args:
        provider: Provider name (default: "openrouter")

    Returns:
        True if key was saved successfully, False otherwise
    """
    from rich.prompt import Prompt

    env_var = _get_provider_api_key_envs(provider)[0]
    key = Prompt.ask(f"Enter your {_get_provider_label(provider)} API key", password=True)

    if not key or not key.strip():
        return False

    return save_setting(env_var, key.strip())


class GitToolsSettings(BaseSettings):
    """Application-wide settings loaded from environment variables.

    All settings have sensible defaults and can be overridden via environment
    variables with the GIT_TOOLS_ prefix. Empty strings are treated as unset.

    Attributes:
        default_provider: Default LLM provider to use
        default_model: Default LLM model to use for the selected provider
        default_temperature: Default temperature for LLM requests
        default_max_tokens: Default max tokens for LLM responses
        default_max_retries: Default max retries for LLM requests
        default_retry_delay: Default delay between retries in seconds
        default_token_limit: Default token limit for diff processing (default: 200000)
        default_issue_pr_token_limit: Default token limit for issue/PR generation (default: 200000)
        large_diff_threshold: Threshold for large diff detection (default: 5000)
        min_file_token_threshold: Files below this are never dropped (default: 1000)
        console_width_offset: Offset for console width to prevent border wrapping (default: -2)
        protected_file_extensions: File extensions that are never dropped, only truncated
    """

    # LLM defaults
    default_provider: str = Field(
        default="openrouter",
        validation_alias=AliasChoices("GIT_TOOLS_PROVIDER", "GIT_TOOLS_DEFAULT_PROVIDER"),
    )
    default_model: Optional[str] = Field(default=None)
    default_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=8000, ge=1)
    default_max_retries: int = Field(default=1, ge=0)
    default_retry_delay: float = Field(default=1.0, ge=0.0)

    # Token limits
    default_token_limit: int = Field(default=200000, ge=1)
    default_issue_pr_token_limit: int = Field(default=200000, ge=1)
    large_diff_threshold: int = Field(default=5000, ge=1)

    # Other settings
    min_file_token_threshold: int = Field(default=1000, ge=0)
    console_width_offset: int = Field(default=-2)
    protected_file_extensions: list[str] = Field(
        default=[
            ".py", ".ts", ".js", ".tsx", ".jsx",
            ".go", ".rs", ".java", ".c", ".cpp", ".h",
            ".md", ".ipynb",
        ]
    )

    @field_validator(
        "default_token_limit",
        "default_issue_pr_token_limit",
        "large_diff_threshold",
        "default_max_tokens",
        "default_max_retries",
        "min_file_token_threshold",
        "console_width_offset",
        mode="before",
    )
    @classmethod
    def empty_str_to_default_int(cls, v: Any, info: ValidationInfo) -> Any:
        """Convert empty strings to default value for int fields."""
        if v == "" or v is None:
            defaults = {
                "default_token_limit": 200000,
                "default_issue_pr_token_limit": 200000,
                "large_diff_threshold": 5000,
                "default_max_tokens": 8000,
                "default_max_retries": 1,
                "min_file_token_threshold": 1000,
                "console_width_offset": -2,
            }
            return defaults.get(info.field_name, v)
        return v

    @field_validator(
        "default_temperature",
        "default_retry_delay",
        mode="before",
    )
    @classmethod
    def empty_str_to_default_float(cls, v: Any, info: ValidationInfo) -> Any:
        """Convert empty strings to default value for float fields."""
        if v == "" or v is None:
            defaults = {
                "default_temperature": 0.2,
                "default_retry_delay": 1.0,
            }
            return defaults.get(info.field_name, v)
        return v

    @field_validator("default_provider", mode="before")
    @classmethod
    def empty_str_to_default_provider(cls, v: Any) -> Any:
        """Convert empty provider values to the default provider."""
        if v == "" or v is None:
            return "openrouter"
        return str(v).strip().lower()

    @field_validator("default_provider")
    @classmethod
    def validate_default_provider(cls, v: str) -> str:
        if v not in PROVIDERS:
            raise ValueError(f"default_provider must be one of: {', '.join(PROVIDERS)}")
        return v

    @field_validator("default_model", mode="before")
    @classmethod
    def empty_str_to_default_model(cls, v: Any) -> Any:
        """Convert empty strings to provider default model."""
        if v == "":
            return None
        return v

    @property
    def default_temperature_range(self) -> Tuple[float, float]:
        """Return temperature range as a tuple."""
        return (0.0, 2.0)

    class Config:
        env_prefix = "GIT_TOOLS_"
        env_file = _get_env_file_paths()
        extra = "ignore"


# Singleton instance for application-wide access
settings = GitToolsSettings()


class BaseLLMConfig(BaseSettings):
    """Base configuration for all LLM providers.

    Attributes:
        api_key: API key for the provider (loaded from environment)
        model: Model name to use (optional)
        max_tokens: Maximum tokens for completions (1-16384)
        temperature: Sampling temperature (0.0-2.0)
        max_retries: Maximum number of retry attempts
        retry_delay: Delay between retries in seconds
        base_url: Base URL for the API endpoint
    """

    api_key: str = Field(..., min_length=1)  # Required, not optional
    model: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_retries: Optional[int] = 1
    retry_delay: Optional[float] = 1.0
    base_url: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: Any, info: ValidationInfo) -> Any:
        """Convert empty strings to None for Optional fields.

        Args:
            v: Value to validate
            info: Validation context information

        Returns:
            None if value is empty string, otherwise the original value
        """
        if v == "":
            return None
        return v


class OpenRouterConfig(BaseLLMConfig):
    """Configuration for OpenRouter API provider."""

    api_key: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("OPENROUTER_API_KEY"),
    )
    base_url: Optional[str] = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "OPENROUTER_BASE_URL"),
    )

    class Config:
        env_file = _get_env_file_paths()
        extra = "ignore"


class KimiCLIConfig(BaseLLMConfig):
    """Configuration for the Kimi CLI-compatible endpoint."""

    api_key: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("MOONSHOT_API_KEY", "KIMICLI_API_KEY"),
    )
    base_url: Optional[str] = Field(
        default="https://api.kimi.com/coding/v1",
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "KIMICLI_BASE_URL"),
    )

    class Config:
        env_file = _get_env_file_paths()
        extra = "ignore"


def load_provider_config(provider: str) -> BaseLLMConfig:
    """Dynamically load configuration for a single provider.

    Args:
        provider: Provider name (e.g., 'openrouter')

    Returns:
        Configured provider configuration instance

    Raises:
        ValueError: If provider is unknown or config class is not whitelisted
    """
    provider_lower = provider.lower()
    if provider_lower not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")

    # Get config class name from mappings
    config_class_name = PROVIDERS[provider_lower]["config_class"]

    # Security: Validate against whitelist
    if config_class_name not in ALLOWED_CONFIG_CLASSES:
        raise ValueError(
            f"Config class '{config_class_name}' is not in whitelist. Allowed: {ALLOWED_CONFIG_CLASSES}"
        )

    # Get config class from current module's globals
    current_module = sys.modules[__name__]
    config_class = getattr(current_module, config_class_name, None)

    if config_class is None:
        raise ValueError(f"Config class '{config_class_name}' not found in module")

    # Load config (only API keys from .env, other settings from JSON)
    return config_class()

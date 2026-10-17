"""Configuration module for LLM provider settings.

This module provides Pydantic-based configuration classes for different LLM providers,
loading API keys from environment files and validating settings.
"""

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, DotEnvSettingsSource

from git_tools.providers import acrc, anthropic, cliproxyapi, copilot, kimi_code, openai, openrouter

from .mappings import PROVIDER_ALIASES, PROVIDERS

# Whitelist of allowed configuration classes for security
ALLOWED_CONFIG_CLASSES = {
    "OpenRouterConfig", "KimiCLIConfig", "CLIProxyAPIConfig",
    "ACRCConfig", "CopilotConfig", "QwenConfig",
    "OpenAIConfig", "AnthropicConfig",
}

# Providers whose API key is a fixed placeholder rather than a secret (local
# proxies). git-tools defaults these so the user need not set them: CLIProxyAPI
# ships with the client key "cliproxyapi". An explicit env/config value still
# overrides the default when the proxy is configured with a different key.
PROVIDER_DEFAULT_API_KEYS = {"cliproxyapi": "cliproxyapi"}

# Default settings file location. A single self-contained ~/.git-tools/ folder so a
# full reset is just `rm -rf ~/.git-tools`.
DEFAULT_SETTINGS_PATH = Path.home() / ".git-tools" / "settings.env"

# Pre-rename locations. The .git-tools location takes priority when both exist;
# develop used the XDG config directory before settings moved to .git-tools.
# Legacy files remain readable if migration fails (e.g. permissions).
LEGACY_SETTINGS_PATH = Path.home() / ".git-tools" / "config.env"
XDG_LEGACY_SETTINGS_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    / "git-tools"
    / "config.env"
)


def _migrate_legacy_settings_file() -> None:
    """Move the highest-priority legacy file without replacing existing settings."""
    if DEFAULT_SETTINGS_PATH.exists():
        return
    for legacy_path in (LEGACY_SETTINGS_PATH, XDG_LEGACY_SETTINGS_PATH):
        if legacy_path.exists():
            try:
                DEFAULT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.replace(DEFAULT_SETTINGS_PATH)
            except OSError:
                pass
            return


_migrate_legacy_settings_file()


def normalize_provider_name(provider: str) -> str:
    """Return the canonical provider key used by the PROVIDERS map.

    Agent-core/agent-cli provider spellings such as ``kimicode`` are accepted
    as aliases while existing git-tools settings keep their compatible key.
    """
    normalized = str(provider).strip().lower()
    return PROVIDER_ALIASES.get(normalized, normalized)


def _get_env_file_paths() -> list[Path]:
    """Get environment file search paths.

    Search order (last found wins in pydantic-settings):
    1. {cwd}/git-tools.env (local development, lowest priority)
    2. $XDG_CONFIG_HOME/git-tools/config.env (defaults to ~/.config/git-tools)
    3. ~/.git-tools/config.env (legacy, higher priority than XDG)
    4. ~/.git-tools/settings.env (user-global, highest priority)

    Both legacy locations are consulted only until settings.env exists.

    The legacy file is dropped from the list as soon as settings.env exists, so
    a stale config.env left behind by a failed migration can never shadow
    settings.env for first-match readers like check_api_key_configured.

    Environment variables (e.g., OPENROUTER_API_KEY) always take precedence.

    Returns:
        List of Path objects to search for env file
    """
    paths = [Path.cwd() / "git-tools.env"]
    if not DEFAULT_SETTINGS_PATH.exists():
        for legacy_path in (XDG_LEGACY_SETTINGS_PATH, LEGACY_SETTINGS_PATH):
            if legacy_path.exists():
                paths.append(legacy_path)
    paths.append(DEFAULT_SETTINGS_PATH)
    return paths


def _get_provider_definition(provider: str) -> dict[str, Any]:
    provider_lower = normalize_provider_name(provider)
    if provider_lower not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    return PROVIDERS[provider_lower]


def _get_provider_api_key_envs(provider: str) -> list[str]:
    provider_def = _get_provider_definition(provider)
    primary_env = provider_def.get("api_key_env")
    if not primary_env:
        raise ValueError(f"Provider '{provider}' must define api_key_env")
    return [primary_env]


def provider_label(provider: str) -> str:
    """Return the human-readable display name from provider metadata."""
    provider_lower = normalize_provider_name(provider)
    definition = PROVIDERS.get(provider_lower, {})
    return str(definition.get("label") or provider_lower.title())


def provider_base_url_env(provider: str) -> str:
    """The provider's own endpoint key (``OPENAI_BASE_URL``, ``QWEN_BASE_URL``, …).

    Every config class reads the shared ``GIT_TOOLS_API_BASE`` first and this
    key second; the settings editors use it to remember a custom endpoint per
    provider, the way agent-cli keeps a base URL per provider profile.
    """
    alias = _provider_config_class(provider).model_fields["base_url"].validation_alias
    choices = [str(choice) for choice in getattr(alias, "choices", [])]
    return next(choice for choice in choices if choice != "GIT_TOOLS_API_BASE")


def effective_value(*keys: str, default: str | None = None) -> tuple[str | None, str]:
    """Resolve aliases within each source, never across precedence levels.

    Return the value and a non-secret source description. Empty environment
    values and credentials are unset; designated file controls may be cleared.
    """
    from dotenv import dotenv_values

    environment = {key.upper(): value for key, value in os.environ.items()}
    for key in keys:
        if environment.get(key.upper()) not in (None, ""):
            return environment[key.upper()], f"environment: {key}"
    for path in reversed(_get_env_file_paths()):
        try:
            values = {key.upper(): value for key, value in dotenv_values(path).items()}
        except OSError:
            continue
        for key in keys:
            value = values.get(key.upper())
            if value is not None and (value != "" or key.upper() in _FILE_CLEAR_KEYS):
                location = "local env" if path == Path.cwd() / "git-tools.env" else "user settings"
                return value, f"{location}: {key}"
    return default, "provider default" if default is not None else "not configured"


def _saved_value(key: str) -> str | None:
    """Return one effective value using the shared source precedence."""
    return effective_value(key)[0]


def effective_provider_base_url(provider: str) -> tuple[str | None, str]:
    """Resolve an endpoint without constructing a credential-requiring config."""
    value, source = effective_value(
        "GIT_TOOLS_API_BASE", provider_base_url_env(provider),
        default=PROVIDERS[normalize_provider_name(provider)].get("default_base_url") or None,
    )
    return value or None, source


class _FileSettingsSource(DotEnvSettingsSource):
    """Keep explicit file clears only for provider/profile controls, never keys."""

    def _read_env_file(self, file_path: Path) -> dict[str, Any]:
        values = self._static_read_env_file(
            file_path, encoding=self.env_file_encoding, case_sensitive=self.case_sensitive,
            ignore_empty=False, parse_none_str=self.env_parse_none_str,
        )
        return {key: value for key, value in values.items()
                if value is not None and (value != "" or key.upper() in _FILE_CLEAR_KEYS)}


def _canonical_source(source: Any, settings_cls: type[BaseSettings]) -> Any:
    """Normalize alias keys before Pydantic merges sources.

    Otherwise a low-priority primary alias can beat a high-priority secondary
    alias (for example a saved shared endpoint versus OPENAI_BASE_URL in env).
    """
    def read() -> dict[str, Any]:
        data = source().copy()
        missing = object()
        for name, field in settings_cls.model_fields.items():
            alias = field.validation_alias
            keys = [alias] if isinstance(alias, str) else list(getattr(alias, "choices", []))
            if not keys:
                continue
            candidates = [*keys, name]
            found = next((data[key] for key in candidates if key in data), missing)
            for key in candidates:
                data.pop(key, None)
            if found is not missing:
                data[keys[0]] = found
        return data
    return read


_INITIAL_ENV_FILE_PATHS = _get_env_file_paths()


class EffectiveSettings(BaseSettings):
    """One source order for application and provider settings.

    Explicit constructor/CLI values > environment > user file > local file >
    defaults. Each file is a separate source so aliases obey that same order.
    """
    def __init__(self, **values: Any) -> None:
        configured_files = self.model_config.get("env_file")
        # Refresh normal paths (cwd, migration, editor saves), while honoring
        # caller model_config overrides and explicit _env_file, including None.
        values.setdefault("_env_file", _get_env_file_paths()
                          if configured_files == _INITIAL_ENV_FILE_PATHS else configured_files)
        super().__init__(**values)

    @classmethod
    def settings_customise_sources(cls, settings_cls: type[BaseSettings], init_settings: Any,
                                   env_settings: Any, dotenv_settings: Any,
                                   file_secret_settings: Any) -> tuple[Any, ...]:
        paths = dotenv_settings.env_file
        if isinstance(paths, (str, os.PathLike)):
            paths = [paths]
        files = [_FileSettingsSource(
            settings_cls, env_file=path, env_file_encoding=dotenv_settings.env_file_encoding,
            case_sensitive=dotenv_settings.case_sensitive, env_prefix=dotenv_settings.env_prefix,
            env_nested_delimiter=dotenv_settings.env_nested_delimiter,
            env_parse_none_str=dotenv_settings.env_parse_none_str,
            env_parse_enums=dotenv_settings.env_parse_enums,
        ) for path in reversed(paths or [])]
        return tuple(_canonical_source(source, settings_cls)
                     for source in (init_settings, env_settings, *files, file_secret_settings))

    model_config = {"populate_by_name": True, "env_ignore_empty": True}


def saved_provider_base_url(provider: str) -> str | None:
    """A custom endpoint remembered for ``provider``, from its own key."""
    value = (_saved_value(provider_base_url_env(provider)) or "").strip()
    return value or None


# Provider profiles. agent-cli keeps a profile per provider (model, support
# model, reasoning tier, Kimi thinking, OpenRouter pin, endpoint); git-tools
# keeps the same under provider-scoped keys. The plain keys always hold the
# current provider's values, so generators and config classes never change:
# every save of a plain key is mirrored into the current provider's profile
# (``save_settings``), and a provider switch reads the target provider's
# profile back into the plain keys. API keys are per provider already.
_PROFILE_FIELDS = {
    "GIT_TOOLS_MODEL_MAIN": "MODEL_MAIN",
    "GIT_TOOLS_DEFAULT_MODEL": "MODEL_MAIN",
    "GIT_TOOLS_MODEL_SUPPORT": "MODEL_SUPPORT",
    "GIT_TOOLS_REASONING_EFFORT": "REASONING_EFFORT",
    "GIT_TOOLS_KIMI_THINKING": "KIMI_THINKING",
    "GIT_TOOLS_OPENROUTER_PROVIDER": "OPENROUTER_PROVIDER",
}

# An assigned blank for these file controls is an explicit reset, not absence.
# Process-environment blanks and saved credentials still fall through normally.
_FILE_CLEAR_KEYS = {
    "GIT_TOOLS_API_BASE", "GIT_TOOLS_MODEL_SUB", *_PROFILE_FIELDS,
    *(f"{provider.upper()}_BASE_URL" for provider in PROVIDERS),
    *(f"GIT_TOOLS_{provider.upper()}_{field}"
      for provider in PROVIDERS for field in set(_PROFILE_FIELDS.values())),
}


def provider_profile_key(provider: str, field: str) -> str:
    """The provider-scoped key for one profile field (``GIT_TOOLS_OPENAI_MODEL_MAIN``)."""
    return f"GIT_TOOLS_{normalize_provider_name(provider).upper()}_{field}"


def saved_provider_profile(provider: str) -> dict[str, str | None]:
    """A provider's remembered choices; ``None`` for anything never saved."""
    return {
        "model": _saved_value(provider_profile_key(provider, "MODEL_MAIN")),
        "support_model": _saved_value(provider_profile_key(provider, "MODEL_SUPPORT")),
        "reasoning_effort": _saved_value(provider_profile_key(provider, "REASONING_EFFORT")),
        "kimi_thinking": _saved_value(provider_profile_key(provider, "KIMI_THINKING")),
        "openrouter_provider": _saved_value(provider_profile_key(provider, "OPENROUTER_PROVIDER")),
        "api_base": saved_provider_base_url(provider),
    }


def _mirror_profile(updates: dict[str, str | None]) -> dict[str, str | None]:
    """``updates`` plus their provider-profile mirrors for the provider they belong to.

    The provider is the one being switched to when the updates carry
    ``GIT_TOOLS_PROVIDER``, else the effective current one (including aliases
    and the implicit application default). A custom endpoint is
    mirrored under the provider's own endpoint key; the default endpoint is
    not, and setting it again forgets a remembered custom one.
    """
    provider = (updates.get("GIT_TOOLS_PROVIDER") or updates.get("GIT_TOOLS_DEFAULT_PROVIDER")
                or effective_value("GIT_TOOLS_PROVIDER", "GIT_TOOLS_DEFAULT_PROVIDER",
                                   default=GitToolsSettings.model_fields["default_provider"].default)[0])
    provider = normalize_provider_name(provider) if provider else ""
    if provider not in PROVIDERS:
        return dict(updates)
    mirrored: dict[str, str | None] = dict(updates)
    for key, value in updates.items():
        field = _PROFILE_FIELDS.get(key)
        if field:
            mirrored[provider_profile_key(provider, field)] = value
        elif key == "GIT_TOOLS_API_BASE" and value is not None:
            default = (PROVIDERS[provider].get("default_base_url") or "").rstrip("/")
            custom = value.rstrip("/") != default
            mirrored[provider_base_url_env(provider)] = value if custom else None
    return mirrored


def provider_api_key_env(provider: str) -> str:
    """Return the primary API-key environment variable for a provider."""
    return _get_provider_api_key_envs(provider)[0]


def check_api_key_configured(provider: str = "openrouter") -> tuple[bool, str | None]:
    """Check if API key is available without triggering validation error.

    Args:
        provider: Provider name (default: "openrouter")

    Returns:
        Tuple of (is_configured, key_value_or_none)
    """
    key, _source = effective_value(*_get_provider_api_key_envs(provider))
    if key:
        return True, key

    # Local-proxy providers ship a usable default key, so treat them as
    # configured even when nothing is set explicitly.
    if default_key := PROVIDER_DEFAULT_API_KEYS.get(normalize_provider_name(provider)):
        return True, default_key

    return False, None


def _render_settings_updates(content: str, updates: dict[str, str | None]) -> str:
    """Return settings file content with all updates applied in memory.

    A ``None`` value removes the key's line, so a setting can be forgotten
    rather than left behind as an empty string.
    """
    for key, value in updates.items():
        pattern = re.compile(rf'^{re.escape(key)}\s*=.*$', re.MULTILINE)
        if value is None:
            content = re.sub(rf'^{re.escape(key)}\s*=.*\n?', "", content, flags=re.MULTILINE)
            continue
        line = f'{key}="{value}"'
        if pattern.search(content):
            # A callable replacement keeps backslashes in values literal; a
            # string replacement would parse them as regex group references.
            content = pattern.sub(lambda _match, replacement=line: replacement, content)
        else:
            content = content.rstrip() + ("\n" if content.strip() else "") + line + "\n"
    return content


def save_settings(updates: dict[str, str | None]) -> bool:
    """Atomically apply multiple settings with a single file replacement.

    A ``None`` value removes that key from the file.
    """
    if not updates:
        return True

    DEFAULT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = DEFAULT_SETTINGS_PATH.read_text() if DEFAULT_SETTINGS_PATH.exists() else ""
    rendered = _render_settings_updates(content, _mirror_profile(updates))

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DEFAULT_SETTINGS_PATH.parent,
            prefix=f".{DEFAULT_SETTINGS_PATH.name}.",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(DEFAULT_SETTINGS_PATH)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return True


def save_setting(key: str, value: str) -> bool:
    """Save one setting atomically to the settings file."""
    return save_settings({key: value})


def setup_api_key(provider: str = "openrouter") -> bool:
    """Prompt user for API key and save to settings file.

    Args:
        provider: Provider name (default: "openrouter")

    Returns:
        True if key was saved successfully, False otherwise
    """
    from rich.prompt import Prompt

    env_var = _get_provider_api_key_envs(provider)[0]
    key = Prompt.ask(f"Enter your {provider_label(provider)} API key", password=True)

    if not key or not key.strip():
        return False

    return save_setting(env_var, key.strip())


class GitToolsSettings(EffectiveSettings):
    """Application-wide settings loaded from environment variables.

    All settings have sensible defaults and can be overridden via environment
    variables with the GIT_TOOLS_ prefix. Empty exports are unset; saved
    provider/profile controls can use an assigned blank to clear an override.

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

    def __init__(self, **values: Any) -> None:
        main_keys = ("main_model", "GIT_TOOLS_MODEL_MAIN", "GIT_TOOLS_DEFAULT_MODEL")
        if "default_model" in values and not any(key in values for key in main_keys):
            values["main_model"] = values["default_model"]
        super().__init__(**values)
        if "main_model" in self.model_fields_set and self.main_model is None:
            # A main-model clear/null must not revive the separate legacy field.
            self.default_model = None

    # LLM defaults
    default_provider: str = Field(
        default="openrouter",
        validation_alias=AliasChoices("GIT_TOOLS_PROVIDER", "GIT_TOOLS_DEFAULT_PROVIDER"),
    )
    default_model: Optional[str] = Field(default=None)
    main_model: Optional[str] = Field(default=None, validation_alias=AliasChoices(
        "GIT_TOOLS_MODEL_MAIN", "GIT_TOOLS_DEFAULT_MODEL"))
    support_model: str = Field(default="follow-main", validation_alias=AliasChoices(
        "GIT_TOOLS_MODEL_SUPPORT", "GIT_TOOLS_MODEL_SUB"))
    openrouter_provider: Optional[str] = Field(default=None)
    kimi_thinking: Optional[bool] = Field(default=None)

    @field_validator("kimi_thinking", mode="before")
    @classmethod
    def empty_thinking_is_unset(cls, value: Any) -> Any:
        return None if value == "" else value
    default_reasoning_effort: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("GIT_TOOLS_REASONING_EFFORT"),
    )
    default_temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=32000, ge=1)
    default_max_retries: int = Field(default=1, ge=0)
    default_retry_delay: float = Field(default=1.0, ge=0.0)

    # Azure PR preferences (global; auto detects each repository's origin).
    azure_pr_limit: str = Field(default="auto")
    azure_pr_max_chars: int = Field(default=4000, ge=1, le=4000)

    @field_validator("azure_pr_limit", mode="before")
    @classmethod
    def validate_azure_pr_limit(cls, value: Any) -> str:
        mode = str(value).strip().lower() if value not in (None, "") else "auto"
        if mode not in {"auto", "false"}:
            raise ValueError("azure_pr_limit must be auto or false")
        return mode

    # Saved generation preferences; explicit command flags override these.
    commit_include_scope: bool = Field(default=False)
    commit_include_body: bool = Field(default=True)
    commit_body_style: Literal["bullets", "prose"] = Field(default="bullets")
    commit_include_footer: bool = Field(default=False)
    issue_pr_source: str = Field(default="b")

    @field_validator("issue_pr_source", mode="before")
    @classmethod
    def validate_issue_pr_source(cls, value: Any) -> str:
        # Keep the documented generator fallback for invalid source values.
        source = str(value or "b").strip().lower()
        return source if source in {"c", "d", "b"} else "b"

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
        "azure_pr_max_chars",
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
        """Convert empty strings to the field default for int fields."""
        if v == "" or v is None:
            return cls.model_fields[info.field_name].default
        return v

    @field_validator(
        "default_temperature",
        "default_retry_delay",
        mode="before",
    )
    @classmethod
    def empty_str_to_default_float(cls, v: Any, info: ValidationInfo) -> Any:
        """Convert empty strings to the field default for float fields."""
        if v == "" or v is None:
            return cls.model_fields[info.field_name].default
        return v

    @field_validator("default_provider", mode="before")
    @classmethod
    def empty_str_to_default_provider(cls, v: Any) -> Any:
        """Convert empty provider values to the default provider."""
        if v == "" or v is None:
            return cls.model_fields["default_provider"].default
        return normalize_provider_name(str(v))

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

    @field_validator("default_reasoning_effort", mode="before")
    @classmethod
    def normalize_reasoning_effort(cls, v: Any) -> Any:
        """Treat empty strings as unset and normalize casing (e.g. 'xhigh')."""
        if v is None or v == "":
            return None
        return str(v).strip().lower() or None

    @field_validator("main_model", "support_model", "openrouter_provider", mode="before")
    @classmethod
    def normalize_model_choice(cls, value: Any, info: ValidationInfo) -> Any:
        if isinstance(value, str):
            value = value.strip()
        return value or ("follow-main" if info.field_name == "support_model" else None)

    @property
    def effective_main_model(self) -> Optional[str]:
        return self.main_model or self.default_model

    @property
    def default_temperature_range(self) -> Tuple[float, float]:
        """Return temperature range as a tuple."""
        return (0.0, 2.0)

    class Config:
        env_prefix = "GIT_TOOLS_"
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


# Singleton instance for application-wide access
settings = GitToolsSettings()


def reload_settings() -> None:
    """Re-read the settings files into the module-level singleton.

    The interactive menu can edit settings and then run a content command in
    the same process; generators read this singleton, so it must be refreshed
    in place after the settings detour.
    """
    settings.__dict__.update(GitToolsSettings().__dict__)


class BaseLLMConfig(EffectiveSettings):
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
        validation_alias="OPENROUTER_API_KEY",
    )
    base_url: Optional[str] = Field(
        default=openrouter.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "OPENROUTER_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class KimiCLIConfig(BaseLLMConfig):
    """Configuration for the Kimi CLI-compatible endpoint."""

    api_key: str = Field(
        ...,
        min_length=1,
        validation_alias="KIMICODE_API_KEY",
    )
    base_url: Optional[str] = Field(
        default=kimi_code.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "KIMICLI_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class CLIProxyAPIConfig(BaseLLMConfig):
    """Configuration for the CLIProxyAPI OpenAI-compatible endpoint.

    CLIProxyAPI (https://github.com/router-for-me/CLIProxyAPI) exposes a local
    OpenAI-compatible proxy in front of CLI-authenticated models such as the
    Codex/GPT-5 family. Because git-tools runs on the host, the default base URL
    is the loopback address agent-cli presets; override it with GIT_TOOLS_API_BASE
    if the proxy lives elsewhere (e.g. http://host.docker.internal:8317/v1 from
    inside a container).

    The client key defaults to the ``cliproxyapi`` placeholder the proxy ships
    with, so it need not be set; override CLIPROXYAPI_API_KEY only if the proxy
    was configured with a different key.
    """

    api_key: str = Field(
        default=PROVIDER_DEFAULT_API_KEYS["cliproxyapi"],
        min_length=1,
        validation_alias="CLIPROXYAPI_API_KEY",
    )
    base_url: Optional[str] = Field(
        default=cliproxyapi.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "CLIPROXYAPI_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class ACRCConfig(BaseLLMConfig):
    """ACRC's OpenAI-compatible endpoint."""

    api_key: str = Field(..., min_length=1, validation_alias="ACRC_API_KEY")
    base_url: Optional[str] = Field(
        default=acrc.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "ACRC_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class CopilotConfig(BaseLLMConfig):
    """A separately running OpenAI-compatible Copilot proxy."""

    api_key: str = Field(..., min_length=1, validation_alias="COPILOT_API_KEY")
    base_url: Optional[str] = Field(
        default=copilot.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "COPILOT_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class QwenConfig(BaseLLMConfig):
    """DashScope requires the account's explicit plan/region endpoint."""

    api_key: str = Field(..., min_length=1, validation_alias="DASHSCOPE_API_KEY")
    base_url: str = Field(..., min_length=1, validation_alias=AliasChoices(
        "GIT_TOOLS_API_BASE", "QWEN_BASE_URL"))

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        from urllib.parse import urlsplit

        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Qwen requires an explicit HTTP(S) API base URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("API base URL must not contain credentials, query, or fragment")
        return value

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class OpenAIConfig(BaseLLMConfig):
    """OpenAI's own platform, spoken as chat completions."""

    api_key: str = Field(..., min_length=1, validation_alias="OPENAI_API_KEY")
    base_url: Optional[str] = Field(
        default=openai.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "OPENAI_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
        extra = "ignore"


class AnthropicConfig(BaseLLMConfig):
    """Anthropic through its OpenAI-compatible chat completions endpoint."""

    api_key: str = Field(..., min_length=1, validation_alias="ANTHROPIC_API_KEY")
    base_url: Optional[str] = Field(
        default=anthropic.BASE_URL,
        validation_alias=AliasChoices("GIT_TOOLS_API_BASE", "ANTHROPIC_BASE_URL"),
    )

    class Config:
        env_file = _INITIAL_ENV_FILE_PATHS
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
    # Load config (only API keys from .env, other settings from JSON)
    return _provider_config_class(provider)()


def _provider_config_class(provider: str) -> type[BaseLLMConfig]:
    """The whitelisted config class registered for ``provider``."""
    provider_lower = normalize_provider_name(provider)
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
    return config_class

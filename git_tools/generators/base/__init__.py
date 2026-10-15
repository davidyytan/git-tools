"""Shared generator infrastructure.

Console styling, prompt templates, model selection, LangChain clients, diff
budgeting, and the ``BaseGenerator`` that composes them for every generator.

Importing this package requires Rich, Questionary, and tiktoken. The bump
engine guards its import so CI can run from a bare checkout without them.
"""

from .terminal import (
    ALIGN_PANEL,
    STYLE_BORDER,
    STYLE_DIM,
    STYLE_ERROR,
    STYLE_PRIMARY,
    STYLE_SUCCESS,
    STYLE_WARNING,
    TYPER_STYLE,
    Panel,
    console,
    error,
    info,
    print_panel,
    success,
    warning,
    fmt_current,
    fmt_dim,
    fmt_ok,
    fmt_primary,
    fmt_warn,
    plain_title,
    styled,
)
from .generator import BaseGenerator
from .openrouter import _get_openrouter_extra_body, _sanitize_openrouter_provider_config
from .prompts import PROMPTS_DIR
from .tokens import count_tokens

__all__ = [
    "ALIGN_PANEL",
    "BaseGenerator",
    "fmt_current",
    "fmt_dim",
    "fmt_ok",
    "fmt_primary",
    "fmt_warn",
    "plain_title",
    "styled",
    "PROMPTS_DIR",
    "Panel",
    "STYLE_BORDER",
    "STYLE_DIM",
    "STYLE_ERROR",
    "STYLE_PRIMARY",
    "STYLE_SUCCESS",
    "STYLE_WARNING",
    "TYPER_STYLE",
    "console",
    "count_tokens",
    "error",
    "info",
    "print_panel",
    "success",
    "warning",
]

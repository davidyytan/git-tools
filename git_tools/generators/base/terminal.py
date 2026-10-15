"""Shared Rich console, Typer-matched styling, and status-message helpers."""

from questionary import Style
from rich.console import Console
from rich.panel import Panel

from git_tools.settings.settings import settings

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

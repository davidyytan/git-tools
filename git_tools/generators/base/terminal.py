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
STYLE_SUCCESS = "bold green"  # agent-cli marks done/current in green
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


# Prompt palette, after agent-cli's: bold cyan for the primary name, grey for
# details and hints, green for what is current or done, yellow for attention.
# Note: prompt_toolkit uses "ansicyan" not "cyan", and "noreverse" prevents a
# filled background on the highlighted row.
TYPER_STYLE = Style([
    ("qmark", "bold ansicyan"),
    ("question", "bold"),
    ("answer", "bold ansicyan"),
    ("pointer", "bold ansicyan"),
    ("highlighted", "bold ansicyan noreverse"),
    ("selected", "noreverse"),  # No cyan - we reorder choices instead of using questionary's default
    ("instruction", "ansibrightblack"),
    ("text", ""),
    ("disabled", "ansibrightblack"),
    ("search_success", "ansigreen"),
    ("search_none", "ansired"),
    # Parts of a styled menu row (see ``styled``).
    ("primary", "bold ansicyan"),
    ("dim", "ansibrightblack"),
    ("current", "bold ansigreen"),
    ("ok", "ansigreen"),
    ("warn", "ansiyellow"),
])

# A menu row is prompt_toolkit formatted text, one (style, text) pair per
# part, so a label, its value and a "(current)" marker can each carry their
# own colour. questionary renders such rows verbatim but cannot search them,
# so lists that use its type-to-filter keep plain string titles.
StyledPart = tuple[str, str]
StyledTitle = list[StyledPart]


def fmt_primary(text: object) -> StyledPart:
    """The row's main name or value: bold cyan."""
    return ("class:primary", str(text))


def fmt_dim(text: object) -> StyledPart:
    """Secondary detail: grey."""
    return ("class:dim", str(text))


def fmt_current(text: object = " (current)") -> StyledPart:
    """What is in force right now: bold green."""
    return ("class:current", str(text))


def fmt_ok(text: object) -> StyledPart:
    """A good state, such as a configured key: green."""
    return ("class:ok", str(text))


def fmt_warn(text: object) -> StyledPart:
    """Something needing attention, such as a missing key: yellow."""
    return ("class:warn", str(text))


def styled(*parts: StyledPart | str) -> StyledTitle:
    """Assemble a menu row from styled parts; bare strings stay unstyled."""
    return [part if isinstance(part, tuple) else ("class:text", str(part)) for part in parts]


def plain_title(title: object) -> str:
    """The text of a menu row whether it is styled or a plain string."""
    if isinstance(title, str):
        return title
    return "".join(text for _, text in title)

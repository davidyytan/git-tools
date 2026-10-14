# Git-Tools Style Guide

This guide covers contributor-facing console conventions. For CLI commands and interactive navigation, see [Usage](usage.md); for development setup, see [Contributing](contributing.md).

## Console Width

Use the shared console in [git_tools/generators/base.py](../git_tools/generators/base.py). It detects terminal width and applies `settings.console_width_offset` (default: `-2`) to avoid border wrapping on some terminals. [git_tools/cli.py](../git_tools/cli.py) applies the same offset to Typer's help output.

- `force_terminal=True` forces terminal-style rendering, including in non-interactive output; it does not detect whether input is interactive.
- `soft_wrap=True` prevents trailing spaces from creating phantom lines.
- Configure the offset with `GIT_TOOLS_CONSOLE_WIDTH_OFFSET`.

Do not create independent consoles with different width or color behavior for new generators.

## Panel and Message Styling

Reuse the constants and helpers from `git_tools/generators/base.py`:

```python
STYLE_BORDER = "dim"
ALIGN_PANEL = "left"
STYLE_PRIMARY = "bold cyan"
STYLE_SUCCESS = "bold cyan"
STYLE_WARNING = "yellow"
STYLE_ERROR = "red"
STYLE_DIM = "dim"
```

Use `print_panel` for left-aligned panels with a dim border, and `info`, `success`, `warning`, and `error` for status messages. Escape user-supplied text before embedding it in Rich markup.

Questionary prompts use the shared `TYPER_STYLE`. Keep new prompts consistent with it rather than defining a separate theme.

## Spacing Rules

**Core principle:** Elements print only themselves. The calling workflow owns spacing between different element types.

- Panels and text helpers should not add leading or trailing blank lines.
- Consecutive panels stack directly, without blank lines.
- Consecutive questions do not need blank lines.
- Add a blank line when transitioning between questions, panels, and text.
- Add a blank line before a spinner or progress display. A transient spinner disappears, so do not add an extra blank line before the panel that replaces it.
- Add a blank line before a final success message after progress or Git command output.
- In non-interactive CLI commands, add a leading blank line before the first output to separate it from the shell command. Interactive prompts already provide that separation.

```python
user_input = prompt_text("Enter value")
console.print()                  # Question → panel
print_panel("First panel")
print_panel("Second panel")      # Panel → panel: no blank line
console.print()                  # Panel → question
next_input = prompt_text("Next value")
```

Clipboard helpers may already handle their own success-message spacing. Check the helper before adding another blank line at its call site.

## Interactive vs Non-Interactive

Running `git-tools` without a command opens the interactive menu when a terminal is available. Explicit commands use CLI options and defaults unless interactive behavior is requested. Pass `interactive=True` when invoking generator commands from the main menu.

Use the existing navigation helpers for nested menus: **Back** or **Esc** returns one level, and **Ctrl+C** exits. Do not infer input interactivity from Rich's `force_terminal` setting.

## Reviewing Output Changes

Check both direct CLI invocation and the interactive menu when changing console output. Verify panel alignment, long-line wrapping, adjacent panels, prompt transitions, clipboard success messages, and error paths. Keep examples focused on layout rather than copying full transcripts with provider names, model defaults, or prompt sequences that can drift from the implementation.

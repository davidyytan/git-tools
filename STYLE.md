# Git-Tools Style Guide

## Console Width

Auto-detect terminal width and apply configurable offset to prevent border wrapping on some terminals (Rich issue #7).

```python
# base.py
_auto_width = Console(force_terminal=True).width
_width_offset = settings.console_width_offset  # default: -2
console = Console(soft_wrap=True, force_terminal=True, width=_auto_width + _width_offset if _auto_width else None)

# cli.py
_typer_width = Console(force_terminal=True).width
_width_offset = settings.console_width_offset
typer.rich_utils.MAX_WIDTH = _typer_width + _width_offset if _typer_width else 80
```

- `force_terminal=True` ensures consistent TTY detection across interactive and non-interactive modes
- `soft_wrap=True` prevents trailing spaces from creating phantom lines
- `console_width_offset` (default: -2) fixes off-by-one terminal width issue
- Configurable via `GIT_TOOLS_CONSOLE_WIDTH_OFFSET` environment variable

## Panel Styling

All panels use consistent styling from `base.py`:

```python
STYLE_BORDER = "dim"
ALIGN_PANEL = "left"
```

## Message Styling

```python
STYLE_PRIMARY = "bold cyan"   # Primary info, branch names
STYLE_SUCCESS = "bold cyan"   # Success messages (✓)
STYLE_WARNING = "yellow"      # Warnings
STYLE_ERROR = "red"           # Errors
STYLE_DIM = "dim"             # Secondary info, metadata
```

## Spacing Rules

**Core principle:** Elements print only themselves. Blank lines separate different element types, not consecutive elements of the same type.

### Element Spacing

- Elements (panels, display functions) print only their content
- Elements do NOT add `console.print()` before or after
- Text helpers (`info`, `success`, `warning`, `error`) print only their message
- Consecutive panels stack directly with NO blank lines between them

```python
# Panel elements - no spacing
def print_panel(content):
    console.print(Panel(content))  # ✅ Just the panel, no blank lines

def display_token_usage(...):
    console.print(Panel(...))      # ✅ Just the panel, no blank lines

# Text helpers - no spacing
def info(message):
    console.print(f"• {message}")  # ✅ Just the message, no blank lines
```

### Workflow Responsibility

Workflow adds blank lines only when transitioning between element types:

```python
# Prompt → Panel: add blank line
user_input = prompt_text("Enter value")
console.print()                  # Blank line before panels
print_panel("First panel")       # Panel prints itself only
print_panel("Second panel")      # NO blank line between panels
console.print()                  # Blank line after panels
# Panel → Prompt: add blank line
next_input = prompt_text("Next value")
```

### Special Elements

Spinners, progress bars, and success messages are special elements with specific spacing rules:

```python
# Spinner - workflow adds blank line before, spinner disappears when done
console.print()                          # Workflow adds blank line before
response = invoke_llm(messages)          # Spinner element (no internal spacing)
# No console.print() after - spinner disappears, next element appears in its place

# Progress bar - blank line before
console.print(f"Output: {output_path}")
console.print()                          # Blank line before progress
with Progress(...) as progress:
    ...

# Success message - blank line before
doc.save(output_path)
console.print()                          # Blank line before success
success(f"Created: {output_path}")
```

### Transition Summary

| From | To | Spacing |
|------|----|---------|
| Questionary | Panel | `console.print()` |
| Panel | Panel | None |
| Panel | Questionary | `console.print()` |
| Text | Panel | `console.print()` |
| Panel | Text | `console.print()` |
| Questionary | Text | `console.print()` |
| Text | Questionary | `console.print()` |
| Panel | Spinner | `console.print()` |
| Questionary | Spinner | `console.print()` |
| Spinner | Panel | None (spinner disappears) |
| Text | Progress | `console.print()` |
| Progress | Success | `console.print()` |

## Interactive vs Non-Interactive

- `git-tools` (no command) → Interactive mode via menu
- `git-tools commit` → Non-interactive, uses defaults
- `git-tools commit --scope` → Non-interactive, overrides specific defaults

Pass `interactive=True` when invoking commands from the main menu.

### CLI Output Spacing

In CLI (non-interactive) mode, add a leading blank line before output to separate from the command:

```python
# CLI command - add blank line before first output
console.print()                          # Separates command from output
console.print(f"Input:  {input_path}")
console.print(f"Pages:  {pages}")
...
```

This creates cleaner terminal output:

```
$ pdf-tools info document.pdf

• File:   document.pdf
• Size:   4.7 MB
• Pages:  260

✓ PDF info: document.pdf
```

Interactive mode (via menu) does not need this leading blank line since prompts already provide visual separation.

## Console Flow Reference

### commitgen - CLI Commit Path
```
$ git-tools commit
                                    <- CLI leading blank line
┌─ File Quota ─────────────────┐
│ ...                          │    <- Panel (quota)
└──────────────────────────────┘
⠋ Generating response from LLM...   <- Spinner (no spacing - disappears, leaving Panel → Panel)
┌─ Reasoning ──────────────────┐
│ ...                          │    <- Panel (if reasoning)
└──────────────────────────────┘
┌─ Raw Response ───────────────┐
│ ...                          │    <- Panel (no spacing between panels)
└──────────────────────────────┘
┌─ Commit Message ─────────────┐
│ ...                          │    <- Panel
└──────────────────────────────┘
┌─ Token Usage ────────────────┐
│ ...                          │    <- Panel
└──────────────────────────────┘
                                    <- Panel → Text
[main abc1234] commit message       <- git output (text)
                                    <- Text → Success
✓ Committed changes.                <- Success
```

### commitgen - CLI Clipboard Path (--no-commit)
```
$ git-tools commit --no-commit
                                    <- CLI leading blank line
┌─ File Quota ─────────────────┐
│ ...                          │
└──────────────────────────────┘
⠋ Generating response from LLM...   <- Spinner (no spacing - disappears, leaving Panel → Panel)
┌─ Reasoning ──────────────────┐
│ ...                          │    <- Panels stack directly
└──────────────────────────────┘
┌─ Token Usage ────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Success (internal in copy_to_clipboard_auto)
✓ Copied to clipboard!
```

### commitgen - Interactive Commit Path
```
❯ Select model: claude-sonnet       <- Questionary (model params)
❯ Enter temperature: 0.5
❯ Enter max tokens: 8192
                                    <- Questionary → Spinner
⠋ Generating response from LLM...   <- Spinner (animates, then disappears)
┌─ Reasoning ──────────────────┐
│ ...                          │
└──────────────────────────────┘
┌─ Token Usage ────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Questionary
❯ Commit changes directly?: Yes
                                    <- Questionary → Text
[main abc1234] commit message
                                    <- Text → Success
✓ Committed changes.
```

### commitgen - Interactive Clipboard Path
```
...
┌─ Token Usage ────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Questionary
❯ Commit changes directly?: No
❯ Copy to clipboard?: Yes           <- Questionary → Questionary (no spacing)
                                    <- Questionary → Success (internal in ask_to_copy)
✓ Copied to clipboard!
```

### issueprgen - CLI Path
```
$ git-tools issue
                                    <- CLI leading blank line
┌─ Commit Range Summary ───────┐
│ ...                          │    <- Panel
└──────────────────────────────┘
┌─ File Quota ─────────────────┐
│ ...                          │    <- Panel (no spacing between panels)
└──────────────────────────────┘
⠋ Generating response from LLM...   <- Spinner (no spacing - disappears, leaving Panel → Panel)
┌─ Reasoning ──────────────────┐
│ ...                          │
└──────────────────────────────┘
┌─ Token Usage ────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Success (internal in copy_to_clipboard_auto)
✓ Copied to clipboard!
```

### issueprgen - Interactive Path
```
❯ Enter base branch: develop        <- Questionary
                                    <- Questionary → Panel
┌─ Commit Range Summary ───────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Questionary
❯ Select content to generate: PR
❯ Select input source: Both         <- Questionary → Questionary (no spacing)
❯ Enter max token count: 8000
                                    <- Questionary → Panel
┌─ File Quota ─────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Questionary
❯ Add additional context?: No
❯ Generate using external?: Yes
❯ Select model: claude-sonnet
...
                                    <- Questionary → Spinner
⠋ Generating response from LLM...   <- Spinner (animates, then disappears)
┌─ Reasoning ──────────────────┐
│ ...                          │
└──────────────────────────────┘
┌─ Token Usage ────────────────┐
│ ...                          │
└──────────────────────────────┘
                                    <- Panel → Questionary
❯ Copy to clipboard?: Yes
                                    <- Questionary → Success
✓ Copied to clipboard!
```

### config - Interactive Settings
```
❯ Select setting to edit:           <- Questionary (select)
  API Key: configured
  Model: moonshotai/kimi-k2-thinking
  Temperature: 0.2
  Max Tokens: 8000
  Max Retries: 1
› Done
❯ Temperature                       <- User selects temperature
❯ Temperature (current: 0.2, ...):  <- Questionary → Questionary (no spacing)
  0.5
                                    <- Questionary → Success
✓ Temperature set to 0.5
                                    <- Success → Questionary
❯ Select setting to edit:           <- Next iteration
  ...
› Done
```

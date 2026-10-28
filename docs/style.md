# Git-Tools Style Guide

This guide covers contributor-facing console conventions. For CLI commands and interactive navigation, see [Usage](usage.md); for development setup, see [Contributing](contributing.md); for where code lives, see [Code layout](architecture.md).

## Markdown Source Formatting

Do not hard-wrap Markdown prose. Keep each paragraph on one source line, regardless of length, and use editor soft wrapping for readability. Keep each list item's prose paragraph on one source line too; retain line breaks only where Markdown structure or code examples require them (headings, separate list items, tables, and code blocks). Do not add forced prose line breaks with trailing spaces, backslashes, or `<br>` tags. Apply the same rule to plain-text documentation and prose comments in workflows and configuration examples. Keep shell commands on one source line unless line breaks are syntactically required, as with heredocs or control flow.

## User-Facing Guides

- Lead with the reader's common task. Existing-key retrieval comes before optional key creation; existing projects must not be sent through fresh-repository bootstrap.
- Keep a short command group **in each standalone guide and copyable workflow example** where readers need it. Repeating three useful commands is better than making readers follow several links.
- Put the exact secret/variable name and its settings destination beside the command that produces its value. Distinguish private-secret storage from public-key registration.
- State where commands run, what placeholders to replace, and what result to check. Do not assume a working directory survives a shell restart.
- Use the reader's own human identity, automation identity, and application repository. Label the upstream tool-source URL separately.
- Avoid extra private-key export files when CI accepts pasted text. Keep important warnings at the relevant step; place advanced policy after the main path.
- Consolidate overlapping explanations, not necessary steps. A beginner should have a complete process, and a returning reader should be able to enter in the middle.

## Console Width

Use the shared console in [git_tools/generators/base/terminal.py](../git_tools/generators/base/terminal.py). It detects terminal width and applies `settings.console_width_offset` (default: `-2`) to avoid border wrapping on some terminals. [git_tools/cli.py](../git_tools/cli.py) applies the same offset to Typer's help output.

- `force_terminal=True` forces terminal-style rendering, including in non-interactive output; it does not detect whether input is interactive.
- The shared console uses `soft_wrap=True` for text. Panel renderers explicitly pass `soft_wrap=False` so borders and long content wrap within the available width.
- Configure the offset with `GIT_TOOLS_CONSOLE_WIDTH_OFFSET`.

Do not create independent consoles with different width or color behavior for new generators.

## Panel and Message Styling

Reuse the constants and helpers from `git_tools/generators/base/terminal.py` (re-exported by `git_tools.generators.base`):

```python
STYLE_BORDER = "dim"
ALIGN_PANEL = "left"
STYLE_PRIMARY = "bold cyan"
STYLE_SUCCESS = "bold green"
STYLE_WARNING = "yellow"
STYLE_ERROR = "red"
STYLE_DIM = "dim"
```

Use `print_panel` for left-aligned panels with a dim border, and `info`, `success`, `warning`, and `error` for status messages. Escape user-supplied text before embedding it in Rich markup.

Questionary prompts use the shared `TYPER_STYLE`. Keep new prompts consistent with it rather than defining a separate theme.

## Spacing Rules

**Core principle:** Every rendered panel owns exactly one trailing blank separator line. The calling workflow owns transitions after question answers and plain text; do not add a second separator after a panel.

- `print_panel` and the quota, reasoning, usage, generated-output, and local-prompt panel renderers leave one blank line after each panel, including the final panel.
- Consecutive panels have one blank line between them, not zero or two.
- Status-text helpers do not add their own blank lines. Consecutive questions need no extra separation.
- Add one blank line after a question answer or plain-text section before the next panel, status section, or action. A preceding panel already provides that gap.
- Separate Git command output from the final success message with one blank line. Do not add another leading blank line merely because the command was invoked directly.
- Optional diagnostic panels that have no content emit nothing, including no separator.

```python
user_input = prompt_text("Enter value")
console.print()                  # Question → panel
print_panel("First panel")       # Owns its trailing separator
print_panel("Second panel")      # No caller-added blank line
next_input = prompt_text("Next value")  # Previous panel already separates it
```

Clipboard helpers also manage prompt/result spacing. After a panel, use `handoff_to_clipboard(..., leading_space=False)` or the corresponding automatic-copy argument to avoid doubling the panel's separator. Check each helper before adding whitespace at its call site.

## Interactive vs Non-Interactive

Running `git-tools` without a command opens the interactive menu only when both stdin and stdout are terminals; otherwise it prints help. Direct generation commands use CLI options and saved defaults unless `--interactive` is requested. Bare `settings` requires an interactive terminal; direct `init` prompts only with `--interactive`, and `--defaults` suppresses those prompts. Pass `interactive=True` when invoking generator commands from the main menu.

Use `_ask_with_back` and the existing **Back** choice for nested settings menus: **Back** or **Esc** returns one level, and **Ctrl+C** exits the command. Generator prompt cancellation aborts the operation rather than accepting a default; not every generator prompt has settings-style Back navigation. Do not infer input interactivity from Rich's `force_terminal` setting.

## Reviewing Output Changes

Use `tests/test_cli_spacing.py` and `tests/test_generation_spacing.py` for mocked narrow/wide rendering checks. Also check both direct CLI invocation and the interactive menu in a controlled test environment when changing console output. Verify panel alignment, long-line wrapping, adjacent panels, prompt transitions, clipboard success messages, and error paths. Keep examples focused on layout rather than copying full transcripts with provider names, model defaults, or prompt sequences that can drift from the implementation.

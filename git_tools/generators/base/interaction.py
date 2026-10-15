"""Questionary prompts and clipboard handoff shared by all generators."""

from typing import List, Optional

import questionary

from .terminal import TYPER_STYLE, console, error, success, warning


class InteractionMixin:
    """Prompt helpers styled to match Typer, plus clipboard output."""

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

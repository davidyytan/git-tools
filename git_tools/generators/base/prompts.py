"""Prompt-template loading for generators (files under ``git_tools/prompts``)."""

from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


class PromptTemplateMixin:
    """Load and render prompt templates by file name."""

    def _load_prompt_template(self, filename: str) -> str:
        """Load prompt template from file.

        Args:
            filename: Name of the prompt file (e.g., 'commitgen_prompt.txt')

        Returns:
            Contents of the prompt file
        """
        try:
            with open(PROMPTS_DIR / filename, "r") as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to load prompt template {filename}: {str(e)}")
            raise e

    def _render_prompt_template(self, filename: str, **kwargs: Any) -> str:
        """Load and optionally format a prompt template from file."""
        template = self._load_prompt_template(filename)
        return template.format(**kwargs) if kwargs else template

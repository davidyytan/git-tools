"""Template management module.

Provides functions to load and access templates for commit messages,
pull requests, and issues. Templates are loaded lazily with proper error handling.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Templates directory
TEMPLATES_DIR = Path(__file__).parent

# Template cache
_template_cache = {}


def _load_template(template_name: str) -> str:
    """Load a template file with error handling.

    Args:
        template_name: Name of the template file (e.g., 'pr_template.txt')

    Returns:
        Template content as string

    Raises:
        FileNotFoundError: If template file doesn't exist
        IOError: If template file cannot be read
    """
    if template_name in _template_cache:
        return _template_cache[template_name]

    template_path = TEMPLATES_DIR / template_name

    if not template_path.exists():
        raise FileNotFoundError(
            f"Template file not found: {template_path}\n"
            f"Expected location: {template_path.absolute()}\n"
            "Please ensure the template files are properly installed."
        )

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read()
        _template_cache[template_name] = content
        logger.debug(f"Loaded template: {template_name}")
        return content
    except IOError as e:
        raise IOError(f"Failed to read template {template_path}: {e}") from e


def get_pr_template() -> str:
    """Get the pull request template.

    Returns:
        PR template content
    """
    return _load_template("pr_template.txt")


def get_commit_template() -> str:
    """Get the commit message template.

    Returns:
        Commit template content
    """
    return _load_template("commit_template.txt")


def get_issue_template() -> str:
    """Get the issue template.

    Returns:
        Issue template content
    """
    return _load_template("issue_template.txt")



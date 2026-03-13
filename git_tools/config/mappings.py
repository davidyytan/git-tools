"""Mappings configuration loader.

Source of truth:
1. mappings.json
2. mappings.json.example

Interactive config writes user overrides to config.env, not to these JSON files.
"""

import json
from pathlib import Path
from typing import Any, Dict

import typer


def _load_mappings_file(path: Path) -> Dict[str, Any]:
    with open(path, "r") as f:
        config = json.load(f)
    return config["providers"]


def _load_mappings() -> Dict[str, Any]:
    """Load mappings from JSON configuration files."""
    # Find the root directory (where main.py or mappings.json would be)
    current_file = Path(__file__)

    # Go up from git-tools/git_tools/config/mappings.py to the repo root
    root_dir = current_file.parent.parent.parent
    mappings_file = root_dir / "mappings.json"
    mappings_example_file = root_dir / "mappings.json.example"

    for path in (mappings_file, mappings_example_file):
        if not path.exists():
            continue
        try:
            return _load_mappings_file(path)
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            typer.echo(
                typer.style(
                    f"Warning: Error loading {path.name}: {e}", fg=typer.colors.YELLOW
                )
            )

    raise RuntimeError(
        "No valid mappings configuration found. Expected mappings.json or mappings.json.example."
    )


# Load the mappings
PROVIDERS = _load_mappings()

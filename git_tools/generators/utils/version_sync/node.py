"""Node/npm version-field syncing, without dependency or workspace changes."""

import json
import re
from typing import Callable


def sync_npm_versions(
    text: str, new_version: str, *, lockfile: bool = False,
    warn: Callable[[str], None],
) -> tuple[str, bool]:
    """Update only the app's own JSON versions; report invalid optional fields."""
    def reject_constant(value: str) -> None:
        raise ValueError(f"Invalid JSON constant: {value}")

    data = json.loads(text, parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    owners = [(data, "version")]
    if lockfile:
        packages = data.get("packages")
        if isinstance(packages, dict) and "" in packages:
            owners.append((packages[""], 'packages[""].version'))
    changed = False
    valid = False
    for owner, field in owners:
        if (not isinstance(owner, dict) or not isinstance(owner.get("version"), str)
                or not owner["version"].strip()):
            warn(f"{field}: missing or non-string version")
            continue
        valid = True
        if owner["version"] != new_version:
            owner["version"] = new_version
            changed = True
    if not valid:
        raise ValueError("No valid app version fields")
    if not changed:
        return text, False
    indent_match = re.search(r'\n([ \t]+)"', text)
    indent = indent_match.group(1) if indent_match else None
    updated = json.dumps(data, ensure_ascii=False, indent=indent)
    if text.endswith("\n"):
        updated += "\n"
    return updated, True

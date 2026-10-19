"""Section-aware TOML version updating for Python manifests and core config."""

import re


class VersionConsistencyError(ValueError):
    """A version field differs from the expected authoritative value."""


def sync_section_version(
    text: str, section_header: str, current_version: str, new_version: str,
    *, check_consistency: bool = False,
) -> tuple[str, bool]:
    """Update an existing version assignment without serializing the TOML file."""
    lines = text.splitlines(keepends=True)
    in_section = False
    section_seen = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == section_header
            section_seen = section_seen or in_section
            continue
        if not in_section:
            continue
        match = re.match(r'^(\s*version\s*=\s*")([^"]+)(".*)$', line)
        if not match:
            continue
        actual = match[2]
        if check_consistency and actual != current_version:
            raise VersionConsistencyError(f"Version is {actual}, expected {current_version}")
        if actual == new_version:
            return text, False
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        suffix = match[3].rstrip("\r\n")
        lines[index] = f"{match[1]}{new_version}{suffix}{ending}"
        return "".join(lines), True
    if not section_seen:
        raise ValueError(f"Missing {section_header}")
    raise ValueError(f"Missing version field in {section_header}")

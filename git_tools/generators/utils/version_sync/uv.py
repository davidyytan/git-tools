"""Own-package uv.lock version syncing; no dependency resolution or uv invocation."""

import re

from .pyproject import VersionConsistencyError


def sync_uv_lock(
    text: str, package_name: str, current_version: str, new_version: str,
    *, check_consistency: bool = False,
) -> tuple[str, bool]:
    """Sync one named package using already converted Python version strings."""
    lines = text.splitlines(keepends=True)
    in_package = False
    matches = False
    found = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[[package]]":
            in_package = True
            matches = False
            continue
        if stripped.startswith("[[") and stripped != "[[package]]":
            in_package = False
            matches = False
            continue
        if not in_package:
            continue
        name = re.match(r'^(\s*name\s*=\s*")([^"]+)(".*)$', line)
        if name:
            matches = name[2] == package_name
            found = found or matches
            continue
        if not matches:
            continue
        version = re.match(r'^(\s*version\s*=\s*")([^"]+)(".*)$', line)
        if not version:
            continue
        actual = version[2]
        if check_consistency and actual != current_version:
            raise VersionConsistencyError(f"Version is {actual}, expected {current_version}")
        if actual == new_version:
            return text, False
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        suffix = version[3].rstrip("\r\n")
        lines[index] = f"{version[1]}{new_version}{suffix}{ending}"
        return "".join(lines), True
    if not found:
        raise ValueError(f"Does not contain package {package_name!r}")
    raise ValueError(f"Does not contain a version for package {package_name!r}")

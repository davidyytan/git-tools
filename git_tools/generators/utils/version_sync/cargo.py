"""Standard-library-only helpers for best-effort auxiliary version syncing.

These functions do not write files or choose release versions. Callers own
warning/skip handling; .cz.toml remains the sole version authority.
"""

from __future__ import annotations

import re
import tomllib
from typing import Any

_VERSION_LINE = re.compile(
    r'''(\s*version\s*=\s*)(["'])([^"'\r\n]+)\2([ \t]*(?:#[^\r\n]*)?)(\r?\n)?'''
)


def _replace_version(line: str, version: str) -> str | None:
    match = _VERSION_LINE.fullmatch(line)
    if match is None:
        return None
    return f"{match[1]}{match[2]}{version}{match[2]}{match[4]}{match[5] or ''}"


def sync_cargo_manifest(text: str, new_version: str) -> tuple[str, bool]:
    """Update one literal [package].version, preserving comments and formatting."""
    data = tomllib.loads(text)
    package = data.get("package")
    if not isinstance(package, dict) or not isinstance(package.get("version"), str) or not package["version"].strip():
        raise ValueError("Missing literal [package].version; workspace inheritance is not auto-synced")
    lines = text.splitlines(keepends=True)
    in_package = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            in_package = bool(re.fullmatch(r'\[package\]\s*(?:#.*)?', stripped))
            continue
        if not in_package:
            continue
        updated_line = _replace_version(line, new_version)
        if updated_line is not None:
            lines[index] = updated_line
            updated = "".join(lines)
            expected = {**data, "package": {**package, "version": new_version}}
            if tomllib.loads(updated) != expected:
                raise ValueError("Cargo manifest update changed unexpected fields")
            return updated, package["version"] != new_version
    raise ValueError("Unsupported Cargo version layout; expected single-line [package].version")


def sync_cargo_lock(
    text: str, package_name: str, package_version: str, new_version: str,
) -> tuple[str, bool]:
    """Update exactly one local crate entry, never registry/git dependency versions."""
    data = tomllib.loads(text)
    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise ValueError("Cargo lockfile has no package array")
    candidates = [index for index, package in enumerate(packages)
                  if isinstance(package, dict) and package.get("name") == package_name
                  and package.get("version") == package_version and "source" not in package]
    if len(candidates) != 1:
        raise ValueError("Cargo lockfile has no unique matching local package; regenerate with Cargo")
    reference = f"{package_name} {package_version}"
    if package_version != new_version and any(
        isinstance(package, dict) and isinstance(package.get("dependencies"), list)
        and any(isinstance(dep, str) and (dep == reference or dep.startswith(reference + " ("))
                for dep in package["dependencies"])
        for package in packages
    ):
        raise ValueError("Cargo lockfile has version-qualified references; regenerate with Cargo")
    lines = text.splitlines(keepends=True)
    block = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if re.fullmatch(r'\[\[package\]\]\s*(?:#.*)?', stripped):
            block += 1
            continue
        if stripped.startswith("[") and block == candidates[0]:
            break
        if block != candidates[0]:
            continue
        updated_line = _replace_version(line, new_version)
        if updated_line is not None:
            lines[index] = updated_line
            updated = "".join(lines)
            expected: list[dict[str, Any]] = [dict(package) for package in packages]
            expected[candidates[0]]["version"] = new_version
            if tomllib.loads(updated) != {**data, "package": expected}:
                raise ValueError("Cargo lockfile update changed unexpected fields")
            return updated, package_version != new_version
    raise ValueError("Unsupported Cargo lockfile version layout")

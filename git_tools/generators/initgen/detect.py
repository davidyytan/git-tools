"""Detect sensible init defaults from existing config and git tags."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..bumpgen import ConfigError, Version
from .config import (
    DEDICATED_CONFIG_FILES,
    find_existing_commitizen_config,
    read_nested_string,
    read_toml,
)


def detect_default_version(root: Path) -> str:
    existing_config = find_existing_commitizen_config(root)
    if existing_config is not None:
        existing_data = read_toml(existing_config)
        if existing_config.name in DEDICATED_CONFIG_FILES:
            commitizen = existing_data.get("tool", {}).get("commitizen", {})
        else:
            commitizen = existing_data.get("tool", {}).get("commitizen", {})
        existing_version = read_nested_string(commitizen, ("version",))
        if existing_version is not None:
            try:
                Version.parse(existing_version)
                return existing_version
            except ConfigError:
                pass

    latest_tag = detect_latest_semver_tag(root)
    if latest_tag is not None:
        return latest_tag[0]

    return "0.0.1"


def detect_default_tag_format(root: Path) -> str:
    latest_tag = detect_latest_semver_tag(root)
    if latest_tag is not None:
        return latest_tag[1]
    return "$version"


def detect_latest_semver_tag(root: Path) -> tuple[str, str] | None:
    result = subprocess.run(
        ["git", "tag", "--sort=-creatordate"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    for raw_tag in result.stdout.splitlines():
        tag_name = raw_tag.strip()
        if not tag_name:
            continue

        if tag_name.startswith("v"):
            candidate = tag_name[1:]
            tag_format = "v$version"
        else:
            candidate = tag_name
            tag_format = "$version"

        try:
            Version.parse(candidate)
        except ConfigError:
            continue
        return candidate, tag_format

    return None

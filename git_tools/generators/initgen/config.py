"""Commitizen config model, discovery, and TOML section rendering."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..bumpgen import DEFAULT_SCHEME, Scheme

# Maps a parsed Version.scheme to the value written into `.cz.toml`'s
# `version_scheme` key. Commitizen recognizes `semver2` and `semver`.
VERSION_SCHEME_LABEL: dict[Scheme, str] = {
    "semver2": "semver2",
    "semver": "semver",
}

SUPPORTED_CONFIG_FILES = (".cz.toml",)
DEDICATED_CONFIG_FILES = (".cz.toml",)
LEGACY_UNSUPPORTED_CONFIG_FILES = ("cz.toml",)
COMMITIZEN_SECTION_HEADER = "[tool.commitizen]"
COMMITIZEN_SECTION_REGEX = re.compile(
    r"(?ms)^\[tool\.commitizen\]\n.*?(?=^\[[^\n]+\]\n|\Z)"
)


class CzInitError(RuntimeError):
    """Raised when the init flow cannot write a safe config."""


@dataclass(frozen=True)
class CzInitOptions:
    config_file: str
    version: str
    tag_format: str
    major_version_zero: bool
    scheme: Scheme = DEFAULT_SCHEME


def find_existing_commitizen_config(root: Path) -> Path | None:
    path = root / ".cz.toml"
    return path if path.exists() else None


def find_legacy_commitizen_config(root: Path) -> Path | None:
    for relative_path in LEGACY_UNSUPPORTED_CONFIG_FILES:
        path = root / relative_path
        if path.exists():
            return path
    pyproject_path = root / "pyproject.toml"
    pyproject_data = read_toml(pyproject_path)
    tool = pyproject_data.get("tool")
    if isinstance(tool, dict):
        commitizen = tool.get("commitizen")
        if isinstance(commitizen, dict):
            return pyproject_path
    return None


def read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise CzInitError(f"Invalid TOML in {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def read_nested_string(data: dict, keys: tuple[str, ...]) -> str | None:
    current: object = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, str) else None


def build_commitizen_section(options: CzInitOptions) -> str:
    scheme_label = VERSION_SCHEME_LABEL[options.scheme]
    lines = [
        COMMITIZEN_SECTION_HEADER,
        'name = "cz_conventional_commits"',
        f'tag_format = "{options.tag_format}"',
        f'version_scheme = "{scheme_label}"',
        f'version = "{options.version}"',
    ]
    if options.major_version_zero:
        lines.append("major_version_zero = true")
    return "\n".join(lines).rstrip() + "\n"


def upsert_commitizen_section(existing_text: str, section_text: str) -> str:
    stripped_section = section_text.strip()
    if not existing_text.strip():
        return stripped_section + "\n"

    match = COMMITIZEN_SECTION_REGEX.search(existing_text)
    if match:
        before = existing_text[:match.start()].rstrip()
        after = existing_text[match.end():].strip()
        parts = [part for part in (before, stripped_section, after) if part]
        return "\n\n".join(parts).rstrip() + "\n"

    return existing_text.rstrip() + "\n\n" + stripped_section + "\n"

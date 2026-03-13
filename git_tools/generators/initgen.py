"""Commitizen-compatible init flow for git-tools."""

from __future__ import annotations

import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

from git_tools.bump import ConfigError, SemVer2Version

from .base import BaseGenerator, print_panel, success, warning

SUPPORTED_CONFIG_FILES = (".cz.toml", "cz.toml", "pyproject.toml")
DEDICATED_CONFIG_FILES = (".cz.toml", "cz.toml")
SUPPORTED_VERSION_PROVIDERS = ("commitizen", "pep621", "uv")
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
    version_provider: str
    tag_format: str
    major_version_zero: bool


class CommitizenInitGenerator(BaseGenerator):
    """Interactive init wizard for Commitizen-compatible config."""

    def __init__(
        self,
        config_file: Optional[str] = None,
        version: Optional[str] = None,
        version_provider: Optional[str] = None,
        tag_format: Optional[str] = None,
        major_version_zero: Optional[bool] = None,
        force: bool = False,
        interactive: bool = False,
    ):
        super().__init__(interactive=interactive)
        self._cli_config_file = config_file
        self._cli_version = version
        self._cli_version_provider = version_provider
        self._cli_tag_format = tag_format
        self._cli_major_version_zero = major_version_zero
        self._cli_force = force

    def generate_init(self, *, cwd: Path | None = None) -> Path:
        root = (cwd or Path.cwd()).resolve()
        existing_config = find_existing_commitizen_config(root)
        options = self._build_options(root, existing_config)
        target_path = root / options.config_file
        existing_text = target_path.read_text(encoding="utf-8") if target_path.exists() else ""

        self._validate_target(existing_config, target_path)
        if existing_text.strip():
            try:
                read_toml(target_path)
            except CzInitError:
                if not (self._cli_force and target_path.name in DEDICATED_CONFIG_FILES):
                    raise
                warning(f"Overwriting invalid TOML in {target_path}.")
                existing_text = ""

        if self._interactive:
            self._print_summary(options)
            if not self.prompt_confirm("Write Commitizen config now?", default=True):
                raise CzInitError("Init cancelled.")

        target_path.write_text(
            upsert_commitizen_section(
                existing_text,
                build_commitizen_section(options),
            ),
            encoding="utf-8",
        )

        success(f"Wrote Commitizen config to {target_path}")
        self._print_follow_up_warnings(root, options)
        return target_path

    def _build_options(
        self,
        root: Path,
        existing_config: Path | None,
    ) -> CzInitOptions:
        config_file = self._resolve_config_file(existing_config)
        version = self._resolve_version(root)
        version_provider = self._resolve_version_provider(root)
        tag_format = self._resolve_tag_format(root)
        major_version_zero = self._resolve_major_version_zero(version)
        return CzInitOptions(
            config_file=config_file,
            version=version,
            version_provider=version_provider,
            tag_format=tag_format,
            major_version_zero=major_version_zero,
        )

    def _resolve_config_file(self, existing_config: Path | None) -> str:
        default = self._cli_config_file
        if default is None:
            if existing_config and self._cli_force:
                default = existing_config.name
            else:
                default = ".cz.toml"

        if default not in SUPPORTED_CONFIG_FILES:
            raise CzInitError(
                f"Unsupported config file: {default}. Choose one of {', '.join(SUPPORTED_CONFIG_FILES)}."
            )

        if self._interactive:
            return self.prompt_select(
                "Choose a Commitizen config file",
                list(SUPPORTED_CONFIG_FILES),
                default=default,
            )
        return default

    def _resolve_version(self, root: Path) -> str:
        default = self._cli_version or detect_default_version(root)
        while True:
            candidate = (
                self.prompt_text("Enter the initial version", default)
                if self._interactive
                else default
            ).strip()
            try:
                SemVer2Version.parse(candidate)
            except ConfigError:
                if not self._interactive:
                    raise CzInitError(f"Unsupported semver2 version: {candidate}")
                warning("Version must follow semver2, for example 0.1.0 or 1.2.0-alpha.1.")
                continue
            return candidate

    def _resolve_version_provider(self, root: Path) -> str:
        default = self._cli_version_provider or detect_default_version_provider(root)
        if default not in SUPPORTED_VERSION_PROVIDERS:
            raise CzInitError(
                f"Unsupported version provider: {default}. Choose one of {', '.join(SUPPORTED_VERSION_PROVIDERS)}."
            )

        if self._interactive:
            return self.prompt_select(
                "Choose the version provider",
                list(SUPPORTED_VERSION_PROVIDERS),
                default=default,
            )
        return default

    def _resolve_tag_format(self, root: Path) -> str:
        default = self._cli_tag_format or detect_default_tag_format(root)
        while True:
            candidate = (
                self.prompt_text("Enter the tag format", default)
                if self._interactive
                else default
            ).strip()
            if "$version" not in candidate:
                if not self._interactive:
                    raise CzInitError("Tag format must include $version.")
                warning('Tag format must include "$version".')
                continue
            return candidate

    def _resolve_major_version_zero(self, version: str) -> bool:
        parsed = SemVer2Version.parse(version)
        if self._cli_major_version_zero is not None:
            return self._cli_major_version_zero

        if parsed.major > 0:
            return False

        default = True
        if self._interactive:
            return self.prompt_confirm(
                "Treat breaking changes as MINOR while major version is zero?",
                default=default,
            )
        return default

    def _validate_target(self, existing_config: Path | None, target_path: Path) -> None:
        if existing_config is None:
            return

        if not self._cli_force:
            raise CzInitError(
                f"Commitizen config already exists in {existing_config}. Re-run with --force to update it."
            )

        if existing_config.resolve() != target_path.resolve():
            raise CzInitError(
                f"Commitizen config already exists in {existing_config}. Update that file in place or remove it first."
            )

    def _print_summary(self, options: CzInitOptions) -> None:
        lines = [
            f"Config file: {options.config_file}",
            f"Version: {options.version}",
            f"Version provider: {options.version_provider}",
            f"Tag format: {options.tag_format}",
            f"Major version zero: {'true' if options.major_version_zero else 'false'}",
        ]
        print_panel("\n".join(lines), title="Commitizen Config")

    def _print_follow_up_warnings(self, root: Path, options: CzInitOptions) -> None:
        pyproject_data = read_toml(root / "pyproject.toml")
        project_version = read_nested_string(pyproject_data, ("project", "version"))

        if options.version_provider in {"pep621", "uv"} and project_version is None:
            warning(
                "pyproject.toml does not contain [project].version. "
                "That provider setting was written for compatibility, but bump sync will only manage pyproject when that field exists."
            )

        if options.version_provider == "uv" and not (root / "uv.lock").exists():
            warning("uv.lock was not found. It will be synced automatically once the lockfile exists.")


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
                SemVer2Version.parse(existing_version)
                return existing_version
            except ConfigError:
                pass

    latest_tag = detect_latest_semver_tag(root)
    if latest_tag is not None:
        return latest_tag[0]

    return "0.0.1"


def detect_default_version_provider(root: Path) -> str:
    return "commitizen"


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
            SemVer2Version.parse(candidate)
        except ConfigError:
            continue
        return candidate, tag_format

    return None


def find_existing_commitizen_config(root: Path) -> Path | None:
    for relative_path in SUPPORTED_CONFIG_FILES:
        path = root / relative_path
        if not path.exists():
            continue

        if relative_path in DEDICATED_CONFIG_FILES:
            return path

        data = read_toml(path)
        tool = data.get("tool")
        if not isinstance(tool, dict):
            continue

        commitizen = tool.get("commitizen")
        if isinstance(commitizen, dict):
            return path
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
    lines = [
        COMMITIZEN_SECTION_HEADER,
        'name = "cz_conventional_commits"',
        f'tag_format = "{options.tag_format}"',
        'version_scheme = "semver2"',
    ]
    if options.version_provider == "commitizen":
        lines.append(f'version = "{options.version}"')
    else:
        lines.append(f'version_provider = "{options.version_provider}"')
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

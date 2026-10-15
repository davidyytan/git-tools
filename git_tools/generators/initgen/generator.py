"""Interactive ``git-tools init`` wizard."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..base import BaseGenerator, print_panel, success, warning
from ..bumpgen import ConfigError, Version
from .config import (
    DEDICATED_CONFIG_FILES,
    SUPPORTED_CONFIG_FILES,
    VERSION_SCHEME_LABEL,
    CzInitError,
    CzInitOptions,
    build_commitizen_section,
    find_existing_commitizen_config,
    find_legacy_commitizen_config,
    read_nested_string,
    read_toml,
    upsert_commitizen_section,
)
from .detect import detect_default_tag_format, detect_default_version


class CommitizenInitGenerator(BaseGenerator):
    """Interactive init wizard for Commitizen-compatible config."""

    def __init__(
        self,
        config_file: Optional[str] = None,
        version: Optional[str] = None,
        tag_format: Optional[str] = None,
        major_version_zero: Optional[bool] = None,
        force: bool = False,
        interactive: bool = False,
    ):
        super().__init__(interactive=interactive)
        self._cli_config_file = config_file
        self._cli_version = version
        self._cli_tag_format = tag_format
        self._cli_major_version_zero = major_version_zero
        self._cli_force = force

    def generate_init(self, *, cwd: Path | None = None) -> Path:
        root = (cwd or Path.cwd()).resolve()
        legacy_config = find_legacy_commitizen_config(root)
        if legacy_config is not None:
            raise CzInitError(
                f"Unsupported legacy Commitizen config found in {legacy_config.name}. "
                "Use .cz.toml as the authoritative Commitizen config instead."
            )
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
        tag_format = self._resolve_tag_format(root)
        major_version_zero = self._resolve_major_version_zero(version)
        scheme = Version.parse(version).scheme
        return CzInitOptions(
            config_file=config_file,
            version=version,
            tag_format=tag_format,
            major_version_zero=major_version_zero,
            scheme=scheme,
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

        if self._interactive and len(SUPPORTED_CONFIG_FILES) > 1:
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
                Version.parse(candidate)
            except ConfigError:
                if not self._interactive:
                    raise CzInitError(
                        f"Unsupported version: {candidate}. Expected semver2 "
                        "(1.0.0-alpha.0), or semver (1.0.0-a0)."
                    )
                warning(
                    "Version must be semver2 (e.g. 1.2.0-alpha.1) "
                    "or semver (e.g. 1.2.0-a1)."
                )
                continue
            return candidate

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
        parsed = Version.parse(version)
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
            f"Version scheme: {VERSION_SCHEME_LABEL[options.scheme]}",
            f"Tag format: {options.tag_format}",
            f"Major version zero: {'true' if options.major_version_zero else 'false'}",
        ]
        print_panel("\n".join(lines), title="Commitizen Config")

    def _print_follow_up_warnings(self, root: Path, options: CzInitOptions) -> None:
        pyproject_data = read_toml(root / "pyproject.toml")
        project_name = read_nested_string(pyproject_data, ("project", "name"))
        project_version = read_nested_string(pyproject_data, ("project", "version"))

        if pyproject_data and project_version is None:
            warning(
                "pyproject.toml does not contain [project].version. "
                "Bump sync will only update pyproject when that field exists."
            )

        if (root / "uv.lock").exists() and not project_name:
            warning(
                "uv.lock was found but pyproject.toml does not contain [project].name. "
                "Bump sync will only update uv.lock when the package name is known."
            )

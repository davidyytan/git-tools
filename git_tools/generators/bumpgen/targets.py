"""Version-file adapters: each knows how to rewrite one managed location."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..utils.version_sync import (
    VersionConsistencyError, sync_cargo_lock, sync_cargo_manifest,
    sync_npm_versions, sync_section_version, sync_uv_lock,
)
from .errors import ConfigError, ConsistencyError
from .version import INLINE_VERSION_REGEX, version_to_uv_version

# Warnings keep the package logger name so existing log filters still match.
_LOGGER = logging.getLogger(__package__)


class VersionTarget:
    """A mutable version location inside a file."""

    path: Path
    label: str

    def apply(
        self,
        text: str,
        *,
        current_version: str,
        new_version: str,
        check_consistency: bool,
    ) -> tuple[str, bool]:
        raise NotImplementedError


@dataclass(frozen=True)
class SectionVersionTarget(VersionTarget):
    path: Path
    label: str
    section_header: str
    strict_consistency: bool = True

    def apply(
        self,
        text: str,
        *,
        current_version: str,
        new_version: str,
        check_consistency: bool,
    ) -> tuple[str, bool]:
        try:
            return sync_section_version(
                text, self.section_header, current_version, new_version,
                check_consistency=check_consistency,
            )
        except VersionConsistencyError as exc:
            raise ConsistencyError(f"{self.label} in {self.path}: {exc}") from exc
        except ValueError as exc:
            raise ConfigError(f"{self.label} in {self.path}: {exc}") from exc


@dataclass(frozen=True)
class PatternVersionTarget(VersionTarget):
    path: Path
    label: str
    regex: re.Pattern[str]
    strict_consistency: bool = True

    def apply(
        self,
        text: str,
        *,
        current_version: str,
        new_version: str,
        check_consistency: bool,
    ) -> tuple[str, bool]:
        matched_lines: list[str] = []
        current_version_found = False

        for line in text.splitlines(keepends=True):
            if self.regex.search(line):
                matched_lines.append(line)
                if current_version in line:
                    current_version_found = True

        if check_consistency and not current_version_found:
            raise ConsistencyError(
                f"{self.label} in {self.path} does not contain {current_version}."
            )

        if not matched_lines:
            raise ConfigError(f"{self.label} in {self.path} did not match any lines.")

        actual_versions = sorted(
            {
                match.group(0)
                for line in matched_lines
                for match in INLINE_VERSION_REGEX.finditer(line)
            }
        )

        if current_version_found:
            source_version = current_version
        elif len(actual_versions) == 1:
            source_version = actual_versions[0]
        else:
            raise ConsistencyError(
                f"{self.label} in {self.path} is ambiguous; expected {current_version}."
            )

        changed = False
        updated_lines: list[str] = []
        for line in text.splitlines(keepends=True):
            if self.regex.search(line):
                updated_line = line.replace(source_version, new_version)
                changed = changed or updated_line != line
                updated_lines.append(updated_line)
            else:
                updated_lines.append(line)
        return "".join(updated_lines), changed


@dataclass(frozen=True)
class UvLockVersionTarget(VersionTarget):
    path: Path
    label: str
    package_name: str
    strict_consistency: bool = True

    def apply(
        self,
        text: str,
        *,
        current_version: str,
        new_version: str,
        check_consistency: bool,
    ) -> tuple[str, bool]:
        try:
            return sync_uv_lock(
                text, self.package_name, version_to_uv_version(current_version),
                version_to_uv_version(new_version), check_consistency=check_consistency,
            )
        except VersionConsistencyError as exc:
            raise ConsistencyError(f"{self.label} in {self.path}: {exc}") from exc
        except ValueError as exc:
            raise ConfigError(f"{self.label} in {self.path}: {exc}") from exc


@dataclass(frozen=True)
class CargoManifestVersionTarget(VersionTarget):
    """Best-effort adapter for a standalone Cargo manifest."""

    path: Path
    label: str
    strict_consistency: bool = False

    def apply(self, text: str, *, current_version: str, new_version: str,
              check_consistency: bool) -> tuple[str, bool]:
        return sync_cargo_manifest(text, new_version)


@dataclass(frozen=True)
class CargoLockVersionTarget(VersionTarget):
    """Best-effort adapter for the matching local crate in a Cargo lockfile."""

    path: Path
    label: str
    package_name: str
    package_version: str
    strict_consistency: bool = False

    def apply(self, text: str, *, current_version: str, new_version: str,
              check_consistency: bool) -> tuple[str, bool]:
        return sync_cargo_lock(text, self.package_name, self.package_version, new_version)


@dataclass(frozen=True)
class JsonVersionTarget(VersionTarget):
    """Sync only an npm manifest's own version, never nested packages."""

    path: Path
    label: str
    lockfile: bool = False
    strict_consistency: bool = False

    def apply(
        self,
        text: str,
        *,
        current_version: str,
        new_version: str,
        check_consistency: bool,
    ) -> tuple[str, bool]:
        return sync_npm_versions(
            text, new_version, lockfile=self.lockfile,
            warn=lambda message: _warn_auxiliary(self.path, message),
        )


def _warn_auxiliary(target: object, error: object) -> None:
    _LOGGER.warning("Skipping auxiliary version sync for %s: %s", target, error)


def _is_core_version_path(root: Path, path: Path) -> bool:
    return path.absolute() == (root / ".cz.toml").absolute()

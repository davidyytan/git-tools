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
from .version import Version, version_to_uv_version

# Capture complete version-like tokens, including unsupported suffixes, so a
# stable prefix is never rewritten inside a prerelease, build, or longer value.
_CUSTOM_VERSION_TOKEN = re.compile(r"(?<![\w.+-])\d+\.\d+\.\d+[\w.+-]*")

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
        lines = text.splitlines(keepends=True)
        replacements: dict[int, re.Match[str]] = {}
        source_versions: set[str] = set()

        # Validate the entire target before producing any replacement. A regex
        # selects lines, not fields; multiple values on one line are unsafe even
        # when they happen to carry the same version today.
        for index, line in enumerate(lines):
            if not self.regex.search(line):
                continue
            matches = list(_CUSTOM_VERSION_TOKEN.finditer(line))
            if not matches:
                continue
            if len(matches) != 1:
                raise ConsistencyError(
                    f"{self.label} in {self.path} is ambiguous: multiple version "
                    f"values on line {index + 1}."
                )
            match = matches[0]
            try:
                Version.parse(match.group(0))
            except ConfigError as exc:
                raise ConsistencyError(
                    f"{self.label} in {self.path} has an unsupported version "
                    f"token on line {index + 1}: {match.group(0)!r}."
                ) from exc
            replacements[index] = match
            source_versions.add(match.group(0))

        if not replacements:
            raise ConfigError(
                f"{self.label} in {self.path} did not select any supported version tokens."
            )
        if len(source_versions) != 1:
            raise ConsistencyError(
                f"{self.label} in {self.path} is ambiguous: selected lines "
                "contain differing versions."
            )
        source_version = next(iter(source_versions))
        if check_consistency and source_version != current_version:
            raise ConsistencyError(
                f"{self.label} in {self.path} does not contain {current_version}."
            )

        for index, match in replacements.items():
            line = lines[index]
            lines[index] = line[:match.start()] + new_version + line[match.end():]
        return "".join(lines), source_version != new_version


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

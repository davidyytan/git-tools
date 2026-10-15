"""Read ``.cz.toml`` and discover every managed version location."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from string import Template

from .errors import ConfigError
from .targets import (
    CargoLockVersionTarget,
    CargoManifestVersionTarget,
    JsonVersionTarget,
    PatternVersionTarget,
    SectionVersionTarget,
    UvLockVersionTarget,
    VersionTarget,
    _warn_auxiliary,
)
from .version import Scheme, Version

DEFAULT_TAG_FORMAT = "$version"


@dataclass(frozen=True)
class BumpConfig:
    root: Path
    current_version: Version
    current_version_text: str
    project_name: str | None
    tag_format: str
    major_version_zero: bool
    version_targets: tuple[VersionTarget, ...]


def load_bump_config(root: Path) -> BumpConfig:
    cz_config_path, cz_settings = _load_commitizen_settings(root)
    pyproject_path = root / "pyproject.toml"

    commitizen_version = _read_nested_string(cz_settings, ("version",))
    commitizen_version_provider = _read_nested_string(cz_settings, ("version_provider",))
    commitizen_version_scheme = _read_nested_string(cz_settings, ("version_scheme",))
    if cz_config_path is None:
        raise ConfigError("No managed version found in .cz.toml.")
    if commitizen_version is None:
        if commitizen_version_provider is not None:
            raise ConfigError(
                ".cz.toml must contain [tool.commitizen].version. "
                "External version providers are not supported as the source of truth."
            )
        raise ConfigError("No managed version found in .cz.toml.")
    current_version_text = commitizen_version
    current_version = _resolve_configured_version(
        current_version_text, commitizen_version_scheme
    )

    try:
        pyproject_data = _read_toml(pyproject_path)
    except Exception as exc:
        _warn_auxiliary(pyproject_path, exc)
        pyproject_data = {}
    pyproject_version = _read_nested_string(pyproject_data, ("project", "version"))
    project_name = _read_nested_string(pyproject_data, ("project", "name"))

    tag_format = _read_nested_string(cz_settings, ("tag_format",)) or DEFAULT_TAG_FORMAT
    major_version_zero = bool(cz_settings.get("major_version_zero", False))

    targets: list[VersionTarget] = []
    auto_managed_paths: set[Path] = set()
    if cz_config_path is not None and commitizen_version is not None:
        targets.append(
            SectionVersionTarget(
                path=cz_config_path,
                label="Commitizen version",
                section_header="[tool.commitizen]",
                strict_consistency=True,
            )
        )
        auto_managed_paths.add(cz_config_path)

    if pyproject_version is not None:
        targets.append(
            SectionVersionTarget(
                path=pyproject_path,
                label="PEP 621 project version",
                section_header="[project]",
                strict_consistency=False,
            )
        )
        auto_managed_paths.add(pyproject_path)

    uv_lock_path = root / "uv.lock"
    try:
        if uv_lock_path.exists() and project_name:
            targets.append(
                UvLockVersionTarget(
                    path=uv_lock_path,
                    label="uv lock package version",
                    package_name=canonicalize_package_name(project_name),
                    strict_consistency=False,
                )
            )
            auto_managed_paths.add(uv_lock_path)
    except Exception as exc:
        _warn_auxiliary(uv_lock_path, exc)

    for filename in ("package.json", "package-lock.json", "npm-shrinkwrap.json"):
        path = root / filename
        # Register absent paths too, so configured regex entries cannot override
        # JSON-aware selection. Only existing root files are automatic targets.
        auto_managed_paths.add(path)
        try:
            if path.exists():
                targets.append(
                    JsonVersionTarget(
                        path=path,
                        label="npm app version",
                        lockfile=filename != "package.json",
                    )
                )
        except Exception as exc:
            _warn_auxiliary(path, exc)

    # Explicit conventional app locations only; never walk workspace members.
    for directory in (root, root / "src-tauri"):
        manifest = directory / "Cargo.toml"
        lockfile = directory / "Cargo.lock"
        auto_managed_paths.update((manifest, lockfile))
        try:
            if not manifest.exists():
                if lockfile.exists():
                    _warn_auxiliary(lockfile, "no sibling Cargo.toml to identify the local crate")
                continue
            cargo_data = _read_toml(manifest)
            package = cargo_data.get("package")
            if not isinstance(package, dict):
                _warn_auxiliary(manifest, "no standalone [package]; workspace versions are not auto-synced")
                continue
            cargo_version = _read_nested_string(cargo_data, ("package", "version"))
            if not cargo_version or not cargo_version.strip():
                _warn_auxiliary(manifest, "missing literal [package].version; workspace inheritance is not auto-synced")
                continue
            targets.append(CargoManifestVersionTarget(path=manifest, label="Cargo package version"))
            cargo_name = _read_nested_string(cargo_data, ("package", "name"))
            if lockfile.exists():
                if cargo_name and cargo_name.strip():
                    targets.append(CargoLockVersionTarget(
                        path=lockfile, label="Cargo local package lock version",
                        package_name=cargo_name, package_version=cargo_version,
                    ))
                else:
                    _warn_auxiliary(lockfile, "missing [package].name in sibling Cargo.toml")
        except Exception as exc:
            _warn_auxiliary(manifest, exc)

    raw_version_files = cz_settings.get("version_files")
    if isinstance(raw_version_files, list):
        for spec in raw_version_files:
            if not isinstance(spec, str):
                _warn_auxiliary("version_files entry", "expected a string")
                continue
            try:
                resolved_targets = _resolve_version_file_spec(root, spec, current_version_text)
                if not resolved_targets:
                    _warn_auxiliary(f"version_files entry {spec}", "no matching files")
                for path, regex in resolved_targets:
                    if path.resolve() in {managed.resolve() for managed in auto_managed_paths}:
                        continue
                    targets.append(
                        PatternVersionTarget(
                            path=path,
                            label=f"version_files entry {spec}",
                            regex=regex,
                            strict_consistency=False,
                        )
                    )
            except Exception as exc:
                _warn_auxiliary(f"version_files entry {spec}", exc)

    return BumpConfig(
        root=root,
        current_version=current_version,
        current_version_text=current_version_text,
        project_name=project_name,
        tag_format=tag_format,
        major_version_zero=major_version_zero,
        version_targets=tuple(targets),
    )


# Commitizen names SemVer v1 as semver and SemVer v2 as semver2.
_SUPPORTED_CZ_SCHEMES: dict[str, Scheme] = {
    "semver2": "semver2",
    "semver": "semver",
}


def _resolve_configured_version(value: str, configured_scheme: str | None) -> Version:
    """Parse `value` and reconcile it with `configured_scheme` from .cz.toml.

    Auto-detection alone always returns `semver2` for stable `X.Y.Z` strings,
    so a repo declaring `version_scheme = "semver"` with a stable current
    version would silently flip to `semver2` formatting on the next
    prerelease. Honoring the configured scheme keeps the next bump in the
    configured style.
    """
    parsed = Version.parse(value)
    if configured_scheme is None:
        return parsed

    normalized = _SUPPORTED_CZ_SCHEMES.get(configured_scheme.strip().lower())
    if normalized is None:
        raise ConfigError(
            f"Unsupported version_scheme: {configured_scheme!r}. "
            "Expected one of semver2 or semver."
        )

    if parsed.is_prerelease and parsed.scheme != normalized:
        raise ConfigError(
            f"version_scheme = {normalized!r} disagrees with version "
            f"{value!r} (parsed as {parsed.scheme!r}). Either rewrite the "
            "version in the configured scheme or remove version_scheme."
        )

    return parsed.with_scheme(normalized)


def normalize_tag(version: Version, tag_format: str) -> str:
    template = Template(tag_format or DEFAULT_TAG_FORMAT)
    return template.safe_substitute(
        version=str(version),
        major=version.major,
        minor=version.minor,
        patch=version.patch,
        prerelease=version.prerelease or "",
    )


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def has_bootstrap_commitizen_version(root: Path) -> bool:
    data = _read_toml(root / ".cz.toml")
    return _read_nested_string(data, ("tool", "commitizen", "version")) == "0.0.1"


def load_current_version_for_strategy(root: Path) -> str:
    path = root / ".cz.toml"
    if path.exists():
        version = _read_nested_string(
            _read_toml(path),
            ("tool", "commitizen", "version"),
        )
        if version is not None:
            return version
    raise ConfigError("No managed version found in .cz.toml.")


def _load_commitizen_settings(root: Path) -> tuple[Path | None, dict]:
    path = root / ".cz.toml"
    data = _read_toml(path)
    tool = data.get("tool")
    if isinstance(tool, dict):
        commitizen = tool.get("commitizen")
        if isinstance(commitizen, dict):
            return path, commitizen
    return None, {}


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def _read_nested_string(data: dict, keys: tuple[str, ...]) -> str | None:
    current: object = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, str) else None


def _resolve_version_file_spec(
    root: Path,
    spec: str,
    current_version: str,
) -> list[tuple[Path, re.Pattern[str]]]:
    drive, tail = os.path.splitdrive(spec)
    path_part, _, regex_part = tail.partition(":")
    pattern = drive + path_part
    regex = regex_part or re.escape(current_version)

    compiled = re.compile(regex)
    resolved: list[tuple[Path, re.Pattern[str]]] = []
    for match in sorted(glob(os.fspath(root / pattern))):
        resolved.append((Path(match), compiled))
    return resolved

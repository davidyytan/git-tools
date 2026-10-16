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
    # Use physical identity consistently (notably /var versus /private/var on macOS).
    root = root.resolve()
    cz_config_path, cz_settings = _load_commitizen_settings(root)
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

    sync_auxiliary = _sync_auxiliary_enabled(cz_settings)
    if not sync_auxiliary:
        return BumpConfig(
            root=root,
            current_version=current_version,
            current_version_text=current_version_text,
            project_name=None,
            tag_format=_read_nested_string(cz_settings, ("tag_format",)) or DEFAULT_TAG_FORMAT,
            major_version_zero=bool(cz_settings.get("major_version_zero", False)),
            version_targets=(SectionVersionTarget(
                path=cz_config_path,
                label="Commitizen version",
                section_header="[tool.commitizen]",
                strict_consistency=True,
            ),),
        )

    directories = _auxiliary_directories(root, cz_settings)
    # project_name remains the root project's metadata, never a child's name.
    pyprojects: dict[Path, dict] = {}
    for directory in dict.fromkeys((root, *directories)):
        path = directory / "pyproject.toml"
        try:
            readable_candidate = not path.is_symlink() and (
                _is_auxiliary_file(path) or not path.exists()
            )
            pyprojects[directory] = _read_toml(path) if readable_candidate else {}
        except Exception as exc:
            _warn_auxiliary(path, exc)
            pyprojects[directory] = {}
    project_name = _read_nested_string(pyprojects[root], ("project", "name"))

    tag_format = _read_nested_string(cz_settings, ("tag_format",)) or DEFAULT_TAG_FORMAT
    major_version_zero = bool(cz_settings.get("major_version_zero", False))

    targets: list[VersionTarget] = [SectionVersionTarget(
        path=cz_config_path,
        label="Commitizen version",
        section_header="[tool.commitizen]",
        strict_consistency=True,
    )]
    auto_managed_paths: set[Path] = {cz_config_path}
    locations: dict[str, list[Path]] = {"Python": [], "npm": [], "Cargo": []}
    filenames = {
        "Python": ("pyproject.toml", "uv.lock"),
        "npm": ("package.json", "package-lock.json", "npm-shrinkwrap.json"),
        "Cargo": ("Cargo.toml", "Cargo.lock"),
    }
    for directory in directories:
        for ecosystem, names in filenames.items():
            # Reserve even absent, invalid, or ambiguous ecosystem paths so a
            # broad version_files regex cannot bypass structured handling.
            auto_managed_paths.update(directory / name for name in names)
            if any(_is_auxiliary_file(directory / name) for name in names):
                locations[ecosystem].append(directory)

    explicit = "auxiliary_directories" in cz_settings
    for ecosystem, found in locations.items():
        if not explicit and len(found) > 1:
            names = ", ".join(str(path.relative_to(root)) for path in found)
            _warn_auxiliary(
                ecosystem,
                f"multiple auxiliary locations ({names}); skipping {ecosystem} sync. "
                "Set [tool.commitizen].auxiliary_directories to select directories "
                "that share this release",
            )
            continue
        for directory in found:
            if ecosystem == "Python":
                data = pyprojects[directory]
                pyproject_path = directory / "pyproject.toml"
                if _read_nested_string(data, ("project", "version")) is not None:
                    targets.append(SectionVersionTarget(
                        path=pyproject_path, label="PEP 621 project version",
                        section_header="[project]", strict_consistency=False,
                    ))
                name = _read_nested_string(data, ("project", "name"))
                lockfile = directory / "uv.lock"
                if name and _is_auxiliary_file(lockfile):
                    targets.append(UvLockVersionTarget(
                        path=lockfile, label="uv lock package version",
                        package_name=canonicalize_package_name(name),
                        strict_consistency=False,
                    ))
            elif ecosystem == "npm":
                for filename in filenames["npm"]:
                    path = directory / filename
                    if _is_auxiliary_file(path):
                        targets.append(JsonVersionTarget(
                            path=path, label="npm app version",
                            lockfile=filename != "package.json",
                        ))
            else:
                _add_cargo_targets(directory, targets)

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
                    # Aliases must share pending content rather than producing
                    # competing writes to the same physical custom file.
                    path = path.resolve()
                    if path in {managed.resolve() for managed in auto_managed_paths}:
                        continue
                    targets.append(
                        PatternVersionTarget(
                            path=path,
                            label=f"version_files entry {spec}",
                            regex=regex,
                            strict_consistency=False,
                        )
                    )
            except _OutsideRepositoryError:
                # Unsafe explicit configuration is not a best-effort sync failure.
                raise
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


_AUXILIARY_EXCLUDED_DIRECTORIES = frozenset({
    "node_modules", "target", "build", "dist", "vendor", "venv", "__pycache__",
})


def _auxiliary_directories(root: Path, settings: dict) -> list[Path]:
    """Select release-sharing roots without traversing grandchildren.

    ``[tool.commitizen].auxiliary_directories = [".", "app", "src-tauri"]``
    explicitly opts those directories into the same release across all supported
    ecosystems. An empty list disables automatic auxiliaries. When omitted,
    root and immediate non-hidden, non-tool children are candidates; ambiguity
    is handled independently per ecosystem by the caller. Validation is only
    reached when auxiliary synchronization is enabled.
    """
    if "auxiliary_directories" in settings:
        raw = settings["auxiliary_directories"]
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ConfigError(
                "[tool.commitizen].auxiliary_directories must be a list of strings."
            )
        directories: list[Path] = []
        for item in raw:
            relative = Path(item)
            if (
                not item
                or relative.is_absolute()
                or ".." in relative.parts
                or len(relative.parts) > 1
                or (relative != Path(".") and (
                    relative.name.startswith(".")
                    or relative.name in _AUXILIARY_EXCLUDED_DIRECTORIES
                ))
            ):
                raise ConfigError(
                    f"auxiliary_directories entry {item!r} must be '.' or an immediate "
                    "non-hidden, non-tool child directory of the repository root."
                )
            path = root / relative
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ConfigError(
                        f"auxiliary_directories entry {item!r} must not be a symlink "
                        "or escape the repository root."
                    )
                if not path.is_dir():
                    raise ConfigError(
                        f"auxiliary_directories entry {item!r} is not an existing directory."
                    )
            except OSError as exc:
                raise ConfigError(f"Cannot inspect auxiliary_directories entry {item!r}: {exc}") from exc
            if path not in directories:
                directories.append(path)
        return directories

    directories = [root]
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        _warn_auxiliary(root, exc)
        return directories
    for child in children:
        if child.name.startswith(".") or child.name in _AUXILIARY_EXCLUDED_DIRECTORIES:
            continue
        try:
            if not child.is_symlink() and child.is_dir():
                directories.append(child)
        except OSError as exc:
            _warn_auxiliary(child, exc)
    return directories


def _is_auxiliary_file(path: Path) -> bool:
    """Optional ecosystem inputs must be regular files, never symlinks."""
    try:
        return not path.is_symlink() and path.is_file()
    except OSError as exc:
        _warn_auxiliary(path, exc)
        return False


def _add_cargo_targets(directory: Path, targets: list[VersionTarget]) -> None:
    manifest = directory / "Cargo.toml"
    lockfile = directory / "Cargo.lock"
    try:
        if not _is_auxiliary_file(manifest):
            if _is_auxiliary_file(lockfile):
                _warn_auxiliary(lockfile, "no sibling Cargo.toml to identify the local crate")
            return
        cargo_data = _read_toml(manifest)
        package = cargo_data.get("package")
        if not isinstance(package, dict):
            _warn_auxiliary(manifest, "no standalone [package]; workspace versions are not auto-synced")
            return
        cargo_version = _read_nested_string(cargo_data, ("package", "version"))
        if not cargo_version or not cargo_version.strip():
            _warn_auxiliary(manifest, "missing literal [package].version; workspace inheritance is not auto-synced")
            return
        targets.append(CargoManifestVersionTarget(path=manifest, label="Cargo package version"))
        cargo_name = _read_nested_string(cargo_data, ("package", "name"))
        if _is_auxiliary_file(lockfile):
            if cargo_name and cargo_name.strip():
                targets.append(CargoLockVersionTarget(
                    path=lockfile, label="Cargo local package lock version",
                    package_name=cargo_name, package_version=cargo_version,
                ))
            else:
                _warn_auxiliary(lockfile, "missing [package].name in sibling Cargo.toml")
    except Exception as exc:
        _warn_auxiliary(manifest, exc)


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

    root = root.resolve()
    candidate = root / pattern
    _require_inside_repository(candidate, root, spec)
    paths = [Path(match).resolve() for match in sorted(glob(os.fspath(candidate)))]
    for path in paths:
        _require_inside_repository(path, root, spec)
    compiled = re.compile(regex)
    return [(path, compiled) for path in paths]


class _OutsideRepositoryError(ConfigError):
    """An explicit custom target escapes the repository's physical root."""


def _require_inside_repository(path: Path, root: Path, spec: str) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise _OutsideRepositoryError(
            f"version_files entry {spec!r} resolves outside repository root "
            f"{root}: {resolved}"
        )


def _sync_auxiliary_enabled(settings: dict) -> bool:
    value = settings.get("sync_auxiliary", True)
    if not isinstance(value, bool):
        raise ConfigError("[tool.commitizen].sync_auxiliary must be a TOML boolean (true or false).")
    override = os.environ.get("GIT_TOOLS_BUMP_SYNC_AUXILIARY")
    if override is None:
        return value
    normalized = override.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ConfigError(
        "GIT_TOOLS_BUMP_SYNC_AUXILIARY must be a boolean: "
        "true/false, 1/0, yes/no, or on/off."
    )

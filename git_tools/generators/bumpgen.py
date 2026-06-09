"""Minimal Commitizen-style version bumping with explicit tag control.

This module focuses on the core bump flow:
- read the current version from `.cz.toml`
- detect the next increment from conventional commits
- compute the next version using the repo's semver or semver2 scheme
- update managed version fields, including auxiliary sync targets when present
- create the bump commit and tag

It intentionally stays stdlib-only so it can power:

    git-tools bump ...
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from glob import glob
from pathlib import Path
from string import Template
from typing import Literal, Optional

_OPTIONAL_BASE_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from .base import BaseGenerator, info, print_panel
except ModuleNotFoundError as exc:
    if exc.name not in {"questionary", "rich", "tiktoken"}:
        raise

    _OPTIONAL_BASE_IMPORT_ERROR = exc

    def info(message: str) -> None:
        print(f"• {message}")

    def print_panel(content: str, title: str = "", border_style: str = "") -> None:
        if title:
            print(f"{title}\n{content.strip()}")
        else:
            print(content.strip())

    class BaseGenerator:
        """Fallback base class for stdlib-only bump and strategy flows."""

        def __init__(self, *_: object, interactive: bool = False, **__: object) -> None:
            self.logger = logging.getLogger(self.__class__.__name__)
            self._interactive = interactive

        def _raise_optional_dependency_error(self) -> None:
            missing = (
                _OPTIONAL_BASE_IMPORT_ERROR.name
                if _OPTIONAL_BASE_IMPORT_ERROR and _OPTIONAL_BASE_IMPORT_ERROR.name
                else "questionary"
            )
            raise ModuleNotFoundError(
                f"Optional dependency '{missing}' is required for interactive bump generation."
            ) from _OPTIONAL_BASE_IMPORT_ERROR

        def prompt_select(self, *_: object, **__: object) -> str:
            self._raise_optional_dependency_error()

        def prompt_confirm(self, *_: object, **__: object) -> bool:
            self._raise_optional_dependency_error()

Increment = Literal["MAJOR", "MINOR", "PATCH"]
Prerelease = Literal["alpha", "beta", "rc"]
Scheme = Literal["semver2", "semver"]
Flow = Literal["classic", "variant"]

DEFAULT_TAG_FORMAT = "$version"
DEFAULT_BUMP_MESSAGE = "bump: version $current_version → $new_version"
DEFAULT_BUMP_PATTERN = re.compile(r"^((BREAKING[\-\ ]CHANGE|\w+)(\(.+\))?!?):")
DEFAULT_SCHEME: Scheme = "semver2"
BOOTSTRAP_RELEASE_SUBJECTS = frozenset({"Release 0.0.1", "Release 0.1.0"})

# Two prerelease formats, parsed by trying each scheme in priority order.
# `semver2` uses long names and a dotted number (`-alpha.0`); Commitizen
# `semver` uses SemVer v1 style short names (`-a0`, `-b0`, `-rc0`).
SEMVER2_REGEX = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease_type>alpha|beta|rc)\.(?P<prerelease_number>\d+))?$"
)
SEMVER_REGEX = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease_short>a|b|rc)(?P<prerelease_number>\d+))?$"
)
INLINE_VERSION_REGEX = re.compile(
    r"\d+\.\d+\.\d+"
    r"(?:-(?:(?:alpha|beta|rc)\.\d+|(?:a|b|rc)\d+))?"
)
VERSION_LINE_REGEX = re.compile(r'^(\s*version\s*=\s*")([^"]+)(".*)$')
NAME_LINE_REGEX = re.compile(r'^(\s*name\s*=\s*")([^"]+)(".*)$')
RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<target>\d+\.\d+\.\d+)$")
RELEASE_MERGE_SUBJECT_PATTERN = re.compile(r"^Release (?P<target>\d+\.\d+\.\d+)$")
HOTFIX_MERGE_SUBJECT_PATTERN = re.compile(r"^Hotfix (?P<target>\d+\.\d+\.\d+)$")
START_SUBJECT_PATTERN = re.compile(r"^Start (?P<target>\d+\.\d+\.\d+)$")
BACKMERGE_RELEASE_SUBJECT_PATTERN = re.compile(
    r"^Backmerge Release (?P<target>\d+\.\d+\.\d+)$"
)
BACKMERGE_HOTFIX_SUBJECT_PATTERN = re.compile(
    r"^Backmerge Hotfix (?P<target>\d+\.\d+\.\d+)$"
)
GITHUB_PR_SUFFIX_PATTERN = re.compile(r"^(?P<subject>.+?)\s+\(#\d+\)$")
_VERSION_TOKEN = (
    r"\d+\.\d+\.\d+(?:-(?:(?:alpha|beta|rc)\.\d+|(?:a|b|rc)\d+))?"
)
BUMP_SUBJECT_TARGET_PATTERN = re.compile(
    r"^bump:\s+version\s+"
    rf"(?P<previous>{_VERSION_TOKEN})\s+"
    r"(?:→|->)\s+"
    rf"(?P<current>{_VERSION_TOKEN})$"
)
PRERELEASE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}
SEMVER_PRERELEASE_TYPE_FROM_SHORT: dict[str, Prerelease] = {
    "a": "alpha",
    "b": "beta",
    "rc": "rc",
}
SEMVER_PRERELEASE_SHORT_FROM_TYPE: dict[Prerelease, str] = {
    "alpha": "a",
    "beta": "b",
    "rc": "rc",
}
GENERATED_BUMP_PREFIX = "bump:"
DVC_EXPERIMENT_COMMIT_PATTERN = re.compile(r"^dvc:\s+commit experiment\b")
RELEASE_MANAGEMENT_PREFIX = "chore(release):"
BACKMERGE_PREP_SUBJECT = "chore: merge develop for backmerge"
BUMP_RULES: tuple[tuple[re.Pattern[str], Increment], ...] = (
    (re.compile(r"^.+!$"), "MAJOR"),
    (re.compile(r"^BREAKING[\-\ ]CHANGE"), "MAJOR"),
    (re.compile(r"^feat"), "MINOR"),
    (re.compile(r"^fix"), "PATCH"),
    (re.compile(r"^refactor"), "PATCH"),
    (re.compile(r"^perf"), "PATCH"),
)


class BumpError(RuntimeError):
    """Base class for bump-related failures."""


class ConfigError(BumpError):
    """Raised when the repo configuration cannot be interpreted safely."""


class GitError(BumpError):
    """Raised when a git command fails."""


class ConsistencyError(BumpError):
    """Raised when managed version locations do not agree."""


class NoCommitsFoundError(BumpError):
    """Raised when there are no commits eligible for a bump."""


class NoneIncrementError(BumpError):
    """Raised when commits exist but none produce a bump."""


@dataclass(frozen=True)
class Version:
    """A minimal version model spanning Commitizen semver and semver2.

    The `scheme` field records which format the value was parsed from
    (`semver` or `semver2`) so it can be preserved across bumps and
    emitted in the same shape on `__str__`.
    """

    major: int
    minor: int
    patch: int
    prerelease_type: Prerelease | None = None
    prerelease_number: int | None = None
    scheme: Scheme = DEFAULT_SCHEME

    @classmethod
    def parse(cls, value: str) -> "Version":
        # Try schemes in priority order. semver2 wins for `X.Y.Z` (no
        # prerelease) so existing repos keep their default formatting.
        for scheme, regex in (
            ("semver2", SEMVER2_REGEX),
            ("semver", SEMVER_REGEX),
        ):
            match = regex.fullmatch(value)
            if match is None:
                continue
            prerelease_type: Prerelease | None
            if scheme == "semver":
                short = match.groupdict().get("prerelease_short")
                prerelease_type = (
                    SEMVER_PRERELEASE_TYPE_FROM_SHORT[short] if short else None
                )
            else:
                raw_type = match.group("prerelease_type")
                prerelease_type = raw_type  # type: ignore[assignment]
            raw_number = match.group("prerelease_number")
            return cls(
                major=int(match.group("major")),
                minor=int(match.group("minor")),
                patch=int(match.group("patch")),
                prerelease_type=prerelease_type,
                prerelease_number=int(raw_number) if raw_number is not None else None,
                scheme=scheme,  # type: ignore[arg-type]
            )

        raise ConfigError(
            f"Unsupported version: {value}. Expected semver2 (1.0.0-alpha.0), "
            "or semver (1.0.0-a0)."
        )

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease_type is not None

    @property
    def prerelease(self) -> str | None:
        """Prerelease suffix formatted per the active scheme, without separator.

        Used by `tag_format` substitutions where the leading separator is
        either implicit in the template or already present.
        """
        if self.prerelease_type is None or self.prerelease_number is None:
            return None
        if self.scheme == "semver":
            short = SEMVER_PRERELEASE_SHORT_FROM_TYPE[self.prerelease_type]
            return f"{short}{self.prerelease_number}"
        return f"{self.prerelease_type}.{self.prerelease_number}"

    @property
    def public(self) -> str:
        return str(self)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if not self.is_prerelease:
            return base
        suffix = self.prerelease or ""
        return f"{base}-{suffix}"

    def with_scheme(self, scheme: Scheme) -> "Version":
        if scheme == self.scheme:
            return self
        return Version(
            self.major,
            self.minor,
            self.patch,
            prerelease_type=self.prerelease_type,
            prerelease_number=self.prerelease_number,
            scheme=scheme,
        )

    def bump(
        self,
        increment: Increment | None,
        *,
        prerelease: Prerelease | None = None,
        exact_increment: bool = False,
    ) -> "Version":
        base = self._get_increment_base(increment, exact_increment=exact_increment)
        if prerelease is None:
            return base

        source = self if self.release == base.release else base
        next_prerelease, next_number = source._generate_prerelease(prerelease)
        return Version(
            base.major,
            base.minor,
            base.patch,
            prerelease_type=next_prerelease,
            prerelease_number=next_number,
            scheme=self.scheme,
        )

    @property
    def release(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def _increment_base(self, increment: Increment | None) -> "Version":
        major, minor, patch = self.release
        if increment == "MAJOR":
            return Version(major + 1, 0, 0, scheme=self.scheme)
        if increment == "MINOR":
            return Version(major, minor + 1, 0, scheme=self.scheme)
        if increment == "PATCH":
            return Version(major, minor, patch + 1, scheme=self.scheme)
        return Version(major, minor, patch, scheme=self.scheme)

    def _get_increment_base(
        self,
        increment: Increment | None,
        *,
        exact_increment: bool,
    ) -> "Version":
        if (
            not self.is_prerelease
            or exact_increment
            or (increment == "MINOR" and self.patch != 0)
            or (increment == "MAJOR" and (self.minor != 0 or self.patch != 0))
        ):
            return self._increment_base(increment)
        return Version(self.major, self.minor, self.patch, scheme=self.scheme)

    def _generate_prerelease(self, requested: Prerelease) -> tuple[Prerelease, int]:
        offset = 0
        if self.prerelease_type is not None and self.prerelease_number is not None:
            current_order = PRERELEASE_ORDER[self.prerelease_type]
            requested_order = PRERELEASE_ORDER[requested]
            if requested_order < current_order:
                requested = self.prerelease_type
            if requested == self.prerelease_type:
                offset = self.prerelease_number + 1
        return requested, offset


def detect_scheme(value: str) -> Scheme | None:
    """Return the scheme of `value` without raising."""
    try:
        return Version.parse(value).scheme
    except ConfigError:
        return None


def format_release_line_prerelease(
    release: tuple[int, int, int],
    prerelease_type: Prerelease,
    prerelease_number: int,
    scheme: Scheme = DEFAULT_SCHEME,
) -> str:
    """Format a prerelease string for `release` in the active scheme.

    Used for reasoning/behavior strings that need to talk about the version
    the bump *will* produce on a particular release line.
    """
    return str(
        Version(
            release[0],
            release[1],
            release[2],
            prerelease_type=prerelease_type,
            prerelease_number=prerelease_number,
            scheme=scheme,
        )
    )


@dataclass(frozen=True)
class BumpOptions:
    increment: Increment | None = None
    default_increment: Increment | None = None
    prerelease: Prerelease | None = None
    increment_mode: Literal["linear", "exact"] = "linear"
    allow_no_commit: bool = False
    check_consistency: bool = True
    dry_run: bool = False
    get_next: bool = False
    yes: bool = False
    create_tag: bool = True
    annotated_tag: bool = False
    gpg_sign: bool = False
    annotated_tag_message: str | None = None
    respect_git_config: bool = True
    major_version_zero: bool | None = None


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
        lines = text.splitlines(keepends=True)
        in_section = False
        section_seen = False

        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                in_section = stripped == self.section_header
                section_seen = section_seen or in_section
                continue

            if not in_section:
                continue

            match = VERSION_LINE_REGEX.match(line)
            if not match:
                continue

            actual_version = match.group(2)
            if check_consistency and actual_version != current_version:
                raise ConsistencyError(
                    f"{self.label} in {self.path} is {actual_version}, expected {current_version}."
                )

            if actual_version == new_version:
                return text, False

            line_ending = ""
            if line.endswith("\r\n"):
                line_ending = "\r\n"
            elif line.endswith("\n"):
                line_ending = "\n"

            suffix = match.group(3).rstrip("\r\n")
            lines[index] = f"{match.group(1)}{new_version}{suffix}{line_ending}"
            return "".join(lines), actual_version != new_version

        if not section_seen:
            raise ConfigError(f"Missing {self.section_header} in {self.path}.")
        raise ConfigError(f"Missing version field for {self.label} in {self.path}.")


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
        expected_current = version_to_uv_version(current_version)
        desired_new = version_to_uv_version(new_version)
        lines = text.splitlines(keepends=True)

        in_package_block = False
        matches_package = False
        package_found = False

        for index, line in enumerate(lines):
            stripped = line.strip()

            if stripped == "[[package]]":
                in_package_block = True
                matches_package = False
                continue

            if stripped.startswith("[[") and stripped != "[[package]]":
                in_package_block = False
                matches_package = False
                continue

            if not in_package_block:
                continue

            name_match = NAME_LINE_REGEX.match(line)
            if name_match:
                matches_package = name_match.group(2) == self.package_name
                package_found = package_found or matches_package
                continue

            if not matches_package:
                continue

            version_match = VERSION_LINE_REGEX.match(line)
            if not version_match:
                continue

            actual_version = version_match.group(2)
            if check_consistency and actual_version != expected_current:
                raise ConsistencyError(
                    f"{self.label} in {self.path} is {actual_version}, expected {expected_current}."
                )

            if actual_version == desired_new:
                return text, False

            line_ending = ""
            if line.endswith("\r\n"):
                line_ending = "\r\n"
            elif line.endswith("\n"):
                line_ending = "\n"

            suffix = version_match.group(3).rstrip("\r\n")
            lines[index] = (
                f"{version_match.group(1)}{desired_new}{suffix}{line_ending}"
            )
            return "".join(lines), actual_version != desired_new

        if not package_found:
            raise ConfigError(
                f"{self.label} in {self.path} does not contain package {self.package_name!r}."
            )
        raise ConfigError(
            f"{self.label} in {self.path} does not contain a version for package {self.package_name!r}."
        )


@dataclass(frozen=True)
class BumpConfig:
    root: Path
    current_version: Version
    current_version_text: str
    project_name: str | None
    tag_format: str
    major_version_zero: bool
    version_targets: tuple[VersionTarget, ...]


@dataclass(frozen=True)
class StrategyDecision:
    skip: bool
    invalid: bool
    mode: str = ""
    args: str = ""
    reason: str = ""
    error: str = ""
    branch: str = ""
    release_target: str = ""
    release_increment: str = ""
    hotfix_target: str = ""
    current_version: str = ""
    current_release_line: str = ""
    master_version: str = ""
    master_release_line: str = ""
    bootstrap_commitizen_version_ok: bool = False
    bootstrap_subject_ok: bool = False
    current_is_prerelease: bool = False
    bump_eligible: bool = False
    subject: str = ""
    branch_gate_ref: str = ""
    branch_has_unique_commits: bool = False
    create_tag: bool = True

    def outputs(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, bool):
                values[key] = "true" if value else "false"
            else:
                values[key] = value
        return values


class BumpGenerator(BaseGenerator):
    """Resolve interactive bump inputs and invoke the stdlib bump engine."""

    def __init__(
        self,
        increment: Optional[str] = None,
        default_increment: Optional[str] = None,
        prerelease: Optional[str] = None,
        increment_mode: str = "linear",
        allow_no_commit: bool = False,
        check_consistency: bool = True,
        dry_run: bool = False,
        get_next: bool = False,
        yes: bool = False,
        create_tag: bool = True,
        annotated_tag: bool = False,
        gpg_sign: bool = False,
        annotated_tag_message: Optional[str] = None,
        respect_git_config: bool = True,
        major_version_zero: Optional[bool] = None,
        interactive: bool = False,
    ):
        super().__init__(interactive=interactive)
        self._cli_increment = increment
        self._cli_default_increment = default_increment
        self._cli_prerelease = prerelease
        self._cli_increment_mode = increment_mode
        self._cli_allow_no_commit = allow_no_commit
        self._cli_check_consistency = check_consistency
        self._cli_dry_run = dry_run
        self._cli_get_next = get_next
        self._cli_yes = yes
        self._cli_create_tag = create_tag
        self._cli_annotated_tag = annotated_tag
        self._cli_gpg_sign = gpg_sign
        self._cli_annotated_tag_message = annotated_tag_message
        self._cli_respect_git_config = respect_git_config
        self._cli_major_version_zero = major_version_zero

    def generate_bump(self, *, cwd: Path | None = None) -> None:
        root = (cwd or Path.cwd()).resolve()
        if self._interactive:
            self._print_repo_context(root)

        options = self._build_options()

        if self._interactive and not options.get_next:
            self._print_summary(options)

        run_bump(options, cwd=root)

    def _build_options(self) -> BumpOptions:
        increment = self._cli_increment
        prerelease = self._cli_prerelease
        increment_mode = self._cli_increment_mode
        dry_run = self._cli_dry_run
        yes = self._cli_yes
        create_tag = self._cli_create_tag
        gpg_sign = self._cli_gpg_sign

        if self._interactive and not self._cli_get_next:
            if increment is None:
                increment_choice = self.prompt_select(
                    "Select version increment",
                    ["Auto-detect from commits", "PATCH", "MINOR", "MAJOR"],
                    default="Auto-detect from commits",
                )
                increment = None if increment_choice == "Auto-detect from commits" else increment_choice

            if prerelease is None:
                prerelease_choice = self.prompt_select(
                    "Select release channel",
                    ["Stable release", "alpha", "beta", "rc"],
                    default="Stable release",
                )
                prerelease = None if prerelease_choice == "Stable release" else prerelease_choice

            if prerelease is not None and self._cli_prerelease is None:
                increment_mode = self.prompt_select(
                    "Select prerelease increment mode",
                    ["linear", "exact"],
                    default=increment_mode,
                )

            if not self._cli_yes:
                yes = self.prompt_confirm(
                    "Treat a missing current-version tag as an initial tag if needed?",
                    default=False,
                )

            if not self._cli_gpg_sign:
                gpg_sign = self.prompt_confirm(
                    "Create a signed tag?",
                    default=False,
                )

            if not dry_run:
                dry_run = self.prompt_confirm(
                    "Preview only without changing files or git state?",
                    default=False,
                )

        return BumpOptions(
            increment=increment,
            default_increment=self._cli_default_increment,
            prerelease=prerelease,
            increment_mode=increment_mode,
            allow_no_commit=self._cli_allow_no_commit,
            check_consistency=self._cli_check_consistency,
            dry_run=dry_run,
            get_next=self._cli_get_next,
            yes=yes,
            create_tag=create_tag,
            annotated_tag=self._cli_annotated_tag,
            gpg_sign=gpg_sign,
            annotated_tag_message=self._cli_annotated_tag_message,
            respect_git_config=self._cli_respect_git_config,
            major_version_zero=self._cli_major_version_zero,
        )

    def _print_repo_context(self, root: Path) -> None:
        try:
            config = load_bump_config(root)
        except BumpError:
            return

        info(f"Current version: {config.current_version_text}")

    def _print_summary(self, options: BumpOptions) -> None:
        tag_behavior = "No tag"
        if options.create_tag:
            tag_behavior = "Respect git config"
            if options.gpg_sign:
                tag_behavior = "Signed tag"
            elif options.annotated_tag or options.annotated_tag_message is not None:
                tag_behavior = "Annotated tag"
            elif not options.respect_git_config:
                tag_behavior = "Ignore git tag config"

        lines = [
            f"Increment: {options.increment or 'auto-detect from commits'}",
            f"Default increment: {options.default_increment or 'none'}",
            f"Release channel: {options.prerelease or 'stable'}",
            f"Prerelease mode: {options.increment_mode}",
            f"Consistency check: {'on' if options.check_consistency else 'off'}",
            f"Tag behavior: {tag_behavior}",
            f"Preview only: {'yes' if options.dry_run else 'no'}",
        ]
        print_panel("\n".join(lines), title="Bump Settings")


def load_bump_config(root: Path) -> BumpConfig:
    cz_config_path, cz_settings = _load_commitizen_settings(root)
    pyproject_path = root / "pyproject.toml"
    pyproject_data = _read_toml(pyproject_path)

    commitizen_version = _read_nested_string(cz_settings, ("version",))
    commitizen_version_provider = _read_nested_string(cz_settings, ("version_provider",))
    commitizen_version_scheme = _read_nested_string(cz_settings, ("version_scheme",))
    pyproject_version = _read_nested_string(pyproject_data, ("project", "version"))
    project_name = _read_nested_string(pyproject_data, ("project", "name"))

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

    raw_version_files = cz_settings.get("version_files")
    if isinstance(raw_version_files, list):
        for spec in raw_version_files:
            if not isinstance(spec, str):
                continue
            for path, regex in _resolve_version_file_spec(root, spec, current_version_text):
                if path in auto_managed_paths:
                    continue
                targets.append(
                    PatternVersionTarget(
                        path=path,
                        label=f"version_files entry {spec}",
                        regex=regex,
                        strict_consistency=False,
                    )
                )

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


def detect_increment(
    commit_messages: list[str],
    *,
    major_version_zero: bool,
    default_increment: Increment | None = None,
) -> Increment | None:
    current: Increment | None = None
    priority = {None: -1, "PATCH": 0, "MINOR": 1, "MAJOR": 2}

    for message in commit_messages:
        if is_dvc_experiment_commit(message):
            continue

        for line in message.splitlines():
            match = DEFAULT_BUMP_PATTERN.search(line)
            if not match:
                continue

            found_keyword = match.group(1)
            detected: Increment | None = None
            for pattern, increment in BUMP_RULES:
                if pattern.match(found_keyword):
                    detected = increment
                    break

            if detected is None:
                detected = default_increment

            if detected == "MAJOR" and major_version_zero:
                detected = "MINOR"

            if detected is None:
                continue

            if priority[detected] > priority[current]:
                current = detected

            if current == "MAJOR":
                return current

    return current


def normalize_tag(version: Version, tag_format: str) -> str:
    template = Template(tag_format or DEFAULT_TAG_FORMAT)
    return template.safe_substitute(
        version=str(version),
        major=version.major,
        minor=version.minor,
        patch=version.patch,
        prerelease=version.prerelease or "",
    )


def version_to_uv_version(version: str | Version) -> str:
    """Convert supported versions to the form expected by uv.lock."""
    parsed = Version.parse(version) if isinstance(version, str) else version
    base = f"{parsed.major}.{parsed.minor}.{parsed.patch}"
    if not parsed.is_prerelease:
        return base
    assert parsed.prerelease_type is not None
    assert parsed.prerelease_number is not None
    short = SEMVER_PRERELEASE_SHORT_FROM_TYPE[parsed.prerelease_type]
    return f"{base}{short}{parsed.prerelease_number}"


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def normalize_workflow_subject(subject: str) -> str:
    stripped = subject.strip()
    match = GITHUB_PR_SUFFIX_PATTERN.fullmatch(stripped)
    if match is None:
        return stripped
    return match.group("subject")


def is_bootstrap_release_subject(subject: str) -> bool:
    return normalize_workflow_subject(subject) in BOOTSTRAP_RELEASE_SUBJECTS


def has_bootstrap_commitizen_version(root: Path) -> bool:
    data = _read_toml(root / ".cz.toml")
    return _read_nested_string(data, ("tool", "commitizen", "version")) == "0.0.1"


def parse_bump_subject_target_version(subject: str) -> str | None:
    match = BUMP_SUBJECT_TARGET_PATTERN.fullmatch(subject.strip())
    if match is None:
        return None
    return match.group("current")


def find_version_bump_commit(root: Path, version: str) -> str | None:
    result = run_command(
        ["git", "log", "--format=%H%x1f%s%x1e"],
        cwd=root,
    )
    for chunk in result.stdout.split("\x1e"):
        if not chunk.strip():
            continue
        commit_hash, _, subject = chunk.partition("\x1f")
        if parse_bump_subject_target_version(subject) == version:
            return commit_hash.strip() or None
    return None


def resolve_version_history_ref(
    root: Path,
    *,
    current_version: str,
    current_tag_name: str,
    tag_names: list[str],
    yes: bool,
) -> str | None:
    if current_tag_name in tag_names:
        return current_tag_name

    anchor_commit = find_version_bump_commit(root, current_version)
    if anchor_commit is not None:
        return anchor_commit

    if tag_names:
        raise ConfigError(
            "No tag matching the current version was found, and no prior bump commit "
            f"for version {current_version} exists in history. "
            "This usually means the configured version is stale or the version history "
            "was rewritten."
        )

    if not yes:
        raise ConfigError(
            "No tag matching the current version was found. "
            "Re-run with --yes to treat this as an initial untagged history."
        )

    return None


def build_git_tag_args(
    tag_name: str,
    *,
    annotated: bool,
    signed: bool,
    message: str | None,
    respect_git_config: bool,
) -> list[str]:
    args = ["git"]
    if not respect_git_config and not signed:
        args.extend(["-c", "tag.gpgSign=false"])
    args.append("tag")

    if signed:
        args.extend(["-s", tag_name, "-m", message or tag_name])
    elif annotated or message:
        args.extend(["-a", tag_name, "-m", message or tag_name])
    else:
        args.append(tag_name)
    return args


def resolve_git_tag_args(
    cwd: Path,
    tag_name: str,
    *,
    annotated: bool,
    signed: bool,
    message: str | None,
    respect_git_config: bool,
) -> list[str]:
    effective_signed = signed
    effective_message = message

    # `git tag <tag>` hangs under `tag.gpgSign=true` because Git upgrades the
    # operation to a signed annotated tag and opens the editor for TAG_EDITMSG.
    # Make that implicit Git behavior explicit only for this exact case.
    if respect_git_config and not signed and not annotated and message is None:
        if get_git_bool_config(cwd, "tag.gpgSign") is True:
            effective_signed = True
            effective_message = tag_name

    return build_git_tag_args(
        tag_name,
        annotated=annotated,
        signed=effective_signed,
        message=effective_message,
        respect_git_config=respect_git_config,
    )


def plan_version_file_updates(
    config: BumpConfig,
    new_version: Version,
    *,
    check_consistency: bool,
) -> dict[Path, str]:
    pending: dict[Path, str] = {}
    current_version = config.current_version_text
    new_version_text = str(new_version)

    for target in config.version_targets:
        text = pending.get(target.path)
        if text is None:
            text = target.path.read_text(encoding="utf-8")
        effective_check_consistency = check_consistency and getattr(
            target, "strict_consistency", True
        )
        updated_text, _ = target.apply(
            text,
            current_version=current_version,
            new_version=new_version_text,
            check_consistency=effective_check_consistency,
        )
        pending[target.path] = updated_text
    return pending


def decide_version_strategy(root: Path, branch: str, *, flow: Flow) -> StrategyDecision:
    last_commit = get_last_commit_message(root)
    subject = last_commit.splitlines()[0] if last_commit else ""
    current_config = load_bump_config(root)
    current_version = current_config.current_version_text
    current_version_parsed = current_config.current_version
    current_is_prerelease = current_version_parsed.is_prerelease
    current_release_line = _format_release_tuple(current_version_parsed.release)
    master_version = ""
    master_release_line = ""
    hotfix_target = ""
    release_increment = ""
    branch_gate_ref = ""
    branch_has_unique_commits = False
    bump_eligible = is_bump_eligible(last_commit)
    has_tags = bool(get_tag_names(root))
    release_match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
    release_target = release_match.group("target") if release_match else ""
    release_branch_error = ""
    hotfix_branch_error = ""
    bootstrap_commitizen_version_ok = has_bootstrap_commitizen_version(root)
    bootstrap_subject_ok = is_bootstrap_release_subject(subject)

    if branch.startswith("release/"):
        branch_has_unique_commits, branch_gate_ref = branch_has_unique_commits_since(
            root,
            ("origin/develop", "develop"),
        )
        if flow == "variant":
            master_version = load_version_from_refs(root, ("origin/master", "master"))
            master_release_line = _format_release_tuple(
                Version.parse(master_version).release
            )
            if not release_match:
                release_branch_error = (
                    "release branches must be named release/<x.y.z>, "
                    f"got {branch}"
                )
            else:
                release_increment = infer_release_increment(master_version, release_target) or ""
            if not release_branch_error and not release_increment:
                release_branch_error = (
                    f"release branch target {release_target} is not a valid "
                    f"MAJOR/MINOR/PATCH step from master version {master_release_line}"
                )
        else:
            if not release_match:
                release_branch_error = (
                    "release branches must be named release/<x.y.z>, "
                    f"got {branch}"
                )
            elif not current_is_prerelease:
                release_branch_error = (
                    "classic release branches must carry a prerelease on the "
                    f"selected line, got {current_version}"
                )
            elif release_target != current_release_line:
                release_branch_error = (
                    f"classic release branch target {release_target} does not match "
                    f"the current prerelease line {current_release_line}"
                )

    if branch.startswith("hotfix/"):
        master_version = load_version_from_refs(root, ("origin/master", "master"))
        master_release_line = _format_release_tuple(
            Version.parse(master_version).release
        )
        hotfix_target = next_patch_release_line(master_version)
        branch_has_unique_commits, branch_gate_ref = branch_has_unique_commits_since(
            root,
            ("origin/master", "master"),
        )
        if current_release_line == master_release_line:
            if current_is_prerelease:
                hotfix_branch_error = (
                    f"hotfix branches should start from stable master state, got {current_version}"
                )
        elif current_release_line == hotfix_target:
            if not current_is_prerelease:
                hotfix_branch_error = (
                    "hotfix branches must carry a prerelease after selecting "
                    f"the patch target line, got {current_version}"
                )
        else:
            hotfix_branch_error = (
                f"hotfix branch version line {current_release_line} does not align "
                f"with master {master_release_line} or next patch target {hotfix_target}"
            )

    decision = StrategyDecision(
        skip=False,
        invalid=False,
        branch=branch,
        release_target=release_target,
        release_increment=release_increment,
        hotfix_target=hotfix_target,
        current_version=current_version,
        current_release_line=current_release_line,
        master_version=master_version,
        master_release_line=master_release_line,
        bootstrap_commitizen_version_ok=bootstrap_commitizen_version_ok,
        bootstrap_subject_ok=bootstrap_subject_ok,
        current_is_prerelease=current_is_prerelease,
        bump_eligible=bump_eligible,
        subject=subject,
        branch_gate_ref=branch_gate_ref,
        branch_has_unique_commits=branch_has_unique_commits,
    )

    if subject == BACKMERGE_PREP_SUBJECT and (
        branch.startswith("release/") or branch.startswith("hotfix/")
    ):
        if not bump_eligible:
            return replace_decision(
                decision,
                skip=True,
                reason="backmerge prep commit is not bump-eligible",
            )
        if _version_is_alpha(current_version):
            return replace_decision(
                decision,
                mode="backmerge-prep-alpha",
                args="--yes --prerelease alpha --default-increment PATCH --no-tag",
                create_tag=False,
                reason="backmerge prep continues the current alpha line",
            )
        if current_is_prerelease:
            return replace_decision(
                decision,
                mode="backmerge-prep-rc",
                args="--yes --increment PATCH --prerelease rc --no-tag",
                create_tag=False,
                reason="backmerge prep continues the current rc line",
            )
        return replace_decision(
            decision,
            mode="backmerge-prep-start-rc",
            args="--yes --increment PATCH --prerelease rc --no-tag",
            create_tag=False,
            reason="backmerge prep starts rc on the stable base",
        )

    if subject.startswith(GENERATED_BUMP_PREFIX) and (
        release_branch_error or hotfix_branch_error
    ):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )

    if release_branch_error:
        return replace_decision(decision, invalid=True, error=release_branch_error)
    if hotfix_branch_error:
        return replace_decision(decision, invalid=True, error=hotfix_branch_error)
    if is_dvc_experiment_commit(last_commit):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by DVC experiment tracking",
        )
    if branch.startswith("feature/") or branch.startswith("bugfix/"):
        return replace_decision(
            decision,
            skip=True,
            reason="feature and bugfix branches do not publish versions",
        )
    if branch == "develop":
        return decide_develop_strategy(root, decision)
    if branch.startswith("release/"):
        if flow == "variant":
            return decide_variant_release_strategy(decision)
        return decide_classic_release_strategy(decision)
    if branch.startswith("hotfix/"):
        return decide_hotfix_strategy(decision)
    if branch == "master":
        return decide_master_strategy(decision, has_tags=has_tags, flow=flow)
    return replace_decision(
        decision,
        skip=True,
        reason=f"branch {branch} is not managed by this workflow",
    )


def decide_develop_strategy(root: Path, decision: StrategyDecision) -> StrategyDecision:
    workflow_subject = normalize_workflow_subject(decision.subject)
    if decision.subject.startswith(RELEASE_MANAGEMENT_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="release-management commits do not bump develop",
        )
    if decision.subject.startswith(GENERATED_BUMP_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )
    start_match = START_SUBJECT_PATTERN.fullmatch(workflow_subject)
    if start_match is not None:
        target = start_match.group("target")
        increment = infer_release_increment(decision.current_version, target)
        if decision.current_release_line == target or not increment:
            return replace_decision(
                decision,
                invalid=True,
                error=(
                    f"Start target {target} is not a valid next-cycle target from "
                    f"the current version line {decision.current_release_line}"
                ),
            )
        target_alpha = format_release_line_prerelease(
            release_tuple(target),
            "alpha",
            0,
            scheme=load_bump_config(root).current_version.scheme,
        )
        return replace_decision(
            decision,
            mode="develop-start-cycle",
            args=(
                f"--yes --increment {increment} --prerelease alpha "
                "--increment-mode exact"
            ),
            reason=f"Start {target} opens the next develop cycle as tagged {target_alpha}",
        )

    release_merge = RELEASE_MERGE_SUBJECT_PATTERN.fullmatch(workflow_subject)
    hotfix_merge = HOTFIX_MERGE_SUBJECT_PATTERN.fullmatch(workflow_subject)
    if release_merge or hotfix_merge:
        target = (
            release_merge.group("target")
            if release_merge is not None
            else hotfix_merge.group("target")
        )
        expected = (
            f"Backmerge Release {target}"
            if release_merge is not None
            else f"Backmerge Hotfix {target}"
        )
        kind = "release" if release_merge is not None else "hotfix"
        return replace_decision(
            decision,
            invalid=True,
            error=(
                f"{decision.subject} is reserved for {kind} promotion to master; "
                f"use {expected} for merge-back into develop"
            ),
        )

    backmerge_release = BACKMERGE_RELEASE_SUBJECT_PATTERN.fullmatch(workflow_subject)
    backmerge_hotfix = BACKMERGE_HOTFIX_SUBJECT_PATTERN.fullmatch(workflow_subject)
    if backmerge_release or backmerge_hotfix:
        kind = "release" if backmerge_release is not None else "hotfix"
        target = (
            backmerge_release.group("target")
            if backmerge_release is not None
            else backmerge_hotfix.group("target")
        )
        current_version = Version.parse(decision.current_version)
        target_rc_on_develop = (
            current_version.prerelease_type == "rc"
            and decision.current_release_line == target
        )
        if not decision.current_is_prerelease or target_rc_on_develop:
            if decision.current_release_line == target:
                if target_rc_on_develop:
                    return replace_decision(
                        decision,
                        mode=f"develop-backmerge-{kind}-stable",
                        args="--yes --no-tag",
                        reason=(
                            f"develop {kind} backmerge is not ahead yet, so it "
                            f"finalizes {target} release-candidate state to stable "
                            "without tagging"
                        ),
                        create_tag=False,
                    )
                return replace_decision(
                    decision,
                    skip=True,
                    reason=(
                        f"develop {kind} backmerge already matches stable line "
                        f"{target}; no develop bump needed"
                    ),
                )
            stable_catchup_increment = infer_release_increment(
                decision.current_version,
                target,
            )
            if stable_catchup_increment:
                return replace_decision(
                    decision,
                    mode=f"develop-backmerge-{kind}-stable",
                    args=(
                        f"--yes --increment {stable_catchup_increment} "
                        "--increment-mode exact --no-tag"
                    ),
                    reason=(
                        f"develop {kind} backmerge is not ahead yet, so it "
                        f"catches stable develop up to {target} without tagging"
                    ),
                    create_tag=False,
                )
        meaningful_changes = latest_commit_has_meaningful_changes(root)
        if not meaningful_changes:
            return replace_decision(
                decision,
                skip=True,
                reason=(
                    f"develop {kind} backmerge introduced no meaningful unique changes "
                    "beyond version-only or no-op updates"
                ),
            )
        return replace_decision(
            decision,
            mode=f"develop-backmerge-{kind}",
            args="--yes --increment PATCH --prerelease alpha --no-tag",
            reason=(
                f"develop {kind} backmerge keeps the ahead alpha line and advances "
                "alpha when meaningful unique changes land there"
            ),
            create_tag=False,
        )
    if decision.bump_eligible:
        return replace_decision(
            decision,
            mode="develop-alpha",
            args="--yes --prerelease alpha --default-increment PATCH",
            reason="develop creates or continues tagged alpha prereleases",
        )
    return replace_decision(
        decision,
        skip=True,
        reason="latest commit on develop is not bump-eligible",
    )


def decide_variant_release_strategy(decision: StrategyDecision) -> StrategyDecision:
    workflow_subject = normalize_workflow_subject(decision.subject)
    if workflow_subject.startswith(RELEASE_MANAGEMENT_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="release-management commit already promoted this release branch",
        )
    if not decision.branch_has_unique_commits:
        return replace_decision(
            decision,
            skip=True,
            reason="release branch has no unique human commit yet",
        )
    if workflow_subject.startswith(GENERATED_BUMP_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )
    if decision.current_release_line != decision.release_target:
        if decision.bump_eligible:
            return replace_decision(
                decision,
                mode="start-release-rc",
                args=(
                    f"--yes --increment {decision.release_increment} --prerelease rc "
                    "--increment-mode exact --gpg-sign"
                ),
                reason=(
                    f"release branch targets {decision.release_target} from master "
                    f"{decision.master_release_line}"
                ),
            )
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit on release branch is not bump-eligible",
        )
    if _version_is_alpha(decision.current_version):
        if decision.bump_eligible:
            return replace_decision(
                decision,
                mode="promote-alpha-to-rc",
                args="--yes --increment PATCH --prerelease rc --gpg-sign",
                reason="release branch promotes alpha to rc without changing the selected release line",
            )
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit on release branch does not require a version bump",
        )
    if not decision.current_is_prerelease:
        return replace_decision(
            decision,
            invalid=True,
            error=(
                "release branches must carry a prerelease after selecting the "
                f"target line, got {decision.current_version}"
            ),
        )
    if decision.bump_eligible:
        return replace_decision(
            decision,
            mode="release-rc",
            args="--yes --increment PATCH --prerelease rc --gpg-sign",
            reason="release branch continues the current rc line without reopening semver detection",
        )
    return replace_decision(
        decision,
        skip=True,
        reason="latest commit on release branch does not require a version bump",
    )


def decide_classic_release_strategy(decision: StrategyDecision) -> StrategyDecision:
    workflow_subject = normalize_workflow_subject(decision.subject)
    if workflow_subject.startswith(RELEASE_MANAGEMENT_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="release-management commit already promoted this release branch",
        )
    if not decision.branch_has_unique_commits:
        return replace_decision(
            decision,
            skip=True,
            reason="release branch has no unique human commit yet",
        )
    if workflow_subject.startswith(GENERATED_BUMP_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )
    if _version_is_alpha(decision.current_version):
        if decision.bump_eligible:
            return replace_decision(
                decision,
                mode="promote-alpha-to-rc",
                args="--yes --increment PATCH --prerelease rc --gpg-sign",
                reason="classic release branch promotes alpha to rc on the same selected line",
            )
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit on release branch does not require a version bump",
        )
    if decision.bump_eligible:
        return replace_decision(
            decision,
            mode="release-rc",
            args="--yes --increment PATCH --prerelease rc --gpg-sign",
            reason="classic release branch continues the current rc line without reopening semver detection",
        )
    return replace_decision(
        decision,
        skip=True,
        reason="latest commit on release branch does not require a version bump",
    )


def decide_hotfix_strategy(decision: StrategyDecision) -> StrategyDecision:
    if decision.subject.startswith(RELEASE_MANAGEMENT_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="release-management commits do not bump hotfix branches",
        )
    if not decision.branch_has_unique_commits:
        return replace_decision(
            decision,
            skip=True,
            reason="hotfix branch has no unique human commit yet",
        )
    if decision.subject.startswith(GENERATED_BUMP_PREFIX):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )
    if decision.current_release_line != decision.hotfix_target:
        if decision.bump_eligible:
            return replace_decision(
                decision,
                mode="start-hotfix-rc",
                args="--yes --increment PATCH --prerelease rc --gpg-sign",
                reason=(
                    f"hotfix branch selects patch release {decision.hotfix_target} from "
                    f"master {decision.master_release_line}"
                ),
            )
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit on hotfix branch is not bump-eligible",
        )
    if decision.bump_eligible:
        return replace_decision(
            decision,
            mode="hotfix-rc",
            args="--yes --increment PATCH --prerelease rc --gpg-sign",
            reason="hotfix branch continues the current patch rc line without reopening semver detection",
        )
    return replace_decision(
        decision,
        skip=True,
        reason="latest commit on hotfix branch is not bump-eligible",
    )


def decide_master_strategy(
    decision: StrategyDecision,
    *,
    has_tags: bool,
    flow: Flow,
) -> StrategyDecision:
    if (
        not decision.current_is_prerelease
        and decision.current_version == "0.0.1"
        and decision.bootstrap_commitizen_version_ok
        and not has_tags
        and decision.bootstrap_subject_ok
    ):
        return replace_decision(
            decision,
            mode="bootstrap-stable",
            args="--yes --increment MINOR --gpg-sign",
            reason="bootstrap commit promotes the initial baseline from 0.0.1 to 0.1.0",
        )
    if (
        not decision.current_is_prerelease
        and decision.current_version == "0.0.1"
        and decision.bootstrap_commitizen_version_ok
        and not has_tags
    ):
        return replace_decision(
            decision,
            invalid=True,
            error=(
                "bootstrap commit subject must be one of: "
                + ", ".join(sorted(BOOTSTRAP_RELEASE_SUBJECTS))
            ),
        )
    if decision.current_is_prerelease:
        return replace_decision(
            decision,
            mode="finalize-stable",
            args="--yes --gpg-sign",
            reason="master finalizes the current prerelease to stable",
        )
    if flow == "variant":
        reason = (
            "variant flow only finalizes prereleases on master; choose release/<target> "
            "or hotfix/** first"
        )
    else:
        reason = (
            "classic Git Flow only finalizes prereleases on master; choose release/** "
            "or hotfix/** first"
        )
    return replace_decision(decision, skip=True, reason=reason)


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


def load_version_from_refs(root: Path, refs: tuple[str, ...]) -> str:
    for ref in refs:
        result = run_command(
            ["git", "show", f"{ref}:.cz.toml"],
            cwd=root,
            check=False,
        )
        if result.returncode != 0:
            continue
        try:
            data = tomllib.loads(result.stdout)
        except tomllib.TOMLDecodeError:
            continue
        version = _read_nested_string(data, ("tool", "commitizen", "version"))
        if version is not None:
            return version
    raise ConfigError(f"No managed version found on refs: {', '.join(refs)}.")


def get_last_commit_message(root: Path) -> str:
    return run_command(
        ["git", "log", "-1", "--pretty=%B"],
        cwd=root,
    ).stdout.strip()


def branch_has_unique_commits_since(root: Path, refs: tuple[str, ...]) -> tuple[bool, str]:
    ref = resolve_git_ref(root, refs)
    count = run_command(
        ["git", "rev-list", "--count", f"{ref}..HEAD"],
        cwd=root,
    ).stdout.strip()
    return int(count or "0") > 0, ref


def resolve_git_ref(root: Path, refs: tuple[str, ...]) -> str:
    for ref in refs:
        result = run_command(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=root,
            check=False,
        )
        if result.returncode == 0:
            return ref
    raise ConfigError(f"Missing required git ref. Tried: {', '.join(refs)}.")


def next_patch_release_line(version: str) -> str:
    major, minor, patch = release_tuple(version)
    return f"{major}.{minor}.{patch + 1}"


def release_tuple(version: str) -> tuple[int, int, int]:
    parsed = Version.parse(version)
    return parsed.release


def _format_release_tuple(release: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in release)


def _version_is_alpha(value: str) -> bool:
    try:
        return Version.parse(value).prerelease_type == "alpha"
    except ConfigError:
        return False


def infer_release_increment(base_version: str, target_version: str) -> str | None:
    base = release_tuple(base_version)
    target = release_tuple(target_version)
    candidates = {
        "PATCH": (base[0], base[1], base[2] + 1),
        "MINOR": (base[0], base[1] + 1, 0),
        "MAJOR": (base[0] + 1, 0, 0),
    }
    for increment, candidate in candidates.items():
        if target == candidate:
            return increment
    return None


def latest_commit_changed_paths(root: Path) -> list[str]:
    parent_ref = run_command(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^"],
        cwd=root,
        check=False,
    )
    if parent_ref.returncode == 0:
        output = run_command(
            ["git", "diff", "--name-only", "HEAD^", "HEAD"],
            cwd=root,
        ).stdout
    else:
        output = run_command(
            [
                "git",
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "--root",
                "HEAD",
            ],
            cwd=root,
        ).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


def managed_version_paths(root: Path) -> set[str]:
    try:
        config = load_bump_config(root)
    except BumpError:
        return set()
    return {
        target.path.relative_to(root).as_posix()
        if target.path.is_absolute()
        else target.path.as_posix()
        for target in config.version_targets
    }


def latest_commit_has_meaningful_changes(root: Path) -> bool:
    changed_paths = latest_commit_changed_paths(root)
    if not changed_paths:
        return False

    version_paths = managed_version_paths(root)
    return any(path not in version_paths for path in changed_paths)


def is_dvc_experiment_commit(message: str) -> bool:
    subject = message.splitlines()[0].strip() if message.strip() else ""
    return bool(DVC_EXPERIMENT_COMMIT_PATTERN.match(subject))


def is_bump_eligible(message: str) -> bool:
    if is_dvc_experiment_commit(message):
        return False

    for line in message.splitlines():
        if DEFAULT_BUMP_PATTERN.search(line):
            return True
    return False


def replace_decision(decision: StrategyDecision, **changes: object) -> StrategyDecision:
    values = asdict(decision)
    values.update(changes)
    return StrategyDecision(**values)


def write_github_output(path: Path, decision: StrategyDecision) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in decision.outputs().items():
            handle.write(f"{key}={value}\n")


def run_bump(options: BumpOptions, *, cwd: Path | None = None) -> Version:
    root = (cwd or Path.cwd()).resolve()
    if not is_git_project(root):
        raise GitError(f"{root} is not a git repository.")

    config = load_bump_config(root)
    major_version_zero = (
        config.major_version_zero
        if options.major_version_zero is None
        else options.major_version_zero
    )

    tag_names = get_tag_names(root)
    current_tag_name = normalize_tag(config.current_version, config.tag_format)
    history_ref = resolve_version_history_ref(
        root,
        current_version=config.current_version_text,
        current_tag_name=current_tag_name,
        tag_names=tag_names,
        yes=options.yes,
    )

    commit_messages = get_commit_messages(root, start_ref=history_ref)
    increment = options.increment

    if increment is None:
        if (
            not commit_messages
            and not config.current_version.is_prerelease
            and not options.allow_no_commit
        ):
            raise NoCommitsFoundError("No new commits found.")
        increment = detect_increment(
            commit_messages,
            major_version_zero=major_version_zero,
            default_increment=options.default_increment,
        )

    if (
        options.prerelease is not None
        and increment is None
        and not config.current_version.is_prerelease
    ):
        raise NoCommitsFoundError(
            "No commits found to generate a prerelease. "
            "Specify --increment to force one."
        )

    if increment is None and options.allow_no_commit:
        increment = "PATCH"

    new_version = config.current_version.bump(
        increment,
        prerelease=options.prerelease,
        exact_increment=options.increment_mode == "exact",
    )

    new_tag_name = normalize_tag(new_version, config.tag_format)
    if increment is None and new_tag_name == current_tag_name:
        raise NoneIncrementError("The commits found are not eligible to be bumped.")

    if options.get_next:
        print(new_version)
        return new_version

    message = create_bump_message(config.current_version, new_version)
    print(message)
    if options.create_tag:
        print(f"tag to create: {new_tag_name}")
    else:
        print("tag creation skipped")
    if increment is not None:
        print(f"increment detected: {increment}")

    if options.dry_run:
        return new_version

    pending_updates = plan_version_file_updates(
        config,
        new_version,
        check_consistency=options.check_consistency,
    )

    updated_paths: list[Path] = []
    for path, contents in pending_updates.items():
        original = path.read_text(encoding="utf-8")
        if original == contents:
            continue
        path.write_text(contents, encoding="utf-8")
        updated_paths.append(path)

    if not updated_paths:
        raise ConfigError("No managed version files changed.")

    git_add(root, updated_paths)
    git_commit(root, message)
    if options.create_tag:
        git_tag(
            root,
            new_tag_name,
            annotated=options.annotated_tag or options.annotated_tag_message is not None,
            signed=options.gpg_sign,
            message=options.annotated_tag_message,
            respect_git_config=options.respect_git_config,
        )

    print("Done!")
    return new_version


def is_git_project(cwd: Path) -> bool:
    result = run_command(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def get_tag_names(cwd: Path) -> list[str]:
    result = run_command(["git", "tag", "--sort=-creatordate"], cwd=cwd)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_commit_messages(cwd: Path, start_ref: str | None) -> list[str]:
    if run_command(["git", "rev-parse", "--verify", "HEAD"], cwd=cwd, check=False).returncode != 0:
        return []

    args = ["git", "log", "--format=%B%x1e"]
    if start_ref:
        args.insert(2, f"{start_ref}..HEAD")
    result = run_command(args, cwd=cwd)
    return [chunk.strip() for chunk in result.stdout.split("\x1e") if chunk.strip()]


def git_add(cwd: Path, paths: list[Path]) -> None:
    args = ["git", "add", *[os.fspath(path.relative_to(cwd)) for path in paths]]
    run_command(args, cwd=cwd)


def git_commit(cwd: Path, message: str) -> None:
    run_command(["git", "commit", "-m", message], cwd=cwd)


def git_tag(
    cwd: Path,
    tag_name: str,
    *,
    annotated: bool,
    signed: bool,
    message: str | None,
    respect_git_config: bool,
) -> None:
    run_command(
        resolve_git_tag_args(
            cwd,
            tag_name,
            annotated=annotated,
            signed=signed,
            message=message,
            respect_git_config=respect_git_config,
        ),
        cwd=cwd,
    )


def create_bump_message(
    current_version: Version,
    new_version: Version,
    template: str = DEFAULT_BUMP_MESSAGE,
) -> str:
    return Template(template).safe_substitute(
        current_version=current_version,
        new_version=new_version,
    )


def run_command(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise GitError(f"{command}: {detail}")
    return result


def get_git_bool_config(cwd: Path, key: str) -> bool | None:
    result = run_command(
        ["git", "config", "--get", "--bool", key],
        cwd=cwd,
        check=False,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not value:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    return None


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

    resolved: list[tuple[Path, re.Pattern[str]]] = []
    for match in sorted(glob(os.fspath(root / pattern))):
        resolved.append((Path(match), re.compile(regex)))
    return resolved


def _parse_increment(value: str) -> Increment:
    upper = value.upper()
    if upper not in {"MAJOR", "MINOR", "PATCH"}:
        raise argparse.ArgumentTypeError(f"Unsupported increment: {value}")
    return upper  # type: ignore[return-value]


def _parse_prerelease(value: str) -> Prerelease:
    lower = value.lower()
    if lower not in {"alpha", "beta", "rc"}:
        raise argparse.ArgumentTypeError(f"Unsupported prerelease: {value}")
    return lower  # type: ignore[return-value]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git-tools bump",
        description="Minimal Commitizen-style version bumping.",
    )
    parser.add_argument("--increment", type=_parse_increment, help="Explicit MAJOR, MINOR, or PATCH increment.")
    parser.add_argument(
        "--default-increment",
        type=_parse_increment,
        help="Fallback MAJOR, MINOR, or PATCH increment for conventional commit types outside the built-in bump rules.",
    )
    parser.add_argument("--prerelease", type=_parse_prerelease, help="Create or continue an alpha, beta, or rc prerelease.")
    parser.add_argument(
        "--increment-mode",
        choices=("linear", "exact"),
        default="linear",
        help="Match Commitizen's linear or exact prerelease bump behavior.",
    )
    parser.add_argument("--allow-no-commit", action="store_true", help="Allow bumping even when no new commits are found.")
    parser.add_argument("--dry-run", action="store_true", help="Print the computed bump without changing files or git state.")
    parser.add_argument("--get-next", action="store_true", help="Print only the next version.")
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Treat a missing current-version tag as an initial tag only when the repository has no existing tags.",
    )
    parser.add_argument(
        "--no-tag",
        dest="create_tag",
        action="store_false",
        help="Skip git tag creation and use the last bump commit as the version baseline when needed.",
    )
    parser.add_argument("--annotated-tag", action="store_true", help="Create an annotated tag.")
    parser.add_argument("--gpg-sign", action="store_true", help="Create a signed tag.")
    parser.add_argument("--annotated-tag-message", help="Custom tag message for annotated or signed tags.")
    parser.add_argument(
        "--respect-git-config",
        dest="respect_git_config",
        action="store_true",
        help="Let git config such as tag.gpgSign affect tag creation.",
    )
    parser.add_argument(
        "--ignore-git-config",
        dest="respect_git_config",
        action="store_false",
        help="Ignore git config such as tag.gpgSign and force explicit tag behavior.",
    )
    parser.set_defaults(
        check_consistency=True,
        create_tag=True,
        major_version_zero=None,
        respect_git_config=True,
    )
    parser.add_argument(
        "--check-consistency",
        dest="check_consistency",
        action="store_true",
        help="Require all managed version fields to match before writing.",
    )
    parser.add_argument(
        "--no-check-consistency",
        dest="check_consistency",
        action="store_false",
        help="Allow managed version fields to be healed during the bump.",
    )
    parser.add_argument(
        "--major-version-zero",
        dest="major_version_zero",
        action="store_true",
        help="Treat breaking changes as MINOR while major is still zero.",
    )
    parser.add_argument(
        "--no-major-version-zero",
        dest="major_version_zero",
        action="store_false",
        help="Disable major-version-zero behavior from config for this run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    namespace = parser.parse_args(argv)
    options = BumpOptions(
        increment=namespace.increment,
        default_increment=namespace.default_increment,
        prerelease=namespace.prerelease,
        increment_mode=namespace.increment_mode,
        allow_no_commit=namespace.allow_no_commit,
        check_consistency=namespace.check_consistency,
        dry_run=namespace.dry_run,
        get_next=namespace.get_next,
        yes=namespace.yes,
        create_tag=namespace.create_tag,
        annotated_tag=namespace.annotated_tag,
        gpg_sign=namespace.gpg_sign,
        annotated_tag_message=namespace.annotated_tag_message,
        respect_git_config=namespace.respect_git_config,
        major_version_zero=namespace.major_version_zero,
    )

    try:
        run_bump(options)
    except BumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

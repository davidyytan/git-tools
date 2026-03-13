"""Minimal Commitizen-style version bumping with explicit tag control.

This module focuses on the core bump flow:
- read the current version from Commitizen and/or PEP 621 metadata
- detect the next increment from conventional commits
- compute the next semver2 version
- update managed version fields
- create the bump commit and tag

It intentionally stays stdlib-only so it can run in CI with:

    python -m git_tools.bump ...
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from glob import glob
from pathlib import Path
from string import Template
from typing import Literal

Increment = Literal["MAJOR", "MINOR", "PATCH"]
Prerelease = Literal["alpha", "beta", "rc"]
VersionSource = Literal["auto", "commitizen", "pyproject"]

DEFAULT_TAG_FORMAT = "$version"
DEFAULT_BUMP_MESSAGE = "bump: version $current_version → $new_version"
DEFAULT_BUMP_PATTERN = re.compile(r"^((BREAKING[\-\ ]CHANGE|\w+)(\(.+\))?!?):")
SEMVER2_REGEX = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<prerelease_type>alpha|beta|rc)\.(?P<prerelease_number>\d+))?$"
)
INLINE_SEMVER2_REGEX = re.compile(
    r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?"
)
VERSION_LINE_REGEX = re.compile(r'^(\s*version\s*=\s*")([^"]+)(".*)$')
NAME_LINE_REGEX = re.compile(r'^(\s*name\s*=\s*")([^"]+)(".*)$')
PRERELEASE_ORDER = {"alpha": 0, "beta": 1, "rc": 2}
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
class SemVer2Version:
    """A minimal semver2 implementation matching the subset used here."""

    major: int
    minor: int
    patch: int
    prerelease_type: Prerelease | None = None
    prerelease_number: int | None = None

    @classmethod
    def parse(cls, value: str) -> "SemVer2Version":
        match = SEMVER2_REGEX.fullmatch(value)
        if not match:
            raise ConfigError(f"Unsupported semver2 version: {value}")

        prerelease_type = match.group("prerelease_type")
        prerelease_number = match.group("prerelease_number")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease_type=prerelease_type,  # type: ignore[arg-type]
            prerelease_number=int(prerelease_number) if prerelease_number else None,
        )

    @property
    def is_prerelease(self) -> bool:
        return self.prerelease_type is not None

    @property
    def prerelease(self) -> str | None:
        if self.prerelease_type is None or self.prerelease_number is None:
            return None
        return f"{self.prerelease_type}.{self.prerelease_number}"

    @property
    def public(self) -> str:
        return str(self)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if not self.is_prerelease:
            return base
        return f"{base}-{self.prerelease}"

    def bump(
        self,
        increment: Increment | None,
        *,
        prerelease: Prerelease | None = None,
        exact_increment: bool = False,
    ) -> "SemVer2Version":
        base = self._get_increment_base(increment, exact_increment=exact_increment)
        if prerelease is None:
            return base

        source = self if self.release == base.release else base
        next_prerelease, next_number = source._generate_prerelease(prerelease)
        return SemVer2Version(
            base.major,
            base.minor,
            base.patch,
            prerelease_type=next_prerelease,
            prerelease_number=next_number,
        )

    @property
    def release(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def _increment_base(self, increment: Increment | None) -> "SemVer2Version":
        major, minor, patch = self.release
        if increment == "MAJOR":
            return SemVer2Version(major + 1, 0, 0)
        if increment == "MINOR":
            return SemVer2Version(major, minor + 1, 0)
        if increment == "PATCH":
            return SemVer2Version(major, minor, patch + 1)
        return SemVer2Version(major, minor, patch)

    def _get_increment_base(
        self,
        increment: Increment | None,
        *,
        exact_increment: bool,
    ) -> "SemVer2Version":
        if (
            not self.is_prerelease
            or exact_increment
            or (increment == "MINOR" and self.patch != 0)
            or (increment == "MAJOR" and (self.minor != 0 or self.patch != 0))
        ):
            return self._increment_base(increment)
        return SemVer2Version(self.major, self.minor, self.patch)

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
    annotated_tag: bool = False
    gpg_sign: bool = False
    annotated_tag_message: str | None = None
    respect_git_config: bool = True
    version_source: VersionSource = "auto"
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

            lines[index] = f"{match.group(1)}{new_version}{match.group(3)}{line_ending}"
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
                for match in INLINE_SEMVER2_REGEX.finditer(line)
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
        expected_current = semver2_to_uv_version(current_version)
        desired_new = semver2_to_uv_version(new_version)
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

            lines[index] = f"{version_match.group(1)}{desired_new}{version_match.group(3)}"
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
    current_version: SemVer2Version
    current_version_text: str
    project_name: str | None
    tag_format: str
    major_version_zero: bool
    version_targets: tuple[VersionTarget, ...]


def load_bump_config(root: Path, version_source: VersionSource = "auto") -> BumpConfig:
    cz_config_path, cz_settings = _load_commitizen_settings(root)
    pyproject_path = root / "pyproject.toml"
    pyproject_data = _read_toml(pyproject_path)

    commitizen_version = _read_nested_string(cz_settings, ("version",))
    pyproject_version = _read_nested_string(pyproject_data, ("project", "version"))
    project_name = _read_nested_string(pyproject_data, ("project", "name"))

    if version_source == "commitizen":
        if commitizen_version is None:
            raise ConfigError("No Commitizen version found in this repository.")
        current_version_text = commitizen_version
        current_version_origin = "commitizen"
    elif version_source == "pyproject":
        if pyproject_version is None:
            raise ConfigError("No [project].version found in pyproject.toml.")
        current_version_text = pyproject_version
        current_version_origin = "pyproject"
    else:
        if commitizen_version is not None:
            current_version_text = commitizen_version
            current_version_origin = "commitizen"
        elif pyproject_version is not None:
            current_version_text = pyproject_version
            current_version_origin = "pyproject"
        else:
            raise ConfigError("No managed version found in .cz.toml or pyproject.toml.")

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
                strict_consistency=current_version_origin == "commitizen",
            )
        )
        auto_managed_paths.add(cz_config_path)

    if pyproject_version is not None:
        targets.append(
            SectionVersionTarget(
                path=pyproject_path,
                label="PEP 621 project version",
                section_header="[project]",
                strict_consistency=current_version_origin == "pyproject",
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
        current_version=SemVer2Version.parse(current_version_text),
        current_version_text=current_version_text,
        project_name=project_name,
        tag_format=tag_format,
        major_version_zero=major_version_zero,
        version_targets=tuple(targets),
    )


def detect_increment(
    commit_messages: list[str],
    *,
    major_version_zero: bool,
    default_increment: Increment | None = None,
) -> Increment | None:
    current: Increment | None = None
    priority = {None: -1, "PATCH": 0, "MINOR": 1, "MAJOR": 2}

    for message in commit_messages:
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


def normalize_tag(version: SemVer2Version, tag_format: str) -> str:
    template = Template(tag_format or DEFAULT_TAG_FORMAT)
    return template.safe_substitute(
        version=str(version),
        major=version.major,
        minor=version.minor,
        patch=version.patch,
        prerelease=version.prerelease or "",
    )


def semver2_to_uv_version(version: str | SemVer2Version) -> str:
    parsed = SemVer2Version.parse(version) if isinstance(version, str) else version
    base = f"{parsed.major}.{parsed.minor}.{parsed.patch}"
    if not parsed.is_prerelease:
        return base

    prerelease_map = {
        "alpha": "a",
        "beta": "b",
        "rc": "rc",
    }
    assert parsed.prerelease_type is not None
    assert parsed.prerelease_number is not None
    return f"{base}{prerelease_map[parsed.prerelease_type]}{parsed.prerelease_number}"


def canonicalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


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
    new_version: SemVer2Version,
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


def run_bump(options: BumpOptions, *, cwd: Path | None = None) -> SemVer2Version:
    root = (cwd or Path.cwd()).resolve()
    if not is_git_project(root):
        raise GitError(f"{root} is not a git repository.")

    config = load_bump_config(root, version_source=options.version_source)
    major_version_zero = (
        config.major_version_zero
        if options.major_version_zero is None
        else options.major_version_zero
    )

    tag_names = get_tag_names(root)
    current_tag_name = normalize_tag(config.current_version, config.tag_format)
    current_tag_exists = current_tag_name in tag_names

    if not current_tag_exists:
        if tag_names:
            raise ConfigError(
                "No tag matching the current version was found. "
                "This usually means the configured version is stale, the tag format does not match, "
                "or the current version tag was never pushed. "
                "--yes only applies when bootstrapping the very first tag in an otherwise untagged repository."
            )
        if not options.yes:
            raise ConfigError(
                "No tag matching the current version was found. "
                "Re-run with --yes to treat this as an initial tag."
            )

    commit_messages = get_commit_messages(root, start_tag=current_tag_name if current_tag_exists else None)
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
    print(f"tag to create: {new_tag_name}")
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


def get_commit_messages(cwd: Path, start_tag: str | None) -> list[str]:
    if run_command(["git", "rev-parse", "--verify", "HEAD"], cwd=cwd, check=False).returncode != 0:
        return []

    args = ["git", "log", "--format=%B%x1e"]
    if start_tag:
        args.insert(2, f"{start_tag}..HEAD")
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
    current_version: SemVer2Version,
    new_version: SemVer2Version,
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
    for path in (root / ".cz.toml", root / "pyproject.toml"):
        data = _read_toml(path)
        tool = data.get("tool")
        if not isinstance(tool, dict):
            continue
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
        prog="python -m git_tools.bump",
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
    parser.add_argument(
        "--version-source",
        choices=("auto", "commitizen", "pyproject"),
        default="auto",
        help="Choose whether the current version comes from Commitizen config, pyproject metadata, or auto-detection.",
    )
    parser.set_defaults(
        check_consistency=True,
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
        annotated_tag=namespace.annotated_tag,
        gpg_sign=namespace.gpg_sign,
        annotated_tag_message=namespace.annotated_tag_message,
        respect_git_config=namespace.respect_git_config,
        version_source=namespace.version_source,
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

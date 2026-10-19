"""Version model spanning Commitizen ``semver`` and ``semver2`` schemes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .errors import ConfigError

Increment = Literal["MAJOR", "MINOR", "PATCH"]
Prerelease = Literal["alpha", "beta", "rc"]
Scheme = Literal["semver2", "semver"]

DEFAULT_SCHEME: Scheme = "semver2"

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

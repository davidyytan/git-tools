"""Version lookups from ``.cz.toml`` on the current branch or another ref."""

import subprocess
import tomllib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..bumpgen import BumpError, Version, load_bump_config
from .contexts import SEMVER_TUPLE_PATTERN


class VersionLookupMixin:
    """Read bump-config versions and relate base and target versions."""

    def _read_nested_string(self, data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
        current: object = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current if isinstance(current, str) else None

    def _load_current_branch_version(self) -> Optional[str]:
        try:
            config = load_bump_config(Path.cwd())
        except BumpError:
            return None
        return config.current_version_text

    def _load_version_from_ref(self, ref: str) -> Optional[str]:
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{ref}:.cz.toml"],
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

        try:
            data = tomllib.loads(raw)
        except tomllib.TOMLDecodeError:
            return None

        version = self._read_nested_string(data, ("tool", "commitizen", "version"))
        if version is not None:
            return version
        return None

    def _infer_target_transition(
        self,
        base_version: Version,
        target_version: Version,
    ) -> Optional[str]:
        for increment in ("PATCH", "MINOR", "MAJOR"):
            candidate = base_version.bump(increment)
            if str(candidate) == str(target_version):
                return increment

            for prerelease in ("alpha", "beta", "rc"):
                candidate = base_version.bump(increment, prerelease=prerelease)
                if str(candidate) == str(target_version):
                    return f"{increment} + {prerelease}"

        return None

    def _validate_semver_tuple(self, value: str, *, label: str) -> str:
        if not SEMVER_TUPLE_PATTERN.fullmatch(value):
            raise ValueError(f"{label} must be an exact release tuple X.Y.Z, got {value!r}.")
        return value

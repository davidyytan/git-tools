"""Repository-state queries that combine git history with ``.cz.toml``."""

from __future__ import annotations

import json
import tomllib
from dataclasses import replace
from pathlib import Path

from .config import _read_nested_string, load_bump_config
from .conventions import parse_bump_subject_target_version
from .errors import BumpError, ConfigError
from .git import latest_commit_changed_paths, run_command
from .targets import (
    CargoLockVersionTarget,
    CargoManifestVersionTarget,
    JsonVersionTarget,
    SectionVersionTarget,
    UvLockVersionTarget,
    VersionTarget,
)


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


def managed_version_paths(root: Path) -> set[str]:
    try:
        config = load_bump_config(root)
    except BumpError:
        return set()
    return {
        target.path.relative_to(config.root).as_posix()
        if target.path.is_absolute()
        else target.path.as_posix()
        for target in config.version_targets
    }


def _normalized_version_content(text: str, targets: list[VersionTarget]) -> object:
    """Erase only the fields the version adapters actually know how to update."""
    sentinel = "987654.321.0"
    for target in targets:
        if isinstance(target, CargoLockVersionTarget):
            # Discovery describes the working manifest's version. Each historical
            # lock blob instead needs its own unique local package version.
            packages = tomllib.loads(text).get("package", [])
            local = [p for p in packages if isinstance(p, dict)
                     and p.get("name") == target.package_name and "source" not in p]
            if len(local) != 1 or not isinstance(local[0].get("version"), str):
                raise ValueError("No unique local Cargo lock package")
            target = replace(target, package_version=local[0]["version"])
        text, _ = target.apply(
            text, current_version=sentinel, new_version=sentinel,
            check_consistency=False,
        )
    if any(isinstance(target, JsonVersionTarget) for target in targets):
        return json.loads(text)
    if any(isinstance(target, (CargoLockVersionTarget, CargoManifestVersionTarget,
                               SectionVersionTarget, UvLockVersionTarget))
           for target in targets):
        return tomllib.loads(text)
    return text


def latest_commit_has_meaningful_changes(root: Path) -> bool:
    """Ignore version-only edits, never entire managed manifests or lockfiles.

    Like ``latest_commit_changed_paths``, compare HEAD with its first parent.
    Unknown content and structural changes fail closed: they are meaningful.
    """
    root = root.resolve()
    changed_paths = latest_commit_changed_paths(root)
    if not changed_paths:
        return False

    try:
        config = load_bump_config(root)
        targets_by_path: dict[str, list[VersionTarget]] = {}
        for target in config.version_targets:
            path = target.path
            relative = path.relative_to(root) if path.is_absolute() else path
            targets_by_path.setdefault(relative.as_posix(), []).append(target)
        for path in changed_paths:
            targets = targets_by_path.get(path)
            if not targets:
                return True
            blobs = []
            modes = []
            for ref in ("HEAD^", "HEAD"):
                entry = run_command(["git", "ls-tree", ref, "--", path], cwd=root)
                mode = entry.stdout.split(maxsplit=1)[0] if entry.stdout else ""
                if mode not in {"100644", "100755"}:
                    return True
                modes.append(mode)
                text = run_command(["git", "show", f"{ref}:{path}"], cwd=root).stdout
                blobs.append(_normalized_version_content(text, targets))
            if modes[0] != modes[1] or blobs[0] != blobs[1]:
                return True
    except (BumpError, ValueError, OSError, TypeError, KeyError):
        return True
    return False

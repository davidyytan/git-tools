"""Repository-state queries that combine git history with ``.cz.toml``."""

from __future__ import annotations

import tomllib
from pathlib import Path

from .config import _read_nested_string, load_bump_config
from .conventions import parse_bump_subject_target_version
from .errors import BumpError, ConfigError
from .git import latest_commit_changed_paths, run_command


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

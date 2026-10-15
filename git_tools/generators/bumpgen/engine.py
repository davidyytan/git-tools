"""The stdlib-only bump engine: compute the next version, write it, commit, tag."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .config import BumpConfig, load_bump_config, normalize_tag
from .conventions import create_bump_message, detect_increment
from .errors import ConfigError, GitError, NoCommitsFoundError, NoneIncrementError
from .git import (
    get_commit_messages,
    get_tag_names,
    git_add,
    git_commit,
    git_tag,
    is_git_project,
)
from .repo import resolve_version_history_ref
from .targets import _is_core_version_path, _warn_auxiliary
from .version import Increment, Prerelease, Version


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
        try:
            text = pending.get(target.path)
            if text is None:
                text = target.path.read_text(encoding="utf-8")
            effective_check_consistency = check_consistency and _is_core_version_path(
                config.root, target.path
            )
            updated_text, _ = target.apply(
                text,
                current_version=current_version,
                new_version=new_version_text,
                check_consistency=effective_check_consistency,
            )
            pending[target.path] = updated_text
        except Exception as exc:
            if _is_core_version_path(config.root, target.path):
                raise
            _warn_auxiliary(target.path, exc)
    return pending


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
        try:
            original = path.read_text(encoding="utf-8")
            if original == contents:
                continue
            path.write_text(contents, encoding="utf-8")
            updated_paths.append(path)
        except Exception as exc:
            if _is_core_version_path(root, path):
                raise
            _warn_auxiliary(path, exc)

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

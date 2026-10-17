"""The stdlib-only bump engine: compute the next version, write it, commit, tag."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
import os
from pathlib import Path
from typing import Literal

from .config import BumpConfig, load_bump_config, normalize_tag
from .conventions import create_bump_message, detect_increment
from .errors import ConfigError, GitError, NoCommitsFoundError, NoneIncrementError
from .git import (
    describe_git_tag_behavior,
    get_commit_messages,
    get_tag_names,
    git_add,
    git_commit,
    git_tag,
    is_git_project,
    require_clean_index,
    run_command,
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


def _compute_bump(options: BumpOptions, *, cwd: Path | None = None) -> tuple[BumpConfig, Version, Increment | None]:
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

    return config, new_version, increment


@dataclass(frozen=True)
class FileUpdate:
    path: Path
    before: str
    after: str


@dataclass(frozen=True)
class BumpPlan:
    """A reviewed, in-memory plan; applying it never recomputes the bump."""

    config: BumpConfig
    options: BumpOptions
    new_version: Version
    increment: Increment | None
    message: str
    tag_name: str
    tag_behavior: str
    updates: tuple[FileUpdate, ...]
    repository_state: tuple[str, ...]
    source_files: tuple[tuple[Path, bytes | None, str], ...]


def _repository_state(root: Path) -> tuple[str, ...]:
    """History/ref/config authority that could invalidate the reviewed action."""
    commands = (
        ["git", "rev-parse", "--verify", "HEAD"],
        ["git", "symbolic-ref", "-q", "HEAD"],
        ["git", "show-ref", "--tags", "--dereference"],
        ["git", "config", "--null", "--list"],
    )
    return tuple(
        run_command(args, cwd=root, check=False).stdout for args in commands
    ) + (os.environ.get("GIT_TOOLS_BUMP_SYNC_AUXILIARY", ""),)


def _source_files(config: BumpConfig) -> tuple[tuple[Path, bytes | None, str], ...]:
    managed_paths = {target.path for target in config.version_targets}
    paths = set(managed_paths)
    # Metadata can affect discovery even if it is not itself a version target.
    names = (".cz.toml", "pyproject.toml", "uv.lock", "package.json", "package-lock.json",
             "npm-shrinkwrap.json", "Cargo.toml", "Cargo.lock")
    directories = [config.root]
    directories.extend(path for path in config.root.iterdir()
                       if not path.name.startswith(".") and not path.is_symlink()
                       and path.is_dir())
    for directory in directories:
        paths.update(directory / name for name in names)
    result = []
    for path in sorted(paths):
        try:
            if path.is_symlink() and path not in managed_paths:
                # Discovery ignores auxiliary symlinks. Record their identity
                # without following broken links, loops, or external targets.
                contents = None
                identity = f"symlink:{path.readlink()}"
            else:
                # Managed inputs are followed by the planner and writer, so a
                # symlink's destination bytes AND physical path must be frozen.
                contents = path.read_bytes() if path.exists() else None
                identity = str(path.resolve())
        except (OSError, RuntimeError) as exc:
            if _is_core_version_path(config.root, path):
                raise GitError(
                    f"Cannot snapshot authoritative config {path}: {exc}. "
                    "Check its file and symlink target, then retry; no bump files were changed."
                ) from exc
            # Optional/unreadable metadata must retain best-effort semantics.
            # A transition back to readable/resolvable input changes this state.
            contents = None
            identity = f"unreadable:{type(exc).__name__}:{exc}"
        result.append((path, contents, identity))
    return tuple(result)


def plan_bump(options: BumpOptions, *, cwd: Path | None = None) -> BumpPlan:
    root = (cwd or Path.cwd()).resolve()
    state = _repository_state(root)
    config, new_version, increment = _compute_bump(options, cwd=root)
    sources = _source_files(config)
    pending = plan_version_file_updates(config, new_version, check_consistency=options.check_consistency)
    updates = []
    for path, after in pending.items():
        before = path.read_text(encoding="utf-8")
        if before != after:
            updates.append(FileUpdate(path, before, after))
    if not updates:
        raise ConfigError("No managed version files changed.")
    if state != _repository_state(root) or sources != _source_files(config):
        raise GitError("Repository changed while preparing the bump plan. Retry; no bump files were changed.")
    return BumpPlan(
        config=config, options=options, new_version=new_version, increment=increment,
        message=create_bump_message(config.current_version, new_version),
        tag_name=normalize_tag(new_version, config.tag_format),
        tag_behavior=describe_git_tag_behavior(
            root, create_tag=options.create_tag, annotated=options.annotated_tag,
            signed=options.gpg_sign, message=options.annotated_tag_message,
            respect_git_config=options.respect_git_config,
        ),
        updates=tuple(updates), repository_state=state, source_files=sources,
    )


def print_bump_plan(plan: BumpPlan, *, show_diff: bool = True) -> None:
    print(f"Version: {plan.config.current_version_text} -> {plan.new_version}")
    print(plan.message)
    print(f"Tag behavior: {plan.tag_behavior}")
    if plan.options.create_tag:
        print(f"tag to create: {plan.tag_name}")
    else:
        print("tag creation skipped")
    if plan.increment is not None:
        print(f"increment detected: {plan.increment}")
    print("Commit scope: the managed files listed below (including any existing unstaged edits).")
    print("Planned file changes:")
    for update in plan.updates:
        name = str(update.path.relative_to(plan.config.root))
        print(f"  {name}")
        if show_diff:
            diff = unified_diff(update.before.splitlines(keepends=True),
                                update.after.splitlines(keepends=True),
                                fromfile=f"a/{name}", tofile=f"b/{name}")
            print("".join(diff), end="\n")
    print("Preview is write-free; hooks, signing and Git failures can only be checked when applying.")


def apply_bump_plan(plan: BumpPlan) -> Version:
    root = plan.config.root
    require_clean_index(root)
    if (plan.repository_state != _repository_state(root)
            or plan.source_files != _source_files(plan.config)
            or plan.config != load_bump_config(root)):
        raise GitError(
            "Bump plan is stale: HEAD, refs, files, configuration or Git settings changed. "
            "Retry to review a new plan. No bump files were changed."
        )
    updated_paths = []
    for update in plan.updates:
        try:
            update.path.write_text(update.after, encoding="utf-8")
            updated_paths.append(update.path)
        except Exception as exc:
            if _is_core_version_path(root, update.path):
                raise
            _warn_auxiliary(update.path, exc)
    if not updated_paths:
        raise ConfigError("No managed version files changed.")
    git_add(root, updated_paths)
    git_commit(root, plan.message)
    if plan.options.create_tag:
        git_tag(
            root, plan.tag_name,
            annotated=plan.options.annotated_tag or plan.options.annotated_tag_message is not None,
            signed=plan.options.gpg_sign, message=plan.options.annotated_tag_message,
            respect_git_config=plan.options.respect_git_config,
        )
    print("Done!")
    return plan.new_version


def run_bump(options: BumpOptions, *, cwd: Path | None = None) -> Version:
    root = (cwd or Path.cwd()).resolve()
    if options.get_next:
        _, new_version, _ = _compute_bump(options, cwd=root)
        print(new_version)
        return new_version
    if not options.dry_run:
        require_clean_index(root)
    plan = plan_bump(options, cwd=root)
    print_bump_plan(plan)
    if options.dry_run:
        return plan.new_version
    return apply_bump_plan(plan)

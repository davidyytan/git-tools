"""Thin git command wrappers used by the bump engine and strategy."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .errors import ConfigError, GitError


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


def require_clean_index(cwd: Path) -> None:
    """Never let a bump commit absorb changes staged by another operation."""
    # Presentation settings must not hide staged gitlinks from this safety check.
    result = run_command(
        ["git", "diff", "--cached", "--quiet", "--exit-code", "--ignore-submodules=none"],
        cwd=cwd, check=False,
    )
    if result.returncode == 1:
        raise GitError(
            "Staged changes are present. Unstage them before applying a bump "
            "(for example, git restore --staged .), then retry. No bump files were changed."
        )
    if result.returncode != 0:
        raise GitError("Cannot verify that the Git index is clean; no bump files were changed.")


def describe_git_tag_behavior(
    cwd: Path, *, create_tag: bool, annotated: bool, signed: bool,
    message: str | None, respect_git_config: bool,
) -> str:
    """Describe Git's effective action, including implicit configured signing."""
    if not create_tag:
        return "No tag"
    if signed:
        return "Signed annotated tag (explicit request)"
    if respect_git_config and get_git_bool_config(cwd, "tag.gpgSign") is True:
        return "Signed annotated tag (Git tag.gpgSign=true)"
    if annotated or message is not None:
        return "Annotated tag (unsigned)"
    return "Lightweight tag (unsigned)"


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

"""Publish a version commit and its exact tag; no hosting APIs or shell eval."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .bumpgen import load_bump_config, normalize_tag


class PublishError(RuntimeError):
    pass


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True,
                          timeout=120, env={**os.environ, "LC_ALL": "C"})


def checked(root: Path, *args: str) -> str:
    result = git(root, *args)
    if result.returncode:
        raise PublishError(f"Git operation failed: {' '.join(args[:2])}\n{result.stderr.strip()}")
    return result.stdout.strip()


def publish(root: Path, branch: str, create_tag: bool, remote: str = "origin",
            recover_tag: bool = False) -> None:
    if remote.startswith("-") or not remote:
        raise PublishError("Invalid remote name")
    branch_ref = f"refs/heads/{branch}"
    checked(root, "check-ref-format", branch_ref)
    head = checked(root, "rev-parse", "HEAD")
    tag_ref = None
    if create_tag or recover_tag:
        config = load_bump_config(root)
        tag = normalize_tag(config.current_version, config.tag_format)
        tag_ref = f"refs/tags/{tag}"
        checked(root, "check-ref-format", tag_ref)
        tagged = checked(root, "rev-parse", "--verify", f"{tag_ref}^{{commit}}")
        if tagged != head:
            raise PublishError("Expected version tag does not point to HEAD; refusing publication")
        print(f"Tag: {tag}", flush=True)
    print(f"Branch: {branch}", flush=True)
    if recover_tag:
        print("Publish mode: tag recovery (no branch update or version bump)", flush=True)
        remote_head = checked(root, "ls-remote", "--refs", remote, branch_ref).split()
        if not remote_head or remote_head[0] != head:
            raise PublishError("Recovery requires remote branch tip to equal local HEAD")
        checked(root, "push", remote, f"{tag_ref}:{tag_ref}")
        print("Result: expected tag published; no version bump performed", flush=True)
        return
    refs = [f"HEAD:{branch_ref}"]
    if tag_ref:
        refs.append(f"{tag_ref}:{tag_ref}")
    probe = git(root, "push", "--dry-run", "--atomic", remote, *refs)
    if probe.returncode == 0:
        print("Publish mode: atomic (dry run accepted)", flush=True)
        checked(root, "push", "--atomic", remote, *refs)
        print("Result: requested refs published atomically", flush=True)
        return
    unsupported = "does not support --atomic push" in probe.stderr.lower()
    if not unsupported:
        raise PublishError(f"Atomic dry run failed; no non-atomic fallback\n{probe.stderr.strip()}")
    print("Publish mode: non-atomic — server does not support atomic push", flush=True)
    checked(root, "push", remote, refs[0])
    print("Branch push: succeeded", flush=True)
    if tag_ref:
        try:
            checked(root, "push", remote, refs[1])
        except PublishError as exc:
            command = shlex.join(["python", "-m", "git_tools.generators.publish",
                                  "--branch", branch, "--remote", remote, "--recover-tag"])
            raise PublishError(f"Tag push failed after branch publication. Keep this checkout and its signed tag. "
                               f"Recovery required: inspect remote refs, then run {command}. "
                               f"Do not create another version bump.\n{exc}") from exc
        print("Tag push: succeeded", flush=True)
    print("Result: requested refs published non-atomically", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--create-tag", choices=("true", "false"), default="false")
    parser.add_argument("--recover-tag", action="store_true")
    args = parser.parse_args()
    try:
        publish(Path.cwd(), args.branch, args.create_tag == "true", args.remote, args.recover_tag)
    except (PublishError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"Publish failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

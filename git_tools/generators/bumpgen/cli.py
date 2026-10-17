"""Argparse front end for ``python -m git_tools.generators.bumpgen``."""

from __future__ import annotations

import argparse
import sys

from .engine import BumpOptions, run_bump
from .errors import BumpError
from .version import Increment, Prerelease


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
    parser.add_argument("--dry-run", action="store_true", help="Preview planned version files and diffs without changing files or Git state.")
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

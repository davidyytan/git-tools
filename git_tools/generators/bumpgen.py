"""Generator-backed CLI flow for version bumps."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from git_tools.bump import BumpError, BumpOptions, load_bump_config, run_bump

from .base import BaseGenerator, info, print_panel


class BumpGenerator(BaseGenerator):
    """Resolve interactive bump inputs and invoke the stdlib bump engine."""

    def __init__(
        self,
        increment: Optional[str] = None,
        default_increment: Optional[str] = None,
        prerelease: Optional[str] = None,
        increment_mode: str = "linear",
        allow_no_commit: bool = False,
        check_consistency: bool = True,
        dry_run: bool = False,
        get_next: bool = False,
        yes: bool = False,
        annotated_tag: bool = False,
        gpg_sign: bool = False,
        annotated_tag_message: Optional[str] = None,
        respect_git_config: bool = True,
        version_source: str = "auto",
        major_version_zero: Optional[bool] = None,
        interactive: bool = False,
    ):
        super().__init__(interactive=interactive)
        self._cli_increment = increment
        self._cli_default_increment = default_increment
        self._cli_prerelease = prerelease
        self._cli_increment_mode = increment_mode
        self._cli_allow_no_commit = allow_no_commit
        self._cli_check_consistency = check_consistency
        self._cli_dry_run = dry_run
        self._cli_get_next = get_next
        self._cli_yes = yes
        self._cli_annotated_tag = annotated_tag
        self._cli_gpg_sign = gpg_sign
        self._cli_annotated_tag_message = annotated_tag_message
        self._cli_respect_git_config = respect_git_config
        self._cli_version_source = version_source
        self._cli_major_version_zero = major_version_zero

    def generate_bump(self, *, cwd: Path | None = None) -> None:
        root = (cwd or Path.cwd()).resolve()
        if self._interactive:
            self._print_repo_context(root)

        options = self._build_options()

        if self._interactive and not options.get_next:
            self._print_summary(options)

        run_bump(options, cwd=root)

    def _build_options(self) -> BumpOptions:
        increment = self._cli_increment
        prerelease = self._cli_prerelease
        increment_mode = self._cli_increment_mode
        dry_run = self._cli_dry_run
        yes = self._cli_yes
        gpg_sign = self._cli_gpg_sign

        if self._interactive and not self._cli_get_next:
            if increment is None:
                increment_choice = self.prompt_select(
                    "Select version increment",
                    ["Auto-detect from commits", "PATCH", "MINOR", "MAJOR"],
                    default="Auto-detect from commits",
                )
                increment = None if increment_choice == "Auto-detect from commits" else increment_choice

            if prerelease is None:
                prerelease_choice = self.prompt_select(
                    "Select release channel",
                    ["Stable release", "alpha", "beta", "rc"],
                    default="Stable release",
                )
                prerelease = None if prerelease_choice == "Stable release" else prerelease_choice

            if prerelease is not None and self._cli_prerelease is None:
                increment_mode = self.prompt_select(
                    "Select prerelease increment mode",
                    ["linear", "exact"],
                    default=increment_mode,
                )

            if not self._cli_yes:
                yes = self.prompt_confirm(
                    "Treat a missing current-version tag as an initial tag if needed?",
                    default=False,
                )

            if not self._cli_gpg_sign:
                gpg_sign = self.prompt_confirm(
                    "Create a signed tag?",
                    default=False,
                )

            if not dry_run:
                dry_run = self.prompt_confirm(
                    "Preview only without changing files or git state?",
                    default=False,
                )

        return BumpOptions(
            increment=increment,
            default_increment=self._cli_default_increment,
            prerelease=prerelease,
            increment_mode=increment_mode,
            allow_no_commit=self._cli_allow_no_commit,
            check_consistency=self._cli_check_consistency,
            dry_run=dry_run,
            get_next=self._cli_get_next,
            yes=yes,
            annotated_tag=self._cli_annotated_tag,
            gpg_sign=gpg_sign,
            annotated_tag_message=self._cli_annotated_tag_message,
            respect_git_config=self._cli_respect_git_config,
            version_source=self._cli_version_source,
            major_version_zero=self._cli_major_version_zero,
        )

    def _print_repo_context(self, root: Path) -> None:
        try:
            config = load_bump_config(root, version_source=self._cli_version_source)
        except BumpError:
            return

        info(f"Current version: {config.current_version_text}")

    def _print_summary(self, options: BumpOptions) -> None:
        tag_behavior = "Respect git config"
        if options.gpg_sign:
            tag_behavior = "Signed tag"
        elif options.annotated_tag or options.annotated_tag_message is not None:
            tag_behavior = "Annotated tag"
        elif not options.respect_git_config:
            tag_behavior = "Ignore git tag config"

        lines = [
            f"Increment: {options.increment or 'auto-detect from commits'}",
            f"Default increment: {options.default_increment or 'none'}",
            f"Release channel: {options.prerelease or 'stable'}",
            f"Prerelease mode: {options.increment_mode}",
            f"Version source: {options.version_source}",
            f"Consistency check: {'on' if options.check_consistency else 'off'}",
            f"Tag behavior: {tag_behavior}",
            f"Preview only: {'yes' if options.dry_run else 'no'}",
        ]
        print_panel("\n".join(lines), title="Bump Settings")

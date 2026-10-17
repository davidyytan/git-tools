"""Interactive ``git-tools bump`` front end over the stdlib engine."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Optional

from .config import load_bump_config, normalize_tag
from .engine import BumpOptions, apply_bump_plan, plan_bump, print_bump_plan, run_bump
from .errors import BumpError
from .git import get_tag_names
from .repo import resolve_version_history_ref
from .ui import BaseGenerator, info, print_panel


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
        create_tag: bool = True,
        annotated_tag: bool = False,
        gpg_sign: bool = False,
        annotated_tag_message: Optional[str] = None,
        respect_git_config: bool = True,
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
        self._cli_create_tag = create_tag
        self._cli_annotated_tag = annotated_tag
        self._cli_gpg_sign = gpg_sign
        self._cli_annotated_tag_message = annotated_tag_message
        self._cli_respect_git_config = respect_git_config
        self._cli_major_version_zero = major_version_zero

    def generate_bump(self, *, cwd: Path | None = None) -> None:
        root = (cwd or Path.cwd()).resolve()
        if self._interactive:
            self._print_repo_context(root)

        options = self._build_options()

        if not self._interactive or options.get_next:
            run_bump(options, cwd=root)
            return

        prompted = self._cli_increment is None or self._cli_prerelease is None
        if not options.yes:
            config = load_bump_config(root)
            # Resolve with consent solely to determine whether consent is needed;
            # inconsistent tagged history still raises the existing refusal.
            history_ref = resolve_version_history_ref(
                root, current_version=config.current_version_text,
                current_tag_name=normalize_tag(config.current_version, config.tag_format),
                tag_names=get_tag_names(root), yes=True,
            )
            if history_ref is None:
                prompted = True
                if not self.prompt_confirm(
                    "No tags or prior bump anchor exist. Use the initial untagged history?",
                    default=False,
                ):
                    print()
                    info("Bump cancelled. No files or Git state changed.")
                    return
                options = replace(options, yes=True)

        plan = plan_bump(options, cwd=root)
        if prompted:
            print()
        self._print_summary(options, tag_behavior=plan.tag_behavior)
        print_bump_plan(plan, show_diff=options.dry_run)
        print()
        if options.dry_run:
            return
        action = self.prompt_select(
            "Choose action (Apply writes the listed files, commits, and creates the configured tag)",
            ["Preview", "Apply", "Cancel"], default="Preview",
        )
        print()
        if action == "Preview":
            print_bump_plan(plan)
            print()
            action = self.prompt_select(
                "Apply this reviewed plan or cancel?",
                ["Apply", "Cancel"], default="Cancel",
            )
            print()
        if action == "Apply":
            apply_bump_plan(plan)
        else:
            info("Bump cancelled. No files or Git state changed.")

    def _build_options(self) -> BumpOptions:
        increment = self._cli_increment
        prerelease = self._cli_prerelease
        increment_mode = self._cli_increment_mode
        dry_run = self._cli_dry_run
        yes = self._cli_yes
        create_tag = self._cli_create_tag
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
            create_tag=create_tag,
            annotated_tag=self._cli_annotated_tag,
            gpg_sign=gpg_sign,
            annotated_tag_message=self._cli_annotated_tag_message,
            respect_git_config=self._cli_respect_git_config,
            major_version_zero=self._cli_major_version_zero,
        )

    def _print_repo_context(self, root: Path) -> None:
        try:
            config = load_bump_config(root)
        except BumpError:
            return

        info(f"Current version: {config.current_version_text}")
        if not self._cli_get_next:
            print()

    def _print_summary(self, options: BumpOptions, *, tag_behavior: str) -> None:
        lines = [
            f"Increment: {options.increment or 'auto-detect from commits'}",
            f"Default increment: {options.default_increment or 'none'}",
            f"Release channel: {options.prerelease or 'stable'}",
            f"Prerelease mode: {options.increment_mode}",
            f"Consistency check: {'on' if options.check_consistency else 'off'}",
            f"Tag behavior: {tag_behavior}",
            f"Preview only: {'yes' if options.dry_run else 'no'}",
        ]
        print_panel("\n".join(lines), title="Bump Settings")

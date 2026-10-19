"""Generation type and PR mode selection."""


class GenerationModeMixin:
    """Resolve issue/PR/both and the fixed-title PR mode from CLI or prompts."""

    def select_generation_type(self) -> None:
        """Select what to generate.

        Uses CLI generation_type if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses default (already set in __init__)
        """
        # If CLI generation_type is set, use it directly (already set in __init__)
        if self._cli_generation_type is not None:
            return  # generation_type already set from CLI

        # Non-interactive mode: use default (already set in __init__)
        if not self._interactive:
            return

        # Interactive mode: prompt for selection
        choices = ["Issue", "Pull Request", "Both Issue + Pull Request"]
        choice = self.prompt_select("Select content to generate", choices, default="Pull Request")
        self.generation_type = {
            "Issue": "issue",
            "Pull Request": "pr",
            "Both Issue + Pull Request": "both",
        }.get(choice, "both")

    def resolve_pr_mode(self) -> None:
        """Resolve whether PR output should use develop or release guidance."""
        if self.generation_type not in {"pr", "both"}:
            self.release_pr = False
            self.hotfix_pr = False
            self.start_pr = False
            self.backmerge_release_pr = False
            self.backmerge_hotfix_pr = False
            return

        selected_modes = sum(
            1
            for flag in (
                self._cli_release_pr,
                self._cli_hotfix_pr,
                self._cli_start_pr,
                self._cli_backmerge_release_pr,
                self._cli_backmerge_hotfix_pr,
            )
            if flag
        )
        if selected_modes > 1:
            raise ValueError(
                "Use only one of start PR mode, release PR mode, hotfix PR mode, "
                "backmerge release PR mode, or backmerge hotfix PR mode."
            )

        if self._cli_release_pr is not None:
            self.release_pr = self._cli_release_pr
        else:
            self.release_pr = False

        if self._cli_hotfix_pr is not None:
            self.hotfix_pr = self._cli_hotfix_pr
        else:
            self.hotfix_pr = False

        if self._cli_start_pr is not None:
            self.start_pr = self._cli_start_pr
        else:
            self.start_pr = False

        if self._cli_backmerge_release_pr is not None:
            self.backmerge_release_pr = self._cli_backmerge_release_pr
        else:
            self.backmerge_release_pr = False

        if self._cli_backmerge_hotfix_pr is not None:
            self.backmerge_hotfix_pr = self._cli_backmerge_hotfix_pr
        else:
            self.backmerge_hotfix_pr = False

        if (
            self.release_pr
            or self.hotfix_pr
            or self.start_pr
            or self.backmerge_release_pr
            or self.backmerge_hotfix_pr
        ):
            return

        if not self._interactive:
            self.release_pr = False
            self.hotfix_pr = False
            self.start_pr = False
            self.backmerge_release_pr = False
            self.backmerge_hotfix_pr = False
            return

        choice = self.prompt_select(
            "Select PR mode",
            [
                "Ordinary PR",
                "Start PR",
                "Release PR",
                "Hotfix PR",
                "Backmerge Release PR",
                "Backmerge Hotfix PR",
            ],
            default="Ordinary PR",
        )
        self.start_pr = choice == "Start PR"
        self.release_pr = choice == "Release PR"
        self.hotfix_pr = choice == "Hotfix PR"
        self.backmerge_release_pr = choice == "Backmerge Release PR"
        self.backmerge_hotfix_pr = choice == "Backmerge Hotfix PR"

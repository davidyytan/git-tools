"""Commit-range inspection for the PR branch."""

import subprocess
from typing import Any, Dict, Optional, Union

from rich.panel import Panel

from ..base import ALIGN_PANEL, STYLE_BORDER, STYLE_DIM, STYLE_PRIMARY, console


class CommitHistoryMixin:
    """Summarize and extract the commits between the base branch and HEAD."""

    def get_commit_info(self, base_branch: str) -> Optional[Dict[str, Any]]:
        """Get commit range information between current and base branch.

        Args:
            base_branch: Name of the base branch to compare against

        Returns:
            Commit info with an exact merge-base range, or None for an empty range.

        Raises:
            ValueError: If the base is invalid or Git cannot compare the refs.
        """
        self._comparison_commit_info = None
        base_branch = self._validate_comparison_base_ref(base_branch)
        try:
            head_hash = subprocess.check_output(
                ["git", "rev-parse", "--verify", "HEAD^{commit}"], text=True, timeout=5
            ).strip()
            merge_base = subprocess.check_output(
                ["git", "merge-base", head_hash, base_branch], text=True, timeout=10
            ).strip()
            commit_range = f"{merge_base}..{head_hash}"
            commits = subprocess.check_output(
                ["git", "rev-list", commit_range], text=True, timeout=10
            ).splitlines()

            if not commits:
                return None

            def get_commit_message(commit_hash: str) -> str:
                return (
                    subprocess.check_output(
                        ["git", "log", "-1", "--pretty=%s", commit_hash],
                        text=True,
                        timeout=5,
                    )
                    .strip()
                    .split("\n")[0]
                )

            info = {
                "base_branch": base_branch,
                "merge_base": merge_base,
                "head_hash": head_hash,
                "commit_range": commit_range,
                "commit_hashes": commits,
                "commit_count": len(commits),
                "first_hash": commits[0][:7],
                "first_message": get_commit_message(commits[0]),
                "last_hash": commits[-1][:7],
                "last_message": get_commit_message(commits[-1]),
            }
            self._comparison_commit_info = info
            return info
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise ValueError(
                f"Could not compare HEAD with base {base_branch!r}. "
                "Ensure both refs have shared history available locally."
            ) from e

    def get_commit_messages(
        self, comparison: Union[Dict[str, Any], str, int]
    ) -> Optional[str]:
        """Get full messages for the exact range summarized by get_commit_info.

        Legacy count callers can reuse a previously inspected comparison, but a
        count alone must never select unrelated recent commits from HEAD.
        """
        if isinstance(comparison, int):
            info = getattr(self, "_comparison_commit_info", None)
            if comparison <= 0 or not info or info["commit_count"] != comparison:
                self.logger.error("An inspected commit range is required, not just a commit count")
                return None
        elif isinstance(comparison, dict):
            info = comparison
        else:
            info = {"commit_range": comparison}

        commit_range = info.get("commit_range")
        if not commit_range and info.get("base_branch"):
            # Compatibility for older callers that construct the summary dict.
            info = self.get_commit_info(info["base_branch"])
            commit_range = info.get("commit_range") if info else None
        if not commit_range:
            self.logger.error("An explicit commit range is required")
            return None

        try:
            messages = subprocess.check_output(
                ["git", "log", "--pretty=format:%B%x1e", commit_range, "--"],
                text=True,
                timeout=30,
            )

            full_messages = [
                msg.strip() for msg in messages.split("\x1e") if msg.strip()
            ]

            if not full_messages:
                self.logger.warning("No commit messages found")
                return None

            return "\n\n".join(full_messages)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error getting commit messages: {e}")
            return None
        except subprocess.TimeoutExpired:
            self.logger.error("Git log command timed out")
            return None

    def _resolve_commit_log_base_ref(self, base_branch: str) -> str:
        """Preserve the same explicit ref intent used by the comparison."""
        return self._validate_comparison_base_ref(base_branch)

    def get_pr_commit_log(self, base_branch: str) -> Optional[str]:
        """Get the formatted commit log for the PR branch range."""
        compare_ref = self._resolve_commit_log_base_ref(base_branch)
        pretty_format = (
            "--pretty=format:## %h %s%n%n"
            if self.release_pr
            else "--pretty=format:## %h %s%n%n%b%n"
        )

        try:
            log_output = subprocess.check_output(
                [
                    "git",
                    "log",
                    "--reverse",
                    pretty_format,
                    f"{compare_ref}..HEAD",
                ],
                text=True,
                timeout=30,
            ).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Error getting PR commit log: {e}")
            return None

        return log_output or None

    def show_commit_summary(self, info: Dict[str, Any]) -> None:
        """Display commit information to user.

        Args:
            info: Dictionary containing commit range information
        """
        current_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, timeout=5
        ).strip()

        summary = f"""Current branch:   [{STYLE_PRIMARY}]{current_branch}[/{STYLE_PRIMARY}]
Base branch:      [{STYLE_PRIMARY}]{info['base_branch']}[/{STYLE_PRIMARY}]
Total commits:    [{STYLE_PRIMARY}]{info['commit_count']}[/{STYLE_PRIMARY}]
First commit:     [{STYLE_DIM}]{info['first_hash']}[/{STYLE_DIM}] {info['first_message']}
Last commit:      [{STYLE_DIM}]{info['last_hash']}[/{STYLE_DIM}] {info['last_message']}"""

        console.print(Panel(summary.strip(), title="[bold]Commit Range Summary[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
        console.print()

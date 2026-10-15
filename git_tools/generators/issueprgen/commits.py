"""Commit-range inspection for the PR branch."""

import logging
import subprocess
from typing import Any, Dict, Optional

from rich.panel import Panel

from ..base import ALIGN_PANEL, STYLE_BORDER, STYLE_DIM, STYLE_PRIMARY, console

logger = logging.getLogger(__name__)


class CommitHistoryMixin:
    """Summarize and extract the commits between the base branch and HEAD."""

    def get_commit_info(self, base_branch: str) -> Optional[Dict[str, Any]]:
        """Get commit range information between current and base branch.

        Args:
            base_branch: Name of the base branch to compare against

        Returns:
            Dictionary with commit info or None if error occurs
        """
        try:
            merge_base = subprocess.check_output(
                ["git", "merge-base", "HEAD", base_branch], text=True, timeout=10
            ).strip()

            commits = subprocess.check_output(
                ["git", "rev-list", f"{merge_base}..HEAD"], text=True, timeout=10
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

            return {
                "base_branch": base_branch,
                "commit_count": len(commits),
                "first_hash": commits[0][:7],
                "first_message": get_commit_message(commits[0]),
                "last_hash": commits[-1][:7],
                "last_message": get_commit_message(commits[-1]),
            }
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Commit info error: {e}")
            return None

    def get_commit_messages(self, commit_count: int) -> Optional[str]:
        """Get commit messages from the last N commits."""
        if commit_count <= 0:
            self.logger.error("Commit count must be positive")
            return None

        try:
            messages = subprocess.check_output(
                ["git", "log", f"-{commit_count}", "--pretty=format:%B%x1e"],
                text=True,
                timeout=30,  # Add timeout to prevent hanging
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
        """Resolve the best ref to use for PR commit-log ranges."""
        for ref in (f"origin/{base_branch}", base_branch):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", ref],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return ref
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Commit log base ref {ref} not found")
                continue

        return base_branch

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

        console.print(Panel(summary.strip(), title="[bold]Commit Range Summary[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))

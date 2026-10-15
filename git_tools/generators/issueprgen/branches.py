"""Base-branch detection and validation against the local repository."""

import logging
import re
import subprocess

from ..base import warning

logger = logging.getLogger(__name__)


class BranchResolutionMixin:
    """Pick and validate the base branch for the comparison range."""

    def get_default_branch(self) -> str:
        """Get base branch, auto-detecting from git or defaulting to main.

        Uses CLI base_branch if provided. If not:
        - Interactive mode: prompts for input with auto-detected default
        - Non-interactive mode: uses auto-detected value

        Returns:
            Name of the base branch to compare against
        """
        # If CLI base_branch is provided, validate and use it
        if self._cli_base_branch is not None:
            return self._validate_branch_input(self._cli_base_branch)

        # Auto-detect the base branch
        if self.release_pr or self.hotfix_pr:
            auto_detected = self._default_release_base_branch()
        elif self.start_pr or self.backmerge_release_pr or self.backmerge_hotfix_pr:
            auto_detected = self._default_develop_base_branch()
        else:
            auto_detected = self._auto_detect_base_branch()

        # Non-interactive mode: use auto-detected value
        if not self._interactive:
            return auto_detected

        # Interactive mode: prompt for input
        user_input = self.prompt_text(
            f"Enter base branch name or commit hash",
            auto_detected,
        )

        if not user_input:
            return auto_detected

        # Validate user input - simple pattern check for safety
        if not re.match(r"^[a-zA-Z0-9/_.-]+$", user_input):
            logger.warning(f"Invalid branch name format: {user_input}")
            warning(f"Invalid branch format. Using default: {auto_detected}")
            return auto_detected

        # Validate if user input is a valid commit hash
        if len(user_input) >= 7:  # Git commit hashes are at least 7 characters
            try:
                # Try to validate as a commit hash
                subprocess.run(
                    ["git", "rev-parse", "--verify", user_input],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return user_input  # Valid commit hash
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                # Not a valid commit hash, treat as branch name
                pass

        # Validate if user input is a valid branch name
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{user_input}"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return user_input  # Valid branch name
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logger.warning(f"Branch {user_input} not found")
            warning(f"'{user_input}' not found. Using default: {auto_detected}")
            return auto_detected

    def _auto_detect_base_branch(self) -> str:
        """Auto-detect the base branch from git."""
        # First, try to find what branch we actually branched from
        try:
            # Get the reflog to find where we branched from
            reflog_result = subprocess.run(
                ["git", "reflog", "--oneline"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )

            # Look for the most recent "checkout: moving from" entry
            reflog_lines = reflog_result.stdout.strip().split("\n")
            for line in reflog_lines:
                if "checkout: moving from" in line:
                    # Extract the branch name we moved from
                    # Format: "abc1234 checkout: moving from main to feature-branch"
                    parts = line.split("checkout: moving from ")
                    if len(parts) > 1:
                        from_branch = parts[1].split(" to ")[0].strip()

                        # Verify this branch exists on remote
                        try:
                            subprocess.run(
                                [
                                    "git",
                                    "rev-parse",
                                    "--verify",
                                    f"origin/{from_branch}",
                                ],
                                capture_output=True,
                                check=True,
                                timeout=5,
                            )
                            return from_branch
                        except subprocess.CalledProcessError:
                            # Branch doesn't exist on remote, continue searching
                            logger.debug(f"Branch {from_branch} not found on remote")
                            continue
            else:
                # No valid branch found in reflog, fall back to remote default
                raise subprocess.CalledProcessError(1, "git reflog")

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        # Fallback: Try to get the default branch from git remote
        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return result.stdout.strip().split("/")[-1]
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        # Fallback to common branch names
        for branch in ["main", "master", "develop"]:
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", f"origin/{branch}"],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Branch {branch} not found")
                continue

        return "main"  # Ultimate fallback

    def _default_release_base_branch(self) -> str:
        """Return the default base branch for release-promotion PRs."""
        for branch in ("master", "main"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", f"origin/{branch}"],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Release base branch {branch} not found on remote")
                continue

        for branch in ("master", "main"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Release base branch {branch} not found locally")
                continue

        return "master"

    def _default_develop_base_branch(self) -> str:
        """Return the default base branch for workflow PRs that must land on develop."""
        for ref in ("origin/develop", "develop"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", ref],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return "develop"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Develop base ref {ref} not found")
                continue

        return "develop"

    def _require_develop_base_branch(self, base_branch: str, *, mode: str) -> None:
        if base_branch != "develop":
            raise ValueError(f"{mode} is for PRs into develop. Use --base develop.")

    def _get_current_branch_name(self) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            timeout=5,
        ).strip()

    def _validate_branch_input(self, branch_input: str) -> str:
        """Validate a branch name or commit hash from CLI.

        Args:
            branch_input: The branch name or commit hash to validate

        Returns:
            The validated branch/commit, or raises an error if invalid
        """
        # Validate format
        if not re.match(r"^[a-zA-Z0-9/_.-]+$", branch_input):
            logger.warning(f"Invalid branch name format: {branch_input}")
            raise ValueError(f"Invalid branch name format: {branch_input}")

        # Try as commit hash first
        if len(branch_input) >= 7:
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch_input],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch_input  # Valid commit hash
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                pass  # Not a commit hash, try as branch

        # Try as branch name
        try:
            subprocess.run(
                ["git", "rev-parse", "--verify", f"origin/{branch_input}"],
                capture_output=True,
                check=True,
                timeout=5,
            )
            return branch_input  # Valid branch name
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # Try without origin/ prefix (local branch)
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch_input],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch_input  # Valid local branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.warning(f"Branch {branch_input} not found, using as-is")
                return branch_input  # Use as-is, git will validate later

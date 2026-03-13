# git_tools/generators/issueprgen.py
"""Issue and Pull Request generator module.

Generates GitHub/GitLab issues and pull request descriptions from commit
history and code diffs using LLM providers.
"""

import logging
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.markup import escape

from git_tools.bump import BumpError, SemVer2Version, load_bump_config
from git_tools.config.config import settings
from git_tools.templates import get_issue_template, get_pr_template
from .base import (
    BaseGenerator, console, Panel, info, success, warning, error,
    STYLE_BORDER, STYLE_DIM, STYLE_SUCCESS, STYLE_PRIMARY, ALIGN_PANEL,
)

logger = logging.getLogger(__name__)
RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<version>\d+\.\d+\.\d+)$")
HOTFIX_BRANCH_PATTERN = re.compile(r"^hotfix/(?P<name>.+)$")
SYNC_BRANCH_PATTERN = re.compile(r"^sync/(?P<name>.+)$")
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_issuepr_prompt_block(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _format_release_tuple(release: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in release)


@dataclass(frozen=True)
class PromotionPrContext:
    current_branch: str
    base_branch: str
    target_version: str
    target_source: str
    base_version: str
    current_version: str
    inferred_transition: str
    promotion_kind: str

    def to_prompt_block(self) -> str:
        return _load_issuepr_prompt_block("issuepr_promotion_context.txt").format(
            promotion_kind=self.promotion_kind,
            current_branch=self.current_branch,
            base_branch=self.base_branch,
            target_version=self.target_version,
            target_source=self.target_source,
            base_version=self.base_version,
            current_version=self.current_version,
            inferred_transition=self.inferred_transition,
        )


class IssuePullRequestGenerator(BaseGenerator):
    def __init__(
        self,
        generation_type: Optional[str] = None,
        base_branch: Optional[str] = None,
        input_source: Optional[str] = None,
        release_pr: Optional[bool] = None,
        hotfix_pr: Optional[bool] = None,
        sync_pr: Optional[bool] = None,
        context: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        token_limit: Optional[int] = None,
        interactive: bool = False,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            interactive=interactive,
        )
        # Set generation_type from CLI or default to "issue"
        self.generation_type = generation_type if generation_type else "issue"
        self.issuepr_prompt = self._load_prompt_template("issuepr_prompt.txt")

        # CLI parameters for issue/pr-specific options
        self._cli_generation_type = generation_type
        self._cli_base_branch = base_branch
        self._cli_input_source = input_source
        self._cli_release_pr = release_pr
        self._cli_hotfix_pr = hotfix_pr
        self._cli_sync_pr = sync_pr
        self._cli_context = context
        self.release_pr = bool(release_pr)
        self.hotfix_pr = bool(hotfix_pr)
        self.sync_pr = bool(sync_pr)
        self._promotion_pr_context: PromotionPrContext | None = None

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
        elif self.sync_pr:
            auto_detected = self._default_sync_base_branch()
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

    def _default_sync_base_branch(self) -> str:
        """Return the default base branch for sync-back PRs."""
        for branch in ("develop", "main", "master"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", f"origin/{branch}"],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Sync base branch {branch} not found on remote")
                continue

        for branch in ("develop", "main", "master"):
            try:
                subprocess.run(
                    ["git", "rev-parse", "--verify", branch],
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                return branch
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                logger.debug(f"Sync base branch {branch} not found locally")
                continue

        return "develop"

    def _read_nested_string(self, data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[str]:
        current: object = data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current if isinstance(current, str) else None

    def _get_current_branch_name(self) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            timeout=5,
        ).strip()

    def _load_current_branch_version(self) -> Optional[str]:
        try:
            config = load_bump_config(Path.cwd())
        except BumpError:
            return None
        return config.current_version_text

    def _load_version_from_ref(self, ref: str) -> Optional[str]:
        for path, keys in (
            (".cz.toml", ("tool", "commitizen", "version")),
            ("pyproject.toml", ("project", "version")),
        ):
            try:
                raw = subprocess.check_output(
                    ["git", "show", f"{ref}:{path}"],
                    text=True,
                    timeout=5,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue

            try:
                data = tomllib.loads(raw)
            except tomllib.TOMLDecodeError:
                continue

            version = self._read_nested_string(data, keys)
            if version is not None:
                return version
        return None

    def _infer_target_transition(
        self,
        base_version: SemVer2Version,
        target_version: SemVer2Version,
    ) -> Optional[str]:
        for increment in ("PATCH", "MINOR", "MAJOR"):
            candidate = base_version.bump(increment)
            if str(candidate) == str(target_version):
                return increment

            for prerelease in ("alpha", "beta", "rc"):
                candidate = base_version.bump(increment, prerelease=prerelease)
                if str(candidate) == str(target_version):
                    return f"{increment} + {prerelease}"

        return None

    def _resolve_release_pr_context(self, base_branch: str) -> Optional[PromotionPrContext]:
        if not self.release_pr:
            return None

        current_branch = self._get_current_branch_name()
        base_version_text = self._load_version_from_ref(base_branch)
        current_version_text = self._load_current_branch_version()

        if base_version_text is None or current_version_text is None:
            return None

        base_version = SemVer2Version.parse(base_version_text)
        current_version = SemVer2Version.parse(current_version_text)
        match = RELEASE_BRANCH_PATTERN.fullmatch(current_branch)
        if not match:
            raise ValueError(
                "Release PR mode requires the current branch to be named release/<x.y.z>."
            )

        branch_target_text = match.group("version")
        branch_target_version = SemVer2Version.parse(branch_target_text)
        if current_version.release == branch_target_version.release:
            target_source = "current branch prerelease line and release branch name"
        else:
            target_source = "release branch name"

        target_version = branch_target_version
        target_version_text = str(target_version)

        inferred_transition = self._infer_target_transition(base_version, target_version)
        if inferred_transition is None:
            raise ValueError(
                f"Release target {target_version_text} is not a valid MAJOR/MINOR/PATCH step from {base_version_text} on {base_branch}."
            )

        return PromotionPrContext(
            current_branch=current_branch,
            base_branch=base_branch,
            target_version=target_version_text,
            target_source=target_source,
            base_version=base_version_text,
            current_version=current_version_text,
            inferred_transition=inferred_transition,
            promotion_kind="release",
        )

    def _resolve_hotfix_pr_context(self, base_branch: str) -> Optional[PromotionPrContext]:
        if not self.hotfix_pr:
            return None

        current_branch = self._get_current_branch_name()
        base_version_text = self._load_version_from_ref(base_branch)
        current_version_text = self._load_current_branch_version()

        if base_version_text is None or current_version_text is None:
            return None

        if not HOTFIX_BRANCH_PATTERN.fullmatch(current_branch):
            raise ValueError(
                "Hotfix PR mode requires the current branch to be named hotfix/<name>."
            )

        base_version = SemVer2Version.parse(base_version_text)
        current_version = SemVer2Version.parse(current_version_text)
        target_version = base_version.bump("PATCH")
        target_version_text = str(target_version)

        if current_version.release == base_version.release:
            if current_version.is_prerelease:
                raise ValueError(
                    f"Hotfix branch version {current_version_text} should start from the stable base version {base_version_text} before selecting the next patch target."
                )
            target_source = "next patch from base branch version"
        elif current_version.release == target_version.release:
            if current_version.is_prerelease:
                target_source = "current branch prerelease line and next patch from base branch version"
            else:
                target_source = "next patch from base branch version"
        else:
            raise ValueError(
                f"Hotfix branch version {current_version_text} does not align with the next patch target {target_version_text} from {base_version_text} on {base_branch}."
            )

        inferred_transition = self._infer_target_transition(base_version, target_version)
        if inferred_transition is None:
            raise ValueError(
                f"Hotfix target {target_version_text} is not a valid PATCH step from {base_version_text} on {base_branch}."
            )

        return PromotionPrContext(
            current_branch=current_branch,
            base_branch=base_branch,
            target_version=target_version_text,
            target_source=target_source,
            base_version=base_version_text,
            current_version=current_version_text,
            inferred_transition=inferred_transition,
            promotion_kind="hotfix",
        )

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
            self.sync_pr = False
            return

        selected_modes = sum(
            1
            for flag in (self._cli_release_pr, self._cli_hotfix_pr, self._cli_sync_pr)
            if flag
        )
        if selected_modes > 1:
            raise ValueError("Use only one of release PR mode, hotfix PR mode, or sync PR mode.")

        if self._cli_release_pr is not None:
            self.release_pr = self._cli_release_pr
        else:
            self.release_pr = False

        if self._cli_hotfix_pr is not None:
            self.hotfix_pr = self._cli_hotfix_pr
        else:
            self.hotfix_pr = False

        if self._cli_sync_pr is not None:
            self.sync_pr = self._cli_sync_pr
        else:
            self.sync_pr = False

        if self.release_pr or self.hotfix_pr or self.sync_pr:
            return

        if not self._interactive:
            self.release_pr = False
            self.hotfix_pr = False
            self.sync_pr = False
            return

        choice = self.prompt_select(
            "Select PR mode",
            ["Develop PR", "Release PR", "Hotfix PR", "Sync PR"],
            default="Develop PR",
        )
        self.release_pr = choice == "Release PR"
        self.hotfix_pr = choice == "Hotfix PR"
        self.sync_pr = choice == "Sync PR"

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
                ["git", "log", f"-{commit_count}", "--pretty=format:%B"],
                text=True,
                timeout=30,  # Add timeout to prevent hanging
            ).strip()

            if not messages:
                self.logger.warning("No commit messages found")
                return None

            # Split messages by commit and join with newlines
            full_messages = [
                msg.strip() for msg in messages.split("\n\n") if msg.strip()
            ]
            return "\n\n".join(full_messages)
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error getting commit messages: {e}")
            return None
        except subprocess.TimeoutExpired:
            self.logger.error("Git log command timed out")
            return None

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

    def _build_system_message(self, content: str, input_source: str) -> str:
        """Construct appropriate system message based on generation type and input source.

        Args:
            content: The content to generate from
            input_source: Source of input ('d' for diffs, 'c' for commits, 'b' for both)

        Returns:
            Formatted system message for the LLM
        """
        pr_template = self._build_pr_template()
        issue_template = get_issue_template()

        template_map = {
            "pr": pr_template,
            "issue": issue_template,
            "both": pr_template + "\n\n" + issue_template,
        }
        instruction_map = {
            "issue": self._load_prompt_template("issuepr_generation_issue.txt").strip(),
            "pr": self._load_prompt_template("issuepr_generation_pr.txt").strip(),
            "both": self._load_prompt_template("issuepr_generation_both.txt").strip(),
        }
        title_instruction_map = {
            "issue": self._load_prompt_template("issuepr_title_instruction_issue.txt").strip(),
            "pr": self._build_pr_title_instruction(),
            "both": self._build_both_title_instruction(),
        }
        focus_instruction = self._load_prompt_template(
            {
                "d": "issuepr_focus_instruction_diffs.txt",
                "c": "issuepr_focus_instruction_commits.txt",
            }.get(input_source, "issuepr_focus_instruction_both.txt")
        ).strip()

        return self.issuepr_prompt.format(
            generation_type_instruction=instruction_map[self.generation_type],
            template_content=template_map[self.generation_type],
            title_instruction=title_instruction_map[self.generation_type],
            focus_instruction=focus_instruction,
        )

    def _build_pr_template(self) -> str:
        return get_pr_template().format(title_block=self._build_pr_title_block())

    def _build_pr_title_block(self) -> str:
        fixed_title = self._resolve_fixed_pr_title()
        if fixed_title is not None:
            return f"## Title: {fixed_title}"

        placeholder_title = self._fixed_pr_title_placeholder()
        if placeholder_title is not None:
            return f"## Title: {placeholder_title}"

        return (
            "## Title: [Use a single Conventional Commit header for develop PRs]"
        )

    def _fixed_pr_title_placeholder(self) -> Optional[str]:
        if self.release_pr:
            return "Release <x.y.z>"
        if self.hotfix_pr:
            return "Hotfix <x.y.z>"
        if self.sync_pr:
            return "Sync <x.y.z>"
        return None

    def _build_pr_title_instruction(self) -> str:
        if self.release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_release.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Release <x.y.z>",
            ).strip()

        if self.hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Hotfix <x.y.z>",
            ).strip()

        if self.sync_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_sync.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Sync <x.y.z>",
            ).strip()

        return self._load_prompt_template(
            "issuepr_title_instruction_pr_default.txt"
        ).strip()

    def _build_both_title_instruction(self) -> str:
        if self.release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_release.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Release <x.y.z>",
            ).strip()

        if self.hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Hotfix <x.y.z>",
            ).strip()

        if self.sync_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_sync.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Sync <x.y.z>",
            ).strip()

        return self._load_prompt_template(
            "issuepr_title_instruction_both_default.txt"
        ).strip()

    def _build_full_prompt(self, content: str) -> str:
        """Build full prompt based on generation type."""
        prompt_map = {
            "both": self._load_prompt_template("issuepr_user_prompt_both.txt").strip(),
            "pr": self._load_prompt_template("issuepr_user_prompt_pr.txt").strip(),
            "issue": self._load_prompt_template("issuepr_user_prompt_issue.txt").strip(),
        }
        instruction = prompt_map.get(self.generation_type, prompt_map["both"])
        return f"{content}\n\n{instruction}"

    def _resolve_fixed_pr_title(self) -> Optional[str]:
        if self.release_pr:
            if self._promotion_pr_context is not None:
                return f"Release {self._promotion_pr_context.target_version}"
            branch = self._get_current_branch_name()
            match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
            if match:
                return f"Release {match.group('version')}"
            return None

        if self.hotfix_pr:
            if self._promotion_pr_context is not None:
                return f"Hotfix {self._promotion_pr_context.target_version}"
            base_branch = self._default_release_base_branch()
            base_version_text = self._load_version_from_ref(base_branch)
            if base_version_text is None:
                return None
            base_version = SemVer2Version.parse(base_version_text)
            return f"Hotfix {_format_release_tuple(base_version.bump('PATCH').release)}"

        if self.sync_pr:
            branch = self._get_current_branch_name()
            if not SYNC_BRANCH_PATTERN.fullmatch(branch):
                return None
            release_base = self._default_release_base_branch()
            release_version_text = self._load_version_from_ref(release_base)
            if release_version_text is None:
                return None
            release_version = SemVer2Version.parse(release_version_text)
            return f"Sync {_format_release_tuple(release_version.release)}"

        return None

    def _normalize_pr_output(self, content: str) -> str:
        normalized = content.strip()
        fixed_title = self._resolve_fixed_pr_title()

        if self.generation_type in {"pr", "both"}:
            normalized = re.sub(
                r"(?ms)^## Related Issue\s*\nIssue:.*?(?:\n{2,}|(?=## )|$)",
                "",
                normalized,
            ).strip()

        if fixed_title is None or self.generation_type not in {"pr", "both"}:
            return normalized

        title_line = f"## Title: {fixed_title}"
        if re.search(r"(?m)^## Title:.*$", normalized):
            return re.sub(r"(?m)^## Title:.*$", title_line, normalized, count=1).strip()

        return f"{title_line}\n\n{normalized}".strip()

    def generate_content(
        self, content: str, system_msg: str
    ) -> Optional[Dict[str, Any]]:
        """Generate content using LangChain chat client.

        Args:
            content: The content to generate from (diffs, commits, and/or user context)
            system_msg: System message with instructions and templates

        Returns:
            LLM response dictionary or None if failed
        """
        full_prompt = self._build_full_prompt(content)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": full_prompt},
        ]
        return self.invoke_llm(messages)

    def parse_generated_content(self, content: str) -> str:
        """Remove first and last lines from the generated content.

        Args:
            content: Raw content from LLM response

        Returns:
            Parsed content with first and last lines removed
        """
        lines = content.split("\n")
        if len(lines) > 2:
            return "\n".join(lines[1:-1])
        return content

    def generate_issue_pullrequest(self) -> None:
        """Main generation workflow.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults
        """
        # CLI mode: add leading blank line to separate from command
        if not self._interactive:
            console.print()

        self.select_generation_type()
        self.resolve_pr_mode()

        base_branch = self.get_default_branch()
        try:
            promotion_context = None
            if self.release_pr:
                promotion_context = self._resolve_release_pr_context(base_branch)
            elif self.hotfix_pr:
                promotion_context = self._resolve_hotfix_pr_context(base_branch)
            self._promotion_pr_context = promotion_context
        except ValueError as exc:
            error(str(exc))
            return

        commit_info = self.get_commit_info(base_branch)

        if (not commit_info or commit_info["commit_count"] < 1) and promotion_context is None:
            warning("No commits to generate from")
            return

        if commit_info and commit_info["commit_count"] >= 1:
            # Only add spacing if interactive (questionary → panel transition)
            if self._interactive:
                console.print()
            self.show_commit_summary(commit_info)
            # Only add spacing if interactive (panel → questionary transition)
            if self._interactive:
                console.print()

        # Input source: CLI param > interactive prompt > default ("b")
        if not commit_info or commit_info["commit_count"] < 1:
            input_source = "c"
            content = promotion_context.to_prompt_block() if promotion_context else ""
        else:
            if self._cli_input_source is not None:
                input_source = self._cli_input_source.lower()
                input_source = "b" if input_source not in ("d", "c", "b") else input_source
            elif self._interactive:
                source_choices = ["Diffs only", "Commit messages only", "Both diffs and commits"]
                source_choice = self.prompt_select("Select input source", source_choices, default="Both diffs and commits")
                input_source = {
                    "Diffs only": "d",
                    "Commit messages only": "c",
                    "Both diffs and commits": "b",
                }.get(source_choice, "b")
            else:
                input_source = "b"  # Default: both

            if input_source == "c":
                messages = self.get_commit_messages(commit_info["commit_count"])
                content_parts = []
                if messages:
                    content_parts.append(f"Commit Messages:\n```\n{messages}\n```")
                if promotion_context is not None:
                    content_parts.append(promotion_context.to_prompt_block())
                content = "\n\n".join(content_parts)
                if not content.strip():
                    warning("No commit messages to generate from")
                    return
            elif input_source == "b":
                messages = self.get_commit_messages(commit_info["commit_count"])
                max_token_count = self.get_diff_processing_params(
                    settings.default_issue_pr_token_limit
                )

                diffs = self.get_branch_diffs(commit_info["base_branch"], max_token_count)
                if not messages or not diffs:
                    warning("Missing data for generation")
                    return
                content_parts = [
                    f"Commit Messages:\n```\n{messages}\n```",
                    f"Code Diffs:\n```\n{diffs[0]}\n```",
                ]
                if promotion_context is not None:
                    content_parts.append(promotion_context.to_prompt_block())
                content = "\n\n".join(content_parts)

                # Display quota breakdown using unified method
                # Only add spacing if interactive (text → panel transition)
                if self._interactive:
                    console.print()
                self.display_quota_breakdown(diffs[1], max_token_count)
            else:
                max_token_count = self.get_diff_processing_params(
                    settings.default_issue_pr_token_limit
                )

                diffs = self.get_branch_diffs(commit_info["base_branch"], max_token_count)
                if not diffs:
                    warning("No diffs to generate from")
                    return
                content_parts = [f"Code Diffs:\n```\n{diffs[0]}\n```"]
                if promotion_context is not None:
                    content_parts.append(promotion_context.to_prompt_block())
                content = "\n\n".join(content_parts)

                # Display quota breakdown using unified method
                # Only add spacing if interactive (text → panel transition)
                if self._interactive:
                    console.print()
                self.display_quota_breakdown(diffs[1], max_token_count)

        # Add spacing before interactive prompts (after quota panel)
        if self._interactive:
            console.print()

        # Context: CLI param > interactive prompt > default (None)
        if self._cli_context is not None:
            context = self._cli_context
        elif self._interactive:
            if self.prompt_confirm("Add additional context?", default=False):
                context = self.prompt_text("Enter additional context").strip()
            else:
                context = None
        else:
            context = None  # Default: no context

        if context:
            content = (
                content
                + "\n\n"
                + "Here are some additional context to guide the diffs and/or commit messages. The generated content should try its best to use the context but stay faithful to the diffs and/or commit messages. Context is user intent but diffs and commit messages are the actual code changes."
                + "\n\n"
                + "Context:\n```\n"
                + context
                + "\n```"
            )

        system_msg = self._build_system_message(content, input_source)

        # In interactive mode, ask if user wants to use external providers
        # In non-interactive mode, always use external providers
        if self._interactive:
            if not self.prompt_confirm("Generate content using external providers?", default=True):
                full_prompt = system_msg + "\n\n" + self._build_full_prompt(content)
                self.ask_to_copy_to_clipboard(full_prompt)
                return

        # Provider initialization
        provider = self.select_provider()

        # Check API key - if not configured, offer setup or fall back to local mode
        if not self.ensure_api_key_configured(provider):
            info("Falling back to local mode...")
            full_prompt = system_msg + "\n\n" + self._build_full_prompt(content)
            self.copy_to_clipboard_auto(full_prompt)
            return

        model, temperature, max_tokens = self.select_model_params(provider)

        if not self._initialize_service(provider, model, temperature, max_tokens):
            return

        # Spacing before spinner only in interactive mode (Questionary → Spinner)
        # In CLI mode, Panel → Spinner → Panel, spinner disappears leaving Panel → Panel (no spacing)
        if self._interactive:
            console.print()
        response = self.generate_content(content, system_msg)
        if not response:
            error("Failed to generate content")
            return

        self.display_reasoning(response)
        console.print(Panel(escape(response["content"].strip()), title="[bold]Raw Response[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))

        parsed = self._normalize_pr_output(self.parse_generated_content(response["content"]))

        type_labels = {
            "pr": "PR Description",
            "issue": "Issue Description",
            "both": "Combined Output",
        }

        if parsed:
            console.print(Panel(escape(parsed.strip()), title=f"[bold]{type_labels.get(self.generation_type, 'Output')}[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))
        else:
            error_msgs = {
                "pr": "No valid PR content found",
                "issue": "No valid issue content found",
                "both": "No valid content found",
            }
            error(error_msgs.get(self.generation_type, "No valid content found"))
            return

        self.display_token_usage(response)

        # Panel → Questionary (interactive) needs spacing
        # CLI mode: copy_to_clipboard_auto handles its own spacing before success
        if self._interactive:
            console.print()
            self.ask_to_copy_to_clipboard(response["content"])
        else:
            self.copy_to_clipboard_auto(response["content"])
        return


def generate_issue_pullrequest() -> None:
    """Entry point for issue and pull request generation.

    Creates an IssuePullRequestGenerator instance and runs the generation workflow.
    """
    return IssuePullRequestGenerator().generate_issue_pullrequest()


if __name__ == "__main__":
    generate_issue_pullrequest()

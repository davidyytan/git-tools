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

from .bumpgen import (
    BumpError,
    Version,
    format_release_line_prerelease,
    infer_release_increment,
    load_bump_config,
    release_tuple,
)
from git_tools.config.config import settings
from git_tools.templates import get_issue_template, get_pr_template
from .base import (
    BaseGenerator, console, Panel, info, success, warning, error,
    STYLE_BORDER, STYLE_DIM, STYLE_SUCCESS, STYLE_PRIMARY, ALIGN_PANEL,
)

logger = logging.getLogger(__name__)
RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<version>\d+\.\d+\.\d+)$")
HOTFIX_BRANCH_PATTERN = re.compile(r"^hotfix/(?P<name>.+)$")
SEMVER_TUPLE_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
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


@dataclass(frozen=True)
class WorkflowPrContext:
    workflow_kind: str
    current_branch: str
    base_branch: str
    fixed_title: str
    target_version: str
    target_source: str
    base_version: str
    current_version: str
    behavior_summary: str

    def to_prompt_block(self) -> str:
        return _load_issuepr_prompt_block("issuepr_workflow_context.txt").format(
            workflow_kind=self.workflow_kind,
            current_branch=self.current_branch,
            base_branch=self.base_branch,
            fixed_title=self.fixed_title,
            target_version=self.target_version,
            target_source=self.target_source,
            base_version=self.base_version,
            current_version=self.current_version,
            behavior_summary=self.behavior_summary,
        )


class IssuePullRequestGenerator(BaseGenerator):
    def __init__(
        self,
        generation_type: Optional[str] = None,
        base_branch: Optional[str] = None,
        input_source: Optional[str] = None,
        release_pr: Optional[bool] = None,
        hotfix_pr: Optional[bool] = None,
        start_pr: Optional[bool] = None,
        backmerge_release_pr: Optional[bool] = None,
        backmerge_hotfix_pr: Optional[bool] = None,
        workflow_version: Optional[str] = None,
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
        self._cli_start_pr = start_pr
        self._cli_backmerge_release_pr = backmerge_release_pr
        self._cli_backmerge_hotfix_pr = backmerge_hotfix_pr
        self._cli_workflow_version = workflow_version
        self._cli_context = context
        self.release_pr = bool(release_pr)
        self.hotfix_pr = bool(hotfix_pr)
        self.start_pr = bool(start_pr)
        self.backmerge_release_pr = bool(backmerge_release_pr)
        self.backmerge_hotfix_pr = bool(backmerge_hotfix_pr)
        self._promotion_pr_context: PromotionPrContext | None = None
        self._workflow_pr_context: WorkflowPrContext | None = None

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
        try:
            raw = subprocess.check_output(
                ["git", "show", f"{ref}:.cz.toml"],
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

        try:
            data = tomllib.loads(raw)
        except tomllib.TOMLDecodeError:
            return None

        version = self._read_nested_string(data, ("tool", "commitizen", "version"))
        if version is not None:
            return version
        return None

    def _infer_target_transition(
        self,
        base_version: Version,
        target_version: Version,
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
        if base_branch not in {"master", "main"}:
            raise ValueError(
                "Release PR mode is for release/* -> master. "
                "Use backmerge release PR mode for release/* -> develop."
            )

        current_branch = self._get_current_branch_name()
        base_version_text = self._load_version_from_ref(base_branch)
        current_version_text = self._load_current_branch_version()

        if base_version_text is None or current_version_text is None:
            return None

        base_version = Version.parse(base_version_text)
        current_version = Version.parse(current_version_text)
        match = RELEASE_BRANCH_PATTERN.fullmatch(current_branch)
        if not match:
            raise ValueError(
                "Release PR mode requires the current branch to be named release/<x.y.z>."
            )

        branch_target_text = match.group("version")
        branch_target_version = Version.parse(branch_target_text)
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
        if base_branch not in {"master", "main"}:
            raise ValueError(
                "Hotfix PR mode is for hotfix/* -> master. "
                "Use backmerge hotfix PR mode for hotfix/* -> develop."
            )

        current_branch = self._get_current_branch_name()
        base_version_text = self._load_version_from_ref(base_branch)
        current_version_text = self._load_current_branch_version()

        if base_version_text is None or current_version_text is None:
            return None

        if not HOTFIX_BRANCH_PATTERN.fullmatch(current_branch):
            raise ValueError(
                "Hotfix PR mode requires the current branch to be named hotfix/<name>."
            )

        base_version = Version.parse(base_version_text)
        current_version = Version.parse(current_version_text)
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

    def _validate_semver_tuple(self, value: str, *, label: str) -> str:
        if not SEMVER_TUPLE_PATTERN.fullmatch(value):
            raise ValueError(f"{label} must be an exact release tuple X.Y.Z, got {value!r}.")
        return value

    def _resolve_workflow_target_version(
        self,
        *,
        label: str,
        inferred: Optional[str],
    ) -> str:
        if self._cli_workflow_version:
            return self._validate_semver_tuple(
                self._cli_workflow_version.strip(),
                label=label,
            )

        if self._interactive:
            default_value = inferred or ""
            value = self.prompt_text(f"Enter {label}", default_value).strip()
            if not value:
                raise ValueError(f"{label} is required for this PR mode.")
            return self._validate_semver_tuple(value, label=label)

        if inferred:
            return self._validate_semver_tuple(inferred, label=label)

        raise ValueError(
            f"Could not infer {label} from the current repo state. Pass --workflow-version."
        )

    def _infer_start_target_version(self) -> Optional[str]:
        current_branch = self._get_current_branch_name()
        release_branch = RELEASE_BRANCH_PATTERN.fullmatch(current_branch)
        if release_branch is not None:
            release_version = Version.parse(release_branch.group("version"))
            return f"{release_version.major}.{release_version.minor + 1}.0"

        current_version_text = self._load_current_branch_version()
        if current_version_text is None:
            return None

        current_version = Version.parse(current_version_text)
        return f"{current_version.major}.{current_version.minor + 1}.0"

    def _infer_hotfix_target_version(self) -> Optional[str]:
        base_branch = self._default_release_base_branch()
        base_version_text = self._load_version_from_ref(base_branch)
        current_version_text = self._load_current_branch_version()
        if base_version_text is None:
            return None

        base_version = Version.parse(base_version_text)
        target_version = base_version.bump("PATCH")

        if current_version_text is None:
            return _format_release_tuple(target_version.release)

        current_version = Version.parse(current_version_text)
        if current_version.release == target_version.release:
            return _format_release_tuple(current_version.release)

        return _format_release_tuple(target_version.release)

    def _resolve_start_pr_context(self, base_branch: str) -> Optional[WorkflowPrContext]:
        if not self.start_pr:
            return None
        self._require_develop_base_branch(base_branch, mode="Start PR mode")

        current_branch = self._get_current_branch_name()
        base_version_text = self._load_version_from_ref(base_branch)
        try:
            current_config = load_bump_config(Path.cwd())
        except BumpError:
            return None
        current_version_text = current_config.current_version_text
        if base_version_text is None:
            return None

        target_version = self._resolve_workflow_target_version(
            label="start target version",
            inferred=self._infer_start_target_version(),
        )
        inferred_transition = infer_release_increment(current_version_text, target_version)
        if inferred_transition is None:
            raise ValueError(
                f"Start target {target_version} is not a valid MAJOR/MINOR/PATCH step from {current_version_text} on {base_branch}."
            )

        target_alpha = format_release_line_prerelease(
            release_tuple(target_version),
            "alpha",
            0,
            scheme=current_config.current_version.scheme,
        )
        return WorkflowPrContext(
            workflow_kind="develop-start",
            current_branch=current_branch,
            base_branch=base_branch,
            fixed_title=f"Start {target_version}",
            target_version=target_version,
            target_source="repo version state and current branch context",
            base_version=base_version_text,
            current_version=current_version_text,
            behavior_summary=(
                f"Merging this PR should open {target_alpha} on develop. "
                "This PR may also contain the first real changes on that line, so "
                "summarize the actual changes normally while keeping the fixed Start title."
            ),
        )

    def _resolve_backmerge_release_pr_context(
        self,
        base_branch: str,
    ) -> Optional[WorkflowPrContext]:
        if not self.backmerge_release_pr:
            return None
        self._require_develop_base_branch(base_branch, mode="Backmerge release PR mode")

        current_branch = self._get_current_branch_name()
        branch_match = RELEASE_BRANCH_PATTERN.fullmatch(current_branch)
        inferred_target = branch_match.group("version") if branch_match else None
        target_version = self._resolve_workflow_target_version(
            label="backmerge release version",
            inferred=inferred_target,
        )
        base_version_text = self._load_version_from_ref(base_branch) or ""
        current_version_text = self._load_current_branch_version() or ""

        return WorkflowPrContext(
            workflow_kind="backmerge-release",
            current_branch=current_branch,
            base_branch=base_branch,
            fixed_title=f"Backmerge Release {target_version}",
            target_version=target_version,
            target_source=(
                "release branch name"
                if inferred_target is not None and inferred_target == target_version
                else "explicit workflow version input"
            ),
            base_version=base_version_text,
            current_version=current_version_text,
            behavior_summary=(
                "This is a backmerge into develop. If develop is already ahead on an "
                "alpha line, describe it as preserving that line and possibly "
                "advancing alpha by one for meaningful unique release fixes. If "
                "develop is not ahead yet, it may catch up to stable "
                f"{target_version} without tagging."
            ),
        )

    def _resolve_backmerge_hotfix_pr_context(
        self,
        base_branch: str,
    ) -> Optional[WorkflowPrContext]:
        if not self.backmerge_hotfix_pr:
            return None
        self._require_develop_base_branch(base_branch, mode="Backmerge hotfix PR mode")

        current_branch = self._get_current_branch_name()
        inferred_target = self._infer_hotfix_target_version()
        target_version = self._resolve_workflow_target_version(
            label="backmerge hotfix version",
            inferred=inferred_target,
        )
        base_version_text = self._load_version_from_ref(base_branch) or ""
        current_version_text = self._load_current_branch_version() or ""

        return WorkflowPrContext(
            workflow_kind="backmerge-hotfix",
            current_branch=current_branch,
            base_branch=base_branch,
            fixed_title=f"Backmerge Hotfix {target_version}",
            target_version=target_version,
            target_source=(
                "repo version state and current branch context"
                if inferred_target is not None and inferred_target == target_version
                else "explicit workflow version input"
            ),
            base_version=base_version_text,
            current_version=current_version_text,
            behavior_summary=(
                "This is a backmerge into develop. If develop is already ahead on an "
                "alpha line, describe it as preserving that line and possibly "
                "advancing alpha by one for meaningful unique hotfix fixes. If "
                "develop is not ahead yet, it may catch up to stable "
                f"{target_version} without tagging."
            ),
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
        if self.start_pr:
            return "Start <x.y.z>"
        if self.release_pr:
            return "Release <x.y.z>"
        if self.hotfix_pr:
            return "Hotfix <x.y.z>"
        if self.backmerge_release_pr:
            return "Backmerge Release <x.y.z>"
        if self.backmerge_hotfix_pr:
            return "Backmerge Hotfix <x.y.z>"
        return None

    def _build_pr_title_instruction(self) -> str:
        if self.start_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_start.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Start <x.y.z>",
            ).strip()

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

        if self.backmerge_release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_backmerge_release.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Release <x.y.z>",
            ).strip()

        if self.backmerge_hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_backmerge_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Hotfix <x.y.z>",
            ).strip()

        return self._load_prompt_template(
            "issuepr_title_instruction_pr_default.txt"
        ).strip()

    def _build_both_title_instruction(self) -> str:
        if self.start_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_start.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Start <x.y.z>",
            ).strip()

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

        if self.backmerge_release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_backmerge_release.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Release <x.y.z>",
            ).strip()

        if self.backmerge_hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_backmerge_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Hotfix <x.y.z>",
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
        if self.start_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            inferred_target = self._infer_start_target_version()
            return f"Start {inferred_target}" if inferred_target else None

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
            base_version = Version.parse(base_version_text)
            return f"Hotfix {_format_release_tuple(base_version.bump('PATCH').release)}"

        if self.backmerge_release_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            branch = self._get_current_branch_name()
            match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
            if match:
                return f"Backmerge Release {match.group('version')}"
            return None

        if self.backmerge_hotfix_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            inferred_target = self._infer_hotfix_target_version()
            return f"Backmerge Hotfix {inferred_target}" if inferred_target else None

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
            normalized = re.sub(
                r"(?m)^Next Develop:.*(?:\n|$)",
                "",
                normalized,
            ).strip()

        if fixed_title is None or self.generation_type not in {"pr", "both"}:
            return normalized

        title_line = f"## Title: {fixed_title}"
        if re.search(r"(?m)^## Title:.*$", normalized):
            normalized = re.sub(
                r"(?m)^## Title:.*$",
                title_line,
                normalized,
                count=1,
            ).strip()
        else:
            normalized = f"{title_line}\n\n{normalized}".strip()

        return normalized

    def _append_pr_commit_log(self, content: str, commit_log: Optional[str]) -> str:
        """Append the PR commit log block to final PR content."""
        normalized = content.strip()
        if not normalized or not commit_log:
            return normalized

        return f"{normalized}\n\n\n## Commits\n```sh\n{commit_log}\n```"

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
            workflow_pr_context = None
            if self.release_pr:
                promotion_context = self._resolve_release_pr_context(base_branch)
            elif self.hotfix_pr:
                promotion_context = self._resolve_hotfix_pr_context(base_branch)
            elif self.start_pr:
                workflow_pr_context = self._resolve_start_pr_context(base_branch)
            elif self.backmerge_release_pr:
                workflow_pr_context = self._resolve_backmerge_release_pr_context(base_branch)
            elif self.backmerge_hotfix_pr:
                workflow_pr_context = self._resolve_backmerge_hotfix_pr_context(base_branch)
            self._promotion_pr_context = promotion_context
            self._workflow_pr_context = workflow_pr_context
        except ValueError as exc:
            error(str(exc))
            return

        commit_info = self.get_commit_info(base_branch)

        fixed_context = promotion_context or workflow_pr_context

        if (not commit_info or commit_info["commit_count"] < 1) and fixed_context is None:
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
            content = fixed_context.to_prompt_block() if fixed_context else ""
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
                if fixed_context is not None:
                    content_parts.append(fixed_context.to_prompt_block())
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
                diff_text = diffs[0] if diffs else ""
                diff_has_content = bool(diff_text.strip())

                if not messages and not diff_has_content:
                    warning("Missing data for generation")
                    return

                content_parts = []
                if messages:
                    content_parts.append(f"Commit Messages:\n```\n{messages}\n```")
                if diff_has_content:
                    content_parts.append(f"Code Diffs:\n```\n{diff_text}\n```")
                elif messages:
                    warning(
                        "No code diffs found for this range; using commit messages only."
                    )
                if fixed_context is not None:
                    content_parts.append(fixed_context.to_prompt_block())
                content = "\n\n".join(content_parts)

                # Display quota breakdown using unified method
                # Only add spacing if interactive (text → panel transition)
                if diff_has_content and self._interactive:
                    console.print()
                if diff_has_content:
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
                if fixed_context is not None:
                    content_parts.append(fixed_context.to_prompt_block())
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
        pr_commit_log = (
            self.get_pr_commit_log(base_branch)
            if self.generation_type == "pr" and commit_info
            else None
        )
        display_output = parsed
        copy_output = response["content"]
        used_raw_fallback = False

        if self.generation_type == "pr":
            if parsed:
                display_output = self._append_pr_commit_log(parsed, pr_commit_log)
                copy_output = display_output
            else:
                raw_output = response["content"].strip()
                if raw_output:
                    display_output = self._append_pr_commit_log(raw_output, pr_commit_log)
                    copy_output = display_output
                    used_raw_fallback = True

        type_labels = {
            "pr": "PR Description",
            "issue": "Issue Description",
            "both": "Combined Output",
        }

        if display_output:
            if used_raw_fallback:
                warning("Parsed PR content was empty. Using raw model output instead.")
            console.print(Panel(escape(display_output.strip()), title=f"[bold]{type_labels.get(self.generation_type, 'Output')}[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))
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
            self.ask_to_copy_to_clipboard(copy_output)
        else:
            self.copy_to_clipboard_auto(copy_output)
        return


def generate_issue_pullrequest() -> None:
    """Entry point for issue and pull request generation.

    Creates an IssuePullRequestGenerator instance and runs the generation workflow.
    """
    return IssuePullRequestGenerator().generate_issue_pullrequest()


if __name__ == "__main__":
    generate_issue_pullrequest()

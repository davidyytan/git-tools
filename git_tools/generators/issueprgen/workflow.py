"""Start and backmerge PRs into develop, with their fixed-title targets."""

from pathlib import Path
from typing import Optional

from ..bumpgen import (
    BumpError,
    Version,
    format_release_line_prerelease,
    infer_release_increment,
    load_bump_config,
    release_tuple,
)
from .contexts import RELEASE_BRANCH_PATTERN, WorkflowPrContext, _format_release_tuple


class WorkflowContextMixin:
    """Infer target versions and build contexts for develop-bound workflow PRs."""

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

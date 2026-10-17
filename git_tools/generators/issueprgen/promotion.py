"""Release and hotfix promotion PRs (``release/*`` or ``hotfix/*`` into master)."""

from typing import Optional

from ..bumpgen import Version
from .contexts import HOTFIX_BRANCH_PATTERN, RELEASE_BRANCH_PATTERN, PromotionPrContext
from .branches import BranchResolutionMixin


class PromotionContextMixin:
    """Resolve the promotion context that steers release and hotfix PR text."""

    def _resolve_release_pr_context(self, base_branch: str) -> Optional[PromotionPrContext]:
        if not self.release_pr:
            return None
        if BranchResolutionMixin._base_branch_name(base_branch) not in {"master", "main"}:
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
        if BranchResolutionMixin._base_branch_name(base_branch) not in {"master", "main"}:
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

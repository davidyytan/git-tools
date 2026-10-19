"""Fixed-title PR context models and the branch/version patterns they share."""

import re
from dataclasses import dataclass

from ..base.prompts import PROMPTS_DIR

RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<version>\d+\.\d+\.\d+)$")
HOTFIX_BRANCH_PATTERN = re.compile(r"^hotfix/(?P<name>.+)$")
SEMVER_TUPLE_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


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

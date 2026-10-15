"""Issue and pull request generator.

Generates issues and pull request descriptions from commit history and code
diffs using LLM providers, with fixed-title modes for Git Flow workflow PRs.
"""

from .azure import (
    AZURE_PR_DESCRIPTION_INSTRUCTION,
    AZURE_PR_DESCRIPTION_LIMIT,
    count_ado_chars,
)
from .contexts import (
    HOTFIX_BRANCH_PATTERN,
    RELEASE_BRANCH_PATTERN,
    SEMVER_TUPLE_PATTERN,
    PromotionPrContext,
    WorkflowPrContext,
)
from .generator import IssuePullRequestGenerator, generate_issue_pullrequest

__all__ = [
    "AZURE_PR_DESCRIPTION_INSTRUCTION",
    "AZURE_PR_DESCRIPTION_LIMIT",
    "HOTFIX_BRANCH_PATTERN",
    "IssuePullRequestGenerator",
    "PromotionPrContext",
    "RELEASE_BRANCH_PATTERN",
    "SEMVER_TUPLE_PATTERN",
    "WorkflowPrContext",
    "count_ado_chars",
    "generate_issue_pullrequest",
]

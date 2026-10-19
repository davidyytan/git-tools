"""Commit message generator.

Generates conventional commit messages from staged git changes using LLM
providers, with sensitive-file checks and commit message format validation.
"""

from .generator import CommitGenerator, generate_commit
from .sensitive import SensitiveFileMatch
from .workflow import WORKFLOW_KIND_NORMAL, WORKFLOW_KIND_OPEN_RELEASE

__all__ = [
    "CommitGenerator",
    "SensitiveFileMatch",
    "WORKFLOW_KIND_NORMAL",
    "WORKFLOW_KIND_OPEN_RELEASE",
    "generate_commit",
]

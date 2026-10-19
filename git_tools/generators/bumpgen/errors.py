"""Exception hierarchy for the bump engine."""


class BumpError(RuntimeError):
    """Base class for bump-related failures."""


class ConfigError(BumpError):
    """Raised when the repo configuration cannot be interpreted safely."""


class GitError(BumpError):
    """Raised when a git command fails."""


class ConsistencyError(BumpError):
    """Raised when managed version locations do not agree."""


class NoCommitsFoundError(BumpError):
    """Raised when there are no commits eligible for a bump."""


class NoneIncrementError(BumpError):
    """Raised when commits exist but none produce a bump."""

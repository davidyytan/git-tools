"""Base-branch detection and validation against the local repository."""

import logging
import re
import subprocess
from typing import Optional

from ..base import warning

logger = logging.getLogger(__name__)


class BranchResolutionMixin:
    """Pick and validate the base branch for the comparison range."""

    def get_default_branch(self) -> str:
        """Return the exact usable base ref, without fetching or changing refs.

        Explicit CLI and interactive input share validation and preserve local
        intent. Inferred defaults prefer existing origin refs, but never HEAD.
        """
        if self._cli_base_branch is not None:
            return self._validate_branch_input(self._cli_base_branch)

        try:
            if self.release_pr or self.hotfix_pr:
                auto_detected = self._default_release_base_branch()
            elif self.start_pr or self.backmerge_release_pr or self.backmerge_hotfix_pr:
                auto_detected = self._default_develop_base_branch()
            else:
                auto_detected = self._auto_detect_base_branch()
        except ValueError:
            if not self._interactive:
                raise
            warning(
                "Could not infer a base branch. Enter an existing branch/ref or commit hash."
            )
            auto_detected = ""

        if not self._interactive:
            return auto_detected

        user_input = self.prompt_text(
            "Enter base branch name or commit hash", auto_detected
        )
        if auto_detected and (not user_input or user_input == auto_detected):
            return self._validate_comparison_base_ref(auto_detected)
        return self._validate_branch_input(user_input)

    def _ref_commit_hash(self, ref: str) -> Optional[str]:
        """Resolve only commit-ish objects; a blob/tree is not a usable base."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logger.debug("Base ref %s does not resolve to a commit", ref)
            return None

    @staticmethod
    def _base_branch_name(ref: str) -> str:
        """Get a branch label for mode checks, never for Git comparisons."""
        if ref.startswith("refs/heads/"):
            return ref.removeprefix("refs/heads/")
        if ref.startswith("refs/remotes/"):
            return ref.removeprefix("refs/remotes/").split("/", 1)[-1]
        return ref.removeprefix("origin/")

    def _unambiguous_ref(self, short_ref: str, full_ref: str) -> Optional[str]:
        """Keep familiar short names unless another ref shadows that name."""
        commit_hash = self._ref_commit_hash(full_ref)
        if commit_hash is None:
            return None
        if self._ref_commit_hash(short_ref) == commit_hash:
            return short_ref
        return full_ref

    def _validate_branch_input(self, branch_input: str) -> str:
        """Resolve explicit local/remote refs or commits, or raise ValueError.

        A bare local branch is intentional even when origin has a newer copy.
        Origin is a fallback only when the explicit local ref does not exist.
        """
        if (
            not re.fullmatch(r"[a-zA-Z0-9/_.-]+", branch_input)
            or branch_input.startswith("-")
            or ".." in branch_input
        ):
            raise ValueError(f"Invalid base branch name or commit hash: {branch_input!r}")

        if not branch_input.startswith("refs/"):
            # An explicitly qualified remote ref must not be shadowed by a
            # similarly named local branch. Other bare names prefer local heads.
            remote = self._unambiguous_ref(
                branch_input, f"refs/remotes/{branch_input}"
            )
            if remote is not None:
                # Fully qualify other remotes so mode checks can distinguish
                # their remote name from a slash-containing local branch.
                return remote if branch_input.startswith("origin/") else f"refs/remotes/{branch_input}"
            local = self._unambiguous_ref(branch_input, f"refs/heads/{branch_input}")
            if local is not None:
                return local

        if self._ref_commit_hash(branch_input) is not None:
            return branch_input
        if not branch_input.startswith(("refs/", "origin/")):
            remote = self._unambiguous_ref(
                f"origin/{branch_input}", f"refs/remotes/origin/{branch_input}"
            )
            if remote is not None:
                return remote

        raise ValueError(
            f"Base branch or commit {branch_input!r} was not found or is not a commit. "
            "Use --base with an existing local ref or refresh remote refs yourself."
        )

    def _validate_exact_base_ref(self, ref: str) -> str:
        """Validate an internal full ref, never an arbitrary revision expression."""
        if not ref.startswith("refs/"):
            raise ValueError(f"Expected an exact full base ref: {ref!r}")
        try:
            subprocess.run(
                ["git", "check-ref-format", ref],
                capture_output=True,
                check=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Invalid exact base ref: {ref!r}") from exc
        if self._ref_commit_hash(ref) is None:
            raise ValueError(f"Base ref {ref!r} was not found or is not a commit.")
        return ref

    def _validate_comparison_base_ref(self, base_ref: str) -> str:
        """Revalidate a resolved comparison ref without applying manual grammar."""
        if base_ref.startswith("refs/"):
            return self._validate_exact_base_ref(base_ref)
        return self._validate_branch_input(base_ref)

    def _inferred_base_ref(self, candidate: str, *, allow_head: bool = False) -> Optional[str]:
        """Exclude the current branch; fixed workflows may use a distinct equal tip."""
        current_branch = self._get_current_branch_name()
        if self._base_branch_name(candidate) in {current_branch, "HEAD"}:
            return None
        head_hash = self._ref_commit_hash("HEAD")
        refs = (
            (candidate,)
            if candidate.startswith(("refs/", "origin/"))
            else (f"origin/{candidate}", candidate)
        )
        for ref in refs:
            try:
                resolved = self._validate_branch_input(ref)
            except ValueError:
                # Git-discovered names need not fit the older manual-input
                # whitelist. Carry only a checked full ref, not a revision expression.
                full_ref = (
                    ref if ref.startswith("refs/")
                    else f"refs/remotes/{ref}" if ref.startswith("origin/")
                    else f"refs/heads/{ref}"
                )
                try:
                    resolved = self._validate_exact_base_ref(full_ref)
                except ValueError:
                    continue
            if allow_head or self._ref_commit_hash(resolved) != head_hash:
                return resolved
        return None

    def _auto_detect_base_branch(self) -> str:
        """Infer a usable base from reflog, origin's default, or common names."""
        try:
            result = subprocess.run(
                ["git", "reflog", "--oneline"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            for line in result.stdout.splitlines():
                if "checkout: moving from " not in line:
                    continue
                candidate = line.split("checkout: moving from ", 1)[1].split(" to ", 1)[0]
                resolved = self._inferred_base_ref(candidate.strip())
                if resolved is not None:
                    return resolved
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        try:
            result = subprocess.run(
                ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            # Do not discard path components in names such as team/integration.
            resolved = self._inferred_base_ref(result.stdout.strip())
            if resolved is not None:
                return resolved
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        for candidate in ("main", "master", "develop"):
            resolved = self._inferred_base_ref(candidate)
            if resolved is not None:
                return resolved
        raise ValueError("Could not infer a base branch different from HEAD. Pass --base <branch-or-commit>.")

    def _default_release_base_branch(self) -> str:
        """Return a real stable base, preferring existing remote-tracking refs."""
        for candidate in ("origin/master", "origin/main", "master", "main"):
            resolved = self._inferred_base_ref(candidate, allow_head=True)
            if resolved is not None:
                return resolved
        raise ValueError("Could not find a release base branch different from HEAD. Pass --base master or --base main.")

    def _default_develop_base_branch(self) -> str:
        """Return a real develop base, preferring its remote-tracking ref."""
        resolved = self._inferred_base_ref("develop", allow_head=True)
        if resolved is not None:
            return resolved
        raise ValueError("Could not find a develop base branch different from HEAD. Pass --base develop.")

    def _require_develop_base_branch(self, base_branch: str, *, mode: str) -> None:
        if self._base_branch_name(base_branch) != "develop":
            raise ValueError(f"{mode} is for PRs into develop. Use --base develop.")

    def _get_current_branch_name(self) -> str:
        return subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            timeout=5,
        ).strip()

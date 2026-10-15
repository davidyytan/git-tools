"""Git diff retrieval and token-budgeted diff truncation."""

import subprocess
from typing import Dict, List, Optional, Tuple

from git_tools.settings.settings import settings

from .tokens import _ENCODER, _escape_special_tokens, count_tokens


class DiffProcessingMixin:
    """Fetch staged or branch diffs and fit them into a token budget per file."""

    def get_staged_diff(self) -> Optional[str]:
        """Get staged changes using git diff.

        Returns:
            Staged diff content or None if error occurs
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--staged"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return result.stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Error getting git diff: {e}")
            return None

    def _process_diff_with_size_limiting(
        self, full_diff: str, max_token_count: Optional[int]
    ) -> Tuple[str, List[str]]:
        """Process a diff with optional size limiting and quota allocation.

        When context limit is exceeded, drops the smallest files above min_file_token_threshold
        first, working up the list until we fit within the limit. Then applies proportional
        allocation to remaining files.

        Args:
            full_diff: The complete diff content
            max_token_count: If set, truncates diffs to stay within this token count

        Returns:
            Tuple of (processed_diff, quota_breakdown)
        """
        # If no token count limit, return raw diff
        if max_token_count is None:
            return full_diff, []

        # Parse diff into files and drop LFS files
        file_diffs, dropped_lfs_files = self._parse_diff_files(full_diff)

        # Calculate total token count
        total_tokens = sum(count_tokens(diff) for _, diff in file_diffs)

        # If under limit, return full diff with quota breakdown (no dropping needed)
        if total_tokens <= max_token_count:
            return self._create_quota_breakdown_for_full_diff(
                file_diffs, max_token_count, full_diff, dropped_lfs_files
            )

        # Drop files to fit within context limit and calculate quotas
        file_quotas, dropped_files = self._calculate_proportional_quotas(
            file_diffs, max_token_count
        )
        truncated_diffs = self._truncate_diffs_to_quotas(file_diffs, file_quotas)
        quota_breakdown = self._create_detailed_quota_breakdown(
            file_diffs, file_quotas, dropped_files, dropped_lfs_files
        )

        return "\n\n".join(truncated_diffs), quota_breakdown

    def _parse_diff_files(
        self, full_diff: str
    ) -> Tuple[List[Tuple[str, str]], List[str]]:
        """Parse diff content into individual file diffs, dropping LFS files completely.

        Returns:
            Tuple of (file_diffs, dropped_lfs_files)
            - file_diffs: List of (filename, diff) tuples (LFS files excluded)
            - dropped_lfs_files: List of LFS filenames that were dropped
        """
        if not full_diff.strip():
            return [], []

        file_diffs = []
        current_file = []
        current_file_name = None
        is_lfs_file = False
        dropped_lfs_files = []

        for line in full_diff.split("\n"):
            if line.startswith("diff --git"):
                if current_file and not is_lfs_file:
                    # Only add non-LFS files
                    file_diffs.append((current_file_name, "\n".join(current_file)))
                elif is_lfs_file:
                    dropped_lfs_files.append(current_file_name)

                current_file = [line]
                is_lfs_file = False
                try:
                    current_file_name = line.split(" ")[2][
                        2:
                    ]  # Extract filename from diff header
                except IndexError:
                    self.logger.warning(f"Malformed diff header: {line}")
                    continue
            elif line.startswith(
                "+version https://git-lfs.github.com/spec/"
            ) or line.startswith("-version https://git-lfs.github.com/spec/"):
                is_lfs_file = True
            else:
                current_file.append(line)

        # Handle the last file
        if current_file and not is_lfs_file:
            file_diffs.append((current_file_name, "\n".join(current_file)))
        elif is_lfs_file:
            dropped_lfs_files.append(current_file_name)

        if dropped_lfs_files:
            self.logger.info(
                f"Dropping {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}"
            )

        return file_diffs, dropped_lfs_files

    def _create_quota_breakdown_for_full_diff(
        self,
        file_diffs: List[Tuple[str, str]],
        max_token_count: int,
        full_diff: str,
        dropped_lfs_files: List[str],
    ) -> Tuple[str, List[str]]:
        """Create quota breakdown when full diff is under the token limit."""
        quota_breakdown = []

        if dropped_lfs_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}\n"
            )

        diff_sizes = {filename: count_tokens(diff) for filename, diff in file_diffs}
        total_size = sum(diff_sizes.values()) or 1

        for filename, diff in file_diffs:
            diff_tokens = count_tokens(diff)
            proportion = diff_tokens / total_size
            display_name = filename or "<unknown>"
            quota = max(1, int(proportion * max_token_count))
            quota_breakdown.append(
                f"- {display_name}: Original diff size: {diff_tokens} tokens, Quota allocated: {quota} tokens"
            )

        return full_diff, quota_breakdown

    def _calculate_proportional_quotas(
        self, file_diffs: List[Tuple[str, str]], max_token_count: int
    ) -> Tuple[Dict[str, int], List[str]]:
        """Calculate quotas using proportional mode with smart file dropping.

        When total tokens exceed max_token_count, drops the smallest files above
        min_file_token_threshold first, working up the list until we fit within
        the limit. Files below min_file_token_threshold are never dropped.

        Returns:
            Tuple of (file_quotas, dropped_files)
        """
        # Calculate token sizes for all files
        diff_sizes = {filename: count_tokens(diff) for filename, diff in file_diffs}
        total_tokens = sum(diff_sizes.values())

        dropped_files = []

        # If we're over the limit, drop files starting from smallest above threshold
        if total_tokens > max_token_count:
            # Helper to check if file has protected extension
            protected_extensions = set(settings.protected_file_extensions)

            def is_protected_extension(filename: str) -> bool:
                return any(filename.endswith(ext) for ext in protected_extensions)

            # Separate files into droppable and protected
            # Protected if: below token threshold OR has protected extension
            droppable_files = [
                (f, s)
                for f, s in diff_sizes.items()
                if s >= settings.min_file_token_threshold
                and not is_protected_extension(f)
            ]
            protected_files = [
                (f, s)
                for f, s in diff_sizes.items()
                if s < settings.min_file_token_threshold
                or is_protected_extension(f)
            ]

            # Sort droppable files by size (smallest first)
            droppable_files.sort(key=lambda x: x[1])

            # Drop files one at a time starting from smallest until under limit
            for filename, size in droppable_files:
                if total_tokens <= max_token_count:
                    break
                dropped_files.append(filename)
                total_tokens -= size
                del diff_sizes[filename]

            if dropped_files:
                self.logger.info(
                    f"Dropping {len(dropped_files)} file(s) to fit context limit: {', '.join(dropped_files)}"
                )

        # If all files are dropped, return empty quotas
        if not diff_sizes:
            self.logger.warning("All files were dropped. No files to process.")
            return {}, dropped_files

        # Calculate proportional quotas for remaining files
        total_size = sum(diff_sizes.values()) or 1

        file_quotas = {}
        for filename, size in diff_sizes.items():
            proportion = size / total_size
            file_quotas[filename] = max(1, int(proportion * max_token_count))

        # Adjust for rounding errors
        total_allocated = sum(file_quotas.values())
        if total_allocated < max_token_count:
            largest_file = max(diff_sizes.items(), key=lambda x: x[1])[0]
            file_quotas[largest_file] += max_token_count - total_allocated

        return file_quotas, dropped_files

    def _truncate_diffs_to_quotas(
        self, file_diffs: List[Tuple[str, str]], file_quotas: Dict[str, int]
    ) -> List[str]:
        """Truncate each file's diff to its allocated quota.

        Only processes files that exist in file_quotas (dropped files are skipped).
        """
        truncated_diffs = []
        for filename, diff in file_diffs:
            # Skip files that were dropped
            if filename not in file_quotas:
                continue

            quota = file_quotas[filename]
            diff_tokens = count_tokens(diff)

            if diff_tokens > quota:
                # Use tiktoken to decode truncated tokens back to text
                encoded = _ENCODER.encode(_escape_special_tokens(diff))
                truncated_tokens = encoded[:quota]
                truncated_diff = _ENCODER.decode(truncated_tokens)
                truncated_diffs.append(
                    f"# Truncated diff for {filename} (original: {diff_tokens} tokens)\n{truncated_diff}"
                )
            else:
                truncated_diffs.append(diff)
        return truncated_diffs

    def _create_detailed_quota_breakdown(
        self,
        file_diffs: List[Tuple[str, str]],
        file_quotas: Dict[str, int],
        dropped_files: List[str],
        dropped_lfs_files: List[str],
    ) -> List[str]:
        """Create detailed breakdown of file quotas."""
        quota_breakdown = []

        if dropped_lfs_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_lfs_files)} LFS file(s): {', '.join(dropped_lfs_files)}\n"
            )

        if dropped_files:
            quota_breakdown.append(
                f"\nDropped {len(dropped_files)} file(s) to fit context limit: {', '.join(dropped_files)}\n"
            )

        for filename, quota in file_quotas.items():
            diff_tokens = count_tokens(
                next(diff for f, diff in file_diffs if f == filename)
            )
            quota_breakdown.append(
                f"- {filename}: Original diff size: {diff_tokens} tokens, Quota allocated: {quota} tokens"
            )
        return quota_breakdown

    def get_branch_diffs(
        self, base_branch: str, max_token_count: Optional[int] = None
    ) -> Optional[Tuple[str, List[str]]]:
        """Get unified diff between base branch and HEAD (committed changes only).

        Uses git diff base_branch...HEAD which compares the merge-base with HEAD,
        excluding any staged or uncommitted changes.

        Args:
            base_branch: The base branch to compare against
            max_token_count: If set, enables size-aware mode and truncates diffs to stay within this token count
        """
        try:
            full_diff = subprocess.check_output(
                ["git", "diff", f"{base_branch}...HEAD"], text=True, timeout=60
            ).strip()

            return self._process_diff_with_size_limiting(full_diff, max_token_count)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Diff error: {e}")
            return None

    def get_staged_diff_enhanced(
        self, max_token_count: Optional[int] = None
    ) -> Optional[Tuple[str, List[str]]]:
        """Get staged changes with optional size limiting and advanced processing.

        Args:
            max_token_count: If set, enables size-aware mode and truncates diffs to stay within this token count
        """
        try:
            full_diff = subprocess.check_output(
                ["git", "diff", "--staged"], text=True, timeout=60
            ).strip()

            return self._process_diff_with_size_limiting(full_diff, max_token_count)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Staged diff error: {e}")
            return None

    def get_diff_processing_params(self, default_token_count: int) -> int:
        """Unified method to get diff processing parameters.

        Uses CLI token_limit if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses default

        Args:
            default_token_count: Default token count limit for this generator type

        Returns:
            max_token_count: The token limit for diff processing
        """
        if self._cli_token_limit is not None:
            return self._cli_token_limit
        if self._interactive:
            return self.get_token_limit(default=default_token_count, context="diff")
        return default_token_count

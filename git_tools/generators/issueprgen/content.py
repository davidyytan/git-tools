"""Assemble the generation input from commits, diffs, and fixed-title context."""

from typing import Any, Dict, Optional, Tuple, Union

from git_tools.settings.settings import settings

from ..base import console, warning
from .contexts import PromotionPrContext, WorkflowPrContext


class GenerationContentMixin:
    """Choose the input source and gather its content for the model."""

    def _collect_generation_content(
        self,
        commit_info: Optional[Dict[str, Any]],
        fixed_context: Optional[Union[PromotionPrContext, WorkflowPrContext]],
    ) -> Optional[Tuple[str, str]]:
        """Return ``(input_source, content)``, or ``None`` when there is nothing to send.

        Input source: CLI param > interactive prompt > default ("b").
        """
        if not commit_info or commit_info["commit_count"] < 1:
            return "c", fixed_context.to_prompt_block() if fixed_context else ""

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
                return None
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
                return None

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
                return None
            content_parts = [f"Code Diffs:\n```\n{diffs[0]}\n```"]
            if fixed_context is not None:
                content_parts.append(fixed_context.to_prompt_block())
            content = "\n\n".join(content_parts)

            # Display quota breakdown using unified method
            # Only add spacing if interactive (text → panel transition)
            if self._interactive:
                console.print()
            self.display_quota_breakdown(diffs[1], max_token_count)

        return input_source, content

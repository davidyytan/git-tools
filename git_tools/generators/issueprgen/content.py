"""Assemble the generation input from commits, diffs, and fixed-title context."""

from typing import Any, Dict, Optional, Tuple, Union

from git_tools.settings.settings import settings

from ..base import console, warning
from ..base.prompts import commit_evidence, diff_evidence, messages_have_content
from .contexts import PromotionPrContext, WorkflowPrContext


class GenerationContentMixin:
    """Choose the input source and gather its content for the model."""

    def _collect_generation_content(
        self,
        commit_info: Optional[Dict[str, Any]],
        fixed_context: Optional[Union[PromotionPrContext, WorkflowPrContext]],
    ) -> Optional[Tuple[str, str]]:
        """Return ``(input_source, content)``, or ``None`` when there is nothing to send.

        Input source: CLI override > saved preference (default "b").
        """
        if not commit_info or commit_info["commit_count"] < 1:
            return "c", fixed_context.to_prompt_block() if fixed_context else ""

        input_source = (
            self._cli_input_source
            if self._cli_input_source is not None
            else settings.issue_pr_source
        ).lower()
        # Preserve the documented fallback for an invalid explicit source.
        input_source = "b" if input_source not in ("d", "c", "b") else input_source

        if input_source == "c":
            messages = self.get_commit_messages(commit_info, individual=True)
            content_parts = []
            if messages_have_content(messages):
                content_parts.append(commit_evidence(messages))
            if fixed_context is not None:
                content_parts.append(fixed_context.to_prompt_block())
            content = "\n\n".join(content_parts)
            if not content.strip():
                warning("No commit messages to generate from")
                return None
        elif input_source == "b":
            messages = self.get_commit_messages(commit_info, individual=True)
            max_token_count = self.get_diff_processing_params(
                settings.default_issue_pr_token_limit
            )

            diffs = self.get_branch_diffs(commit_info["base_branch"], max_token_count)
            diff_text = diffs[0] if diffs else ""
            diff_has_content = bool(diff_text.strip())
            has_messages = messages_have_content(messages)

            if not has_messages and not diff_has_content:
                if fixed_context is not None:
                    warning("No usable selected evidence remains; using validated workflow context only.")
                    console.print()
                    return "c", fixed_context.to_prompt_block()
                warning("Missing data for generation")
                return None

            content_parts = []
            if messages_have_content(messages):
                content_parts.append(commit_evidence(messages))
            if diff_has_content:
                content_parts.append(diff_evidence(diff_text))
            elif has_messages:
                warning(
                    "No code diffs found for this range; using commit messages only."
                )
                console.print()
            if fixed_context is not None:
                content_parts.append(fixed_context.to_prompt_block())
            content = "\n\n".join(content_parts)

            # Each rendered quota panel owns its trailing separator.
            if diff_has_content:
                self.display_quota_breakdown(diffs[1], max_token_count)
        else:
            max_token_count = self.get_diff_processing_params(
                settings.default_issue_pr_token_limit
            )

            diffs = self.get_branch_diffs(commit_info["base_branch"], max_token_count)
            if not diffs or not diffs[0].strip():
                if fixed_context is not None:
                    warning("No usable code diffs remain; using validated workflow context only.")
                    console.print()
                    return "c", fixed_context.to_prompt_block()
                warning("No usable code diffs remain after processing")
                return None
            content_parts = [diff_evidence(diffs[0])]
            if fixed_context is not None:
                content_parts.append(fixed_context.to_prompt_block())
            content = "\n\n".join(content_parts)

            self.display_quota_breakdown(diffs[1], max_token_count)

        return input_source, content

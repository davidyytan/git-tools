"""Rich panels for quota breakdowns, token usage, and model reasoning."""

from typing import Any, Dict, List

from rich.markup import escape
from rich.panel import Panel

from .terminal import (
    ALIGN_PANEL,
    STYLE_BORDER,
    STYLE_DIM,
    STYLE_PRIMARY,
    STYLE_SUCCESS,
    STYLE_WARNING,
    console,
)


class DisplayMixin:
    """Render generator diagnostics in the shared panel style."""

    def display_quota_breakdown(
        self, quota_breakdown: List[str], max_token_count: int
    ) -> None:
        """Unified method to display quota breakdown with sorting.

        Args:
            quota_breakdown: List of quota breakdown lines
            max_token_count: Maximum token count limit used
        """
        if not quota_breakdown or not any(line.strip() for line in quota_breakdown):
            return

        # Separate dropped files messages from quota allocations
        dropped_messages = [
            line for line in quota_breakdown if line.startswith("\nDropped")
        ]
        quota_lines = [
            line for line in quota_breakdown if not line.startswith("\nDropped")
        ]

        # Sort quota lines by original diff size (descending)
        sorted_quotas = sorted(
            quota_lines,
            key=lambda x: int(x.split("Original diff size: ")[1].split(" tokens")[0])
            if "Original diff size:" in x
            else 0,
            reverse=True,
        )

        # Build panel content
        lines = []
        for msg in dropped_messages:
            lines.append(f"[{STYLE_WARNING}]⚠ {msg.strip()}[/{STYLE_WARNING}]")

        for line in sorted_quotas:
            if "Original diff size:" in line:
                parts = line.split(":")
                filename = parts[0].replace("- ", "").strip()
                try:
                    orig = line.split("Original diff size: ")[1].split(" tokens")[0]
                    alloc = line.split("Quota allocated: ")[1].split(" tokens")[0]
                    lines.append(f"[{STYLE_DIM}]•[/{STYLE_DIM}] {filename} [{STYLE_DIM}]({orig} → {alloc})[/{STYLE_DIM}]")
                except (IndexError, ValueError):
                    lines.append(f"[{STYLE_DIM}]• {line}[/{STYLE_DIM}]")
            else:
                lines.append(f"[{STYLE_DIM}]{line}[/{STYLE_DIM}]")

        # Filter out empty lines and strip each line to prevent phantom newlines
        clean_lines = [line.strip() for line in lines if line.strip()]
        if not clean_lines:
            return
        console.print(Panel(
            "\n".join(clean_lines),
            title=f"[bold]File Quota[/bold] [{STYLE_DIM}]{max_token_count:,} tokens[/{STYLE_DIM}]",
            border_style=STYLE_BORDER,
            title_align=ALIGN_PANEL,
        ), soft_wrap=False)
        console.print()

    def display_token_usage(self, response: Dict[str, Any]) -> None:
        """Unified method to display token usage and cost information.

        Args:
            response: Response dict from LLM invocation
        """
        response_metadata = response.get("response_metadata")
        if not isinstance(response_metadata, dict):
            return
        token_usage = response_metadata.get("token_usage")
        if not isinstance(token_usage, dict) or not token_usage:
            return

        # Providers may explicitly return null for optional nested usage fields.
        completion_details = token_usage.get("completion_tokens_details")
        if not isinstance(completion_details, dict):
            completion_details = {}
        cost_details = token_usage.get("cost_details")
        if not isinstance(cost_details, dict):
            cost_details = {}

        # Build token usage content
        lines = []
        prompt_tokens = token_usage.get("prompt_tokens")
        completion_tokens = token_usage.get("completion_tokens")
        total_tokens = token_usage.get("total_tokens")
        reasoning_tokens = completion_details.get("reasoning_tokens")

        if prompt_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Prompt:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{prompt_tokens:,}[/{STYLE_PRIMARY}]")
        if completion_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Completion:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{completion_tokens:,}[/{STYLE_PRIMARY}]")
        if reasoning_tokens is not None:
            lines.append(f"[{STYLE_DIM}]Reasoning:[/{STYLE_DIM}] [{STYLE_PRIMARY}]{reasoning_tokens:,}[/{STYLE_PRIMARY}]")
        if total_tokens is not None:
            lines.append(f"[bold]Total:[/bold] [{STYLE_PRIMARY}]{total_tokens:,}[/{STYLE_PRIMARY}]")

        # Cost information
        cost = token_usage.get("cost")
        upstream_cost = cost_details.get("upstream_inference_cost")

        if cost is not None or upstream_cost is not None:
            lines.append("")
            if cost is not None:
                lines.append(f"[{STYLE_DIM}]Cost:[/{STYLE_DIM}] [{STYLE_SUCCESS}]${cost:.6f}[/{STYLE_SUCCESS}]")
            if upstream_cost is not None:
                lines.append(f"[{STYLE_DIM}]Upstream:[/{STYLE_DIM}] [{STYLE_SUCCESS}]${upstream_cost:.6f}[/{STYLE_SUCCESS}]")
            total_cost = (cost or 0) + (upstream_cost or 0)
            lines.append(f"[bold]Total Cost:[/bold] [{STYLE_SUCCESS}]${total_cost:.6f}[/{STYLE_SUCCESS}]")

        if not lines:
            return
        console.print(Panel("\n".join(lines).strip(), title="[bold]Token Usage[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
        console.print()

    def display_reasoning(self, response: Dict[str, Any]) -> None:
        """Display reasoning content if available in response.

        Args:
            response: Response dict from LLM invocation
        """
        reasoning_content = response.get("additional_kwargs", {}).get(
            "reasoning_content"
        )
        if reasoning_content and reasoning_content.strip():
            console.print(Panel(escape(reasoning_content.strip()), title="[bold]Reasoning[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
            console.print()

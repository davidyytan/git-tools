"""``CommitGenerator``: Conventional Commit messages from staged changes."""

from pathlib import Path
from typing import Any, Dict, Literal, Optional

from rich.markup import escape
from rich.panel import Panel

from git_tools.settings.settings import settings

from ..base import (
    ALIGN_PANEL,
    STYLE_BORDER,
    BaseGenerator,
    console,
    info,
    warning,
)
from .messages import CommitMessageMixin
from .sensitive import SensitiveFileGuardMixin
from .workflow import WORKFLOW_KIND_NORMAL, WorkflowCommitMixin


class CommitGenerator(
    SensitiveFileGuardMixin,
    WorkflowCommitMixin,
    CommitMessageMixin,
    BaseGenerator,
):
    """Generate a Conventional Commit from the staged diff, or a workflow subject."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        token_limit: Optional[int] = None,
        include_scope: Optional[bool] = None,
        include_footer: Optional[bool] = None,
        auto_commit: Optional[bool] = None,
        copy_clipboard: Optional[bool] = None,
        force_sensitive: bool = False,
        workflow_kind: Optional[str] = None,
        interactive: bool = False,
        include_body: Optional[bool] = None,
        body_style: Optional[Literal["bullets", "prose"]] = None,
        output_path: str | Path | None = None,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            interactive=interactive,
        )
        self.commit_prompt = self._load_prompt_template("commitgen_prompt.txt")

        # CLI parameters for commit-specific options
        self._cli_include_scope = include_scope
        self._cli_include_footer = include_footer
        self._cli_include_body = include_body
        self._cli_body_style = body_style
        self._cli_auto_commit = auto_commit
        self._cli_copy_clipboard = copy_clipboard
        self._cli_force_sensitive = force_sensitive
        self._cli_workflow_kind = workflow_kind
        self._cli_output_path = output_path

    def generate_commit(self) -> None:
        """Main commit generation workflow."""
        self._prepare_output()
        # CLI mode: add leading blank line to separate from command
        if not self._interactive:
            console.print()

        workflow_kind = self._resolve_commit_mode()
        if self._interactive and self._cli_workflow_kind is None:
            console.print()
        if workflow_kind != WORKFLOW_KIND_NORMAL:
            self._handle_workflow_commit(workflow_kind)
            return

        diff_content = self._get_and_validate_diff()
        if not diff_content:
            self._require_finished_output()
            return

        # Check for sensitive files before processing
        if not self._check_sensitive_files():
            if not self._interactive:
                raise ValueError("Sensitive files refused. Unstage them or re-run with --force-sensitive.")
            self._require_finished_output()
            return

        diff_content = self._handle_large_diff_processing(diff_content)
        if not diff_content.strip():
            raise ValueError("No usable staged diff remains after filtering or truncation; no commit message was generated. Review omitted LFS/binary files or the input token budget.")

        if not self._handle_external_provider_workflow(diff_content):
            self._require_finished_output()
            return

    def _get_and_validate_diff(self) -> Optional[str]:
        """Get staged diff and validate it exists."""
        diff_content = self.get_staged_diff()
        if not diff_content:
            warning("No staged changes detected! Exiting...")
            return None

        return diff_content

    def _handle_large_diff_processing(self, diff_content: str) -> str:
        """Process the diff using a CLI override or saved input budget."""
        # Get processing parameters upfront
        max_token_count = self.get_diff_processing_params(settings.default_token_limit)

        # Apply enhanced diff processing
        enhanced_result = self.get_staged_diff_enhanced(max_token_count)
        if enhanced_result:
            enhanced_diff, quota_breakdown = enhanced_result

            # Display quota breakdown if available
            if quota_breakdown:
                self.display_quota_breakdown(quota_breakdown, max_token_count)

            return enhanced_diff

        return diff_content

    def _handle_external_provider_workflow(self, diff_content: str) -> bool:
        """Handle the external provider workflow for commit generation.

        Format options reuse saved preferences unless explicitly overridden.
        Interactive mode retains consent before sending content externally.
        """
        include_scope = (
            self._cli_include_scope
            if self._cli_include_scope is not None
            else settings.commit_include_scope
        )
        include_footer = (
            self._cli_include_footer
            if self._cli_include_footer is not None
            else settings.commit_include_footer
        )

        include_body = (
            self._cli_include_body
            if self._cli_include_body is not None
            else settings.commit_include_body
        )
        body_style = (
            self._cli_body_style
            if self._cli_body_style is not None
            else settings.commit_body_style
        )

        system_msg = self._build_system_message(
            include_scope, include_footer, include_body, body_style
        )
        if self._interactive:
            self.display_generation_settings(
                input_budget=self.get_diff_processing_params(settings.default_token_limit),
                details=(
                    f"Scope: {'on' if include_scope else 'off'}; "
                    f"footer: {'on' if include_footer else 'off'}; "
                    f"body: {'on' if include_body else 'off'}; style: {body_style}"
                ),
            )

        # In interactive mode, ask if user wants to use external providers
        # In non-interactive mode, always use external providers
        if self._interactive:
            if not self.prompt_confirm("Generate commit message using external providers?", default=True):
                console.print()
                self._handle_local_mode(diff_content, system_msg)
                return False

        return self._generate_with_provider(diff_content, system_msg)

    def _handle_local_mode(
        self, diff_content: str, system_msg: str, *, allow_auto: bool = True
    ) -> None:
        """Display the local prompt, then honor the requested clipboard policy."""
        prompt = self._build_full_prompt(diff_content, system_msg)
        self.handoff_local_prompt(prompt, allow_auto=allow_auto)

    def _generate_with_provider(self, diff_content: str, system_msg: str) -> bool:
        """Generate commit message using external provider."""
        provider = self.select_provider()

        # Separate the consent answer from provider diagnostics or local output.
        if self._interactive:
            console.print()
        # Check API key - if not configured, offer setup or fall back to local mode
        if not self.ensure_api_key_configured(provider):
            info("Falling back to local mode...")
            console.print()
            self._handle_local_mode(diff_content, system_msg, allow_auto=False)
            return False

        model, temperature, max_tokens = self.select_model_params(provider)

        if not self._initialize_service(provider, model, temperature, max_tokens):
            raise ValueError(f"Failed to initialize {provider} service. Please check your configuration and API keys.")

        response = self.generate_commit_message(diff_content, system_msg)
        if not response:
            raise ValueError("Failed to generate commit message")

        self._handle_commit_action(response, show_preview=True)
        return True

    def _display_response(self, response: Dict[str, Any], *, commit_message: Optional[str] = None) -> None:
        """Display LLM response panels."""
        self.display_optional_metadata(response, kind="reasoning")
        if commit_message is None:
            raw_content = response.get("content")
            commit_message = self.parse_commit_message(raw_content) if isinstance(raw_content, str) else None
        if not commit_message:
            raise ValueError("Invalid commit message format")
        if console.is_terminal:
            console.print(Panel(escape(commit_message), title="[bold]Commit Message[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
        else:
            console.print(commit_message, markup=False, highlight=False, emoji=False, soft_wrap=True)
        console.print()

    def _handle_commit_action(self, response: Dict[str, Any], *, show_preview: bool = False) -> Optional[Path]:
        """Handle the commit or clipboard action.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults (commit directly)

        Args:
            response: LLM response dictionary
        """
        raw_content = response.get("content")
        commit_message = self.parse_commit_message(raw_content) if isinstance(raw_content, str) else None

        if not commit_message:
            raise ValueError("Invalid commit message format")

        def preview() -> None:
            self._display_response(response, commit_message=commit_message)
            self.display_optional_metadata(response, kind="token usage")

        return self._handle_message_action(commit_message, preview=preview if show_preview else None)


def generate_commit() -> None:
    """Entry point for commit generation.

    Creates a CommitGenerator instance and runs the generation workflow.
    """
    return CommitGenerator().generate_commit()

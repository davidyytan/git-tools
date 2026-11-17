"""``IssuePullRequestGenerator``: issue and PR text from commits and diffs."""

from pathlib import Path
from typing import Optional

from rich.markup import escape
from rich.panel import Panel

from git_tools.settings.settings import settings

from ..base import (
    ALIGN_PANEL,
    STYLE_BORDER,
    BaseGenerator,
    console,
    info,
    success,
    warning,
)
from ..utils.artifacts import resolve_output_path, save_draft
from .azure import AZURE_PR_DESCRIPTION_INSTRUCTION, AzureLimitMixin
from .branches import BranchResolutionMixin
from .commits import CommitHistoryMixin
from .content import GenerationContentMixin
from .contexts import PromotionPrContext, WorkflowPrContext
from .modes import GenerationModeMixin
from .promotion import PromotionContextMixin
from .prompts import PromptAssemblyMixin
from .titles import FixedTitleMixin
from .versions import VersionLookupMixin
from .workflow import WorkflowContextMixin


class IssuePullRequestGenerator(
    GenerationModeMixin,
    BranchResolutionMixin,
    VersionLookupMixin,
    PromotionContextMixin,
    WorkflowContextMixin,
    CommitHistoryMixin,
    GenerationContentMixin,
    PromptAssemblyMixin,
    FixedTitleMixin,
    AzureLimitMixin,
    BaseGenerator,
):
    """Generate issue and pull request text, optionally with fixed workflow titles."""

    def __init__(
        self,
        generation_type: Optional[str] = None,
        base_branch: Optional[str] = None,
        input_source: Optional[str] = None,
        release_pr: Optional[bool] = None,
        hotfix_pr: Optional[bool] = None,
        start_pr: Optional[bool] = None,
        backmerge_release_pr: Optional[bool] = None,
        backmerge_hotfix_pr: Optional[bool] = None,
        workflow_version: Optional[str] = None,
        context: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        token_limit: Optional[int] = None,
        azure_limit: Optional[bool] = None,
        interactive: bool = False,
        copy_clipboard: Optional[bool] = None,
        output_path: str | Path | None = None,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            token_limit=token_limit,
            interactive=interactive,
        )
        # Set generation_type from CLI or default to "issue"
        self.generation_type = generation_type if generation_type else "issue"
        self.issuepr_prompt = self._load_prompt_template("issuepr_prompt.txt")

        # CLI parameters for issue/pr-specific options
        self._cli_generation_type = generation_type
        self._cli_base_branch = base_branch
        self._cli_input_source = input_source
        self._cli_release_pr = release_pr
        self._cli_hotfix_pr = hotfix_pr
        self._cli_start_pr = start_pr
        self._cli_backmerge_release_pr = backmerge_release_pr
        self._cli_backmerge_hotfix_pr = backmerge_hotfix_pr
        self._cli_workflow_version = workflow_version
        self._cli_context = context
        self._cli_azure_limit = azure_limit
        self._cli_copy_clipboard = copy_clipboard
        self._cli_output_path = output_path
        self.release_pr = bool(release_pr)
        self.hotfix_pr = bool(hotfix_pr)
        self.start_pr = bool(start_pr)
        self.backmerge_release_pr = bool(backmerge_release_pr)
        self.backmerge_hotfix_pr = bool(backmerge_hotfix_pr)
        self._promotion_pr_context: PromotionPrContext | None = None
        self._workflow_pr_context: WorkflowPrContext | None = None

    def generate_issue_pullrequest(self) -> Optional[Path]:
        """Main generation workflow.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults
        """
        output_directory = Path.cwd()
        output_path = resolve_output_path(self._cli_output_path, output_directory)
        # CLI mode: add leading blank line to separate from command
        if not self._interactive:
            console.print()

        self.select_generation_type()
        self.resolve_pr_mode()

        base_branch = self.get_default_branch()
        promotion_context = None
        workflow_pr_context = None
        if self.release_pr:
            promotion_context = self._resolve_release_pr_context(base_branch)
        elif self.hotfix_pr:
            promotion_context = self._resolve_hotfix_pr_context(base_branch)
        elif self.start_pr:
            workflow_pr_context = self._resolve_start_pr_context(base_branch)
        elif self.backmerge_release_pr:
            workflow_pr_context = self._resolve_backmerge_release_pr_context(base_branch)
        elif self.backmerge_hotfix_pr:
            workflow_pr_context = self._resolve_backmerge_hotfix_pr_context(base_branch)
        self._promotion_pr_context = promotion_context
        self._workflow_pr_context = workflow_pr_context

        commit_info = self.get_commit_info(base_branch)

        fixed_context = promotion_context or workflow_pr_context

        if (not commit_info or commit_info["commit_count"] < 1) and fixed_context is None:
            warning("No commits to generate from")
            self._require_finished_output()
            return

        if commit_info and commit_info["commit_count"] >= 1:
            # Only add spacing if interactive (questionary → panel transition)
            if self._interactive:
                console.print()
            self.show_commit_summary(commit_info)

        collected = self._collect_generation_content(commit_info, fixed_context)
        if collected is None:
            self._require_finished_output()
            return
        input_source, content = collected

        # Context: CLI param > interactive prompt > default (None)
        if self._cli_context is not None:
            context = self._cli_context
        elif self._interactive:
            context = self.prompt_text("Additional context (optional; leave blank to skip)").strip()
        else:
            context = None  # Default: no context

        if context:
            content = (
                content
                + "\n\n"
                + "Here are some additional context to guide the diffs and/or commit messages. The generated content should try its best to use the context but stay faithful to the diffs and/or commit messages. Context is user intent but diffs and commit messages are the actual code changes."
                + "\n\n"
                + "Context:\n```\n"
                + context
                + "\n```"
            )

        # Separate an answered context prompt (or fixed mode without a summary)
        # from the next status/settings section. Existing panels own their gap.
        if self._interactive and (
            self._cli_context is None or not (commit_info and commit_info["commit_count"] >= 1)
        ):
            console.print()
        system_msg = self._build_system_message(content, input_source)

        # PR description limit: CLI override > saved preference/origin detection.
        apply_azure_limit = False
        if self.generation_type == "pr" and self._should_apply_azure_limit():
            apply_azure_limit = True
            instruction = AZURE_PR_DESCRIPTION_INSTRUCTION
            instruction += (
                f" The user's preferred limit is {settings.azure_pr_max_chars} "
                "UTF-16 units; keep the generated PR within that limit."
            )
            system_msg = f"{system_msg}\n\n{instruction}"

        if self._interactive:
            self.display_generation_settings(
                input_budget=self.get_diff_processing_params(settings.default_issue_pr_token_limit),
                details=(f"Input source: {input_source}; PR description limit: "
                         f"{str(settings.azure_pr_max_chars) + ' UTF-16 units' if apply_azure_limit else 'off'}"),
            )
        # In interactive mode, ask if user wants to use external providers
        # In non-interactive mode, always use external providers
        if self._interactive:
            if not self.prompt_confirm("Generate content using external providers?", default=True):
                console.print()
                self._handle_local_mode(content, system_msg)
                self._require_finished_output()
                return

        # Provider initialization
        provider = self.select_provider()

        # Separate the consent answer from provider diagnostics or local output.
        if self._interactive:
            console.print()
        # Check API key - if not configured, offer setup or fall back to local mode
        if not self.ensure_api_key_configured(provider):
            info("Falling back to local mode...")
            console.print()
            self._handle_local_mode(content, system_msg, allow_auto=False)
            self._require_finished_output()
            return

        model, temperature, max_tokens = self.select_model_params(provider)

        if not self._initialize_service(provider, model, temperature, max_tokens):
            raise ValueError(f"Failed to initialize {provider} service. Check your configuration and API keys.")

        response = self.generate_content(content, system_msg)
        if not response:
            raise ValueError("Failed to generate content")
        raw_output = response.get("content")
        if not isinstance(raw_output, str):
            raise ValueError("No valid generated text found")
        parsed_source = self.parse_generated_content(raw_output)
        if not parsed_source.strip():
            # Preserve substantial imperfect output, but never treat empty verified fences as a draft.
            if self.generation_type != "pr" or not raw_output.strip() or raw_output.strip().startswith(("```", "~~~")):
                raise ValueError(f"No valid {self.generation_type} content found")
            parsed_source = raw_output
            warning("Parsed PR content was empty. Using raw model output instead.")
        display_output = self._normalize_pr_output(parsed_source)
        if not display_output.strip():
            raise ValueError(f"No valid {self.generation_type} content found")
        if apply_azure_limit:
            display_output = self._enforce_azure_pr_description_limit(display_output, content, system_msg)
        copy_output = display_output if self.generation_type == "pr" else raw_output

        # Save paid-for output before metadata rendering or a cancellable copy question.
        saved_path = None
        save_error = None
        try:
            save_options = {"output_path": output_path} if output_path is not None else {}
            saved_path = save_draft(display_output, self.generation_type, output_directory, **save_options)
        except (OSError, UnicodeError) as exc:
            destination = str(output_path) if output_path is not None else f"draft in {output_directory}"
            save_error = ValueError(f"Could not save {self.generation_type} {destination}: {exc}")
        try:
            if saved_path is not None:
                success(f"Saved draft: {escape(str(saved_path))}")
                console.print()
            if save_error is not None:
                warning("Draft could not be saved; the preview and requested clipboard handoff are still available.")

            self.display_optional_metadata(response, kind="reasoning")
            type_labels = {
                "pr": "PR Description",
                "issue": "Issue Description",
                "both": "Combined Output",
            }
            if console.is_terminal:
                console.print(Panel(escape(display_output), title=f"[bold]{type_labels.get(self.generation_type, 'Output')}[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
            else:
                console.print(display_output, markup=False, highlight=False, emoji=False, soft_wrap=True)
            console.print()
            self.display_optional_metadata(response, kind="token usage")
            self.handoff_to_clipboard(copy_output, leading_space=False)
        finally:
            # Keep an already-failed save authoritative, even if later output or cancellation interrupts recovery.
            if save_error is not None:
                raise save_error
        return saved_path

    def _require_finished_output(self) -> None:
        if self._cli_output_path is not None:
            raise ValueError("No finished document was generated for --output; no file was written.")

    def _handle_local_mode(
        self, content: str, system_msg: str, *, allow_auto: bool = True
    ) -> None:
        """Display a reusable prompt even when copying is disabled or unavailable."""
        full_prompt = system_msg + "\n\n" + self._build_full_prompt(content)
        self.handoff_local_prompt(full_prompt, allow_auto=allow_auto)


def generate_issue_pullrequest() -> Optional[Path]:
    """Entry point for issue and pull request generation.

    Creates an IssuePullRequestGenerator instance and runs the generation workflow.
    """
    return IssuePullRequestGenerator().generate_issue_pullrequest()

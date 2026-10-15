"""``IssuePullRequestGenerator``: issue and PR text from commits and diffs."""

from typing import Optional

from rich.markup import escape
from rich.panel import Panel

from git_tools.settings.settings import settings

from ..base import (
    ALIGN_PANEL,
    STYLE_BORDER,
    BaseGenerator,
    console,
    error,
    info,
    warning,
)
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
        self.release_pr = bool(release_pr)
        self.hotfix_pr = bool(hotfix_pr)
        self.start_pr = bool(start_pr)
        self.backmerge_release_pr = bool(backmerge_release_pr)
        self.backmerge_hotfix_pr = bool(backmerge_hotfix_pr)
        self._promotion_pr_context: PromotionPrContext | None = None
        self._workflow_pr_context: WorkflowPrContext | None = None

    def generate_issue_pullrequest(self) -> None:
        """Main generation workflow.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults
        """
        # CLI mode: add leading blank line to separate from command
        if not self._interactive:
            console.print()

        self.select_generation_type()
        self.resolve_pr_mode()

        base_branch = self.get_default_branch()
        try:
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
        except ValueError as exc:
            error(str(exc))
            return

        commit_info = self.get_commit_info(base_branch)

        fixed_context = promotion_context or workflow_pr_context

        if (not commit_info or commit_info["commit_count"] < 1) and fixed_context is None:
            warning("No commits to generate from")
            return

        if commit_info and commit_info["commit_count"] >= 1:
            # Only add spacing if interactive (questionary → panel transition)
            if self._interactive:
                console.print()
            self.show_commit_summary(commit_info)
            # Only add spacing if interactive (panel → questionary transition)
            if self._interactive:
                console.print()

        collected = self._collect_generation_content(commit_info, fixed_context)
        if collected is None:
            return
        input_source, content = collected

        # Add spacing before interactive prompts (after quota panel)
        if self._interactive:
            console.print()

        # Context: CLI param > interactive prompt > default (None)
        if self._cli_context is not None:
            context = self._cli_context
        elif self._interactive:
            if self.prompt_confirm("Add additional context?", default=False):
                context = self.prompt_text("Enter additional context").strip()
            else:
                context = None
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

        system_msg = self._build_system_message(content, input_source)

        # Azure DevOps PR description limit: CLI param > prompt > origin detection.
        apply_azure_limit = False
        if self.generation_type == "pr" and self._should_apply_azure_limit():
            apply_azure_limit = True
            instruction = AZURE_PR_DESCRIPTION_INSTRUCTION
            instruction += (
                f" The user's preferred limit is {settings.azure_pr_max_chars} "
                "UTF-16 units; keep the generated PR within that limit."
            )
            system_msg = f"{system_msg}\n\n{instruction}"

        # In interactive mode, ask if user wants to use external providers
        # In non-interactive mode, always use external providers
        if self._interactive:
            if not self.prompt_confirm("Generate content using external providers?", default=True):
                full_prompt = system_msg + "\n\n" + self._build_full_prompt(content)
                self.ask_to_copy_to_clipboard(full_prompt)
                return

        # Provider initialization
        provider = self.select_provider()

        # Check API key - if not configured, offer setup or fall back to local mode
        if not self.ensure_api_key_configured(provider):
            info("Falling back to local mode...")
            full_prompt = system_msg + "\n\n" + self._build_full_prompt(content)
            self.copy_to_clipboard_auto(full_prompt)
            return

        model, temperature, max_tokens = self.select_model_params(provider)

        if not self._initialize_service(provider, model, temperature, max_tokens):
            return

        # Spacing before spinner only in interactive mode (Questionary → Spinner)
        # In CLI mode, Panel → Spinner → Panel, spinner disappears leaving Panel → Panel (no spacing)
        if self._interactive:
            console.print()
        response = self.generate_content(content, system_msg)
        if not response:
            error("Failed to generate content")
            return

        self.display_reasoning(response)

        parsed = self._normalize_pr_output(self.parse_generated_content(response["content"]))
        if apply_azure_limit and parsed:
            parsed = self._enforce_azure_pr_description_limit(parsed, content, system_msg)
        display_output = parsed
        copy_output = response["content"]
        used_raw_fallback = False

        if self.generation_type == "pr":
            if parsed:
                display_output = parsed
                copy_output = display_output
            else:
                raw_output = response["content"].strip()
                if raw_output:
                    display_output = raw_output
                    copy_output = display_output
                    used_raw_fallback = True

        type_labels = {
            "pr": "PR Description",
            "issue": "Issue Description",
            "both": "Combined Output",
        }

        if display_output:
            if used_raw_fallback:
                warning("Parsed PR content was empty. Using raw model output instead.")
            console.print(Panel(escape(display_output.strip()), title=f"[bold]{type_labels.get(self.generation_type, 'Output')}[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))
        else:
            error_msgs = {
                "pr": "No valid PR content found",
                "issue": "No valid issue content found",
                "both": "No valid content found",
            }
            error(error_msgs.get(self.generation_type, "No valid content found"))
            return

        self.display_token_usage(response)

        # Panel → Questionary (interactive) needs spacing
        # CLI mode: copy_to_clipboard_auto handles its own spacing before success
        if self._interactive:
            console.print()
            self.ask_to_copy_to_clipboard(copy_output)
        else:
            self.copy_to_clipboard_auto(copy_output)
        return


def generate_issue_pullrequest() -> None:
    """Entry point for issue and pull request generation.

    Creates an IssuePullRequestGenerator instance and runs the generation workflow.
    """
    return IssuePullRequestGenerator().generate_issue_pullrequest()

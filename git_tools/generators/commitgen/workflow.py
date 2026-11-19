"""Commit-mode selection and shared file/commit delivery for normal and fixed messages."""

from pathlib import Path
import subprocess
from typing import Callable

from rich.markup import escape
from rich.panel import Panel

from ..base import ALIGN_PANEL, STYLE_BORDER, console, success, warning
from ..utils.artifacts import resolve_output_path, save_draft

WORKFLOW_KIND_NORMAL = "normal"
WORKFLOW_KIND_OPEN_RELEASE = "open-release"
GIT_COMMIT_TIMEOUT_SECONDS = 15 * 60


class WorkflowCommitMixin:
    """Resolve commit modes and share action/output policy across generated and fixed messages."""

    def _prepare_output(self) -> None:
        self._output_directory = Path.cwd()
        self._resolved_output_path = resolve_output_path(self._cli_output_path, self._output_directory, validate_default=self._cli_auto_commit is False)

    def _require_finished_output(self) -> None:
        if self._cli_output_path is not None:
            raise ValueError("No finished commit message was generated for --output; no file was written.")

    def _resolve_commit_mode(self) -> str:
        if self._cli_workflow_kind is not None:
            return self._normalize_workflow_kind(self._cli_workflow_kind)
        if not self._interactive:
            return WORKFLOW_KIND_NORMAL
        choice = self.prompt_select(
            "Select commit mode",
            ["Conventional Commit", "chore: open release"],
            default="Conventional Commit",
        )
        return {
            "Conventional Commit": WORKFLOW_KIND_NORMAL,
            "chore: open release": WORKFLOW_KIND_OPEN_RELEASE,
        }.get(choice, WORKFLOW_KIND_NORMAL)

    def _normalize_workflow_kind(self, workflow_kind: str) -> str:
        normalized = workflow_kind.strip().lower()
        aliases = {
            WORKFLOW_KIND_NORMAL: WORKFLOW_KIND_NORMAL,
            "conventional": WORKFLOW_KIND_NORMAL,
            WORKFLOW_KIND_OPEN_RELEASE: WORKFLOW_KIND_OPEN_RELEASE,
            "open_release": WORKFLOW_KIND_OPEN_RELEASE,
        }
        if normalized not in aliases:
            raise ValueError(f"Unsupported workflow commit kind: {workflow_kind}")
        return aliases[normalized]

    def _handle_workflow_commit(self, workflow_kind: str) -> Path | None:
        staged_files = self._get_staged_files()
        if staged_files and not self._check_sensitive_files():
            if not self._interactive:
                raise ValueError("Sensitive files refused. Unstage them or re-run with --force-sensitive.")
            self._require_finished_output()
            return None
        subject = self._build_workflow_subject(workflow_kind)
        return self._handle_fixed_subject_action(subject, allow_empty=not staged_files, show_preview=True)

    def _build_workflow_subject(self, workflow_kind: str) -> str:
        if workflow_kind == WORKFLOW_KIND_OPEN_RELEASE:
            return "chore: open release"
        raise ValueError(f"Unsupported workflow commit kind: {workflow_kind}")

    def _handle_fixed_subject_action(self, subject: str, *, allow_empty: bool, show_preview: bool = False) -> Path | None:
        def preview() -> None:
            if console.is_terminal:
                console.print(Panel(escape(subject), title="[bold]Workflow Commit Subject[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL), soft_wrap=False)
            else:
                console.print(subject, markup=False, highlight=False, emoji=False, soft_wrap=True)
            console.print()
        return self._handle_message_action(subject, allow_empty=allow_empty, preview=preview if show_preview else None)

    def _handle_message_action(self, message: str, *, allow_empty: bool = False, preview: Callable[[], None] | None = None) -> Path | None:
        if not hasattr(self, "_output_directory"):
            self._prepare_output()
        output = self._resolved_output_path
        if self._cli_auto_commit is not None:
            should_commit = self._cli_auto_commit
        elif self._cli_output_path is not None:
            should_commit = False
        else:
            should_commit = None if self._interactive else True

        saved_path = None
        save_error = None

        def save_message() -> None:
            nonlocal saved_path, save_error
            try:
                options = {"output_path": output} if output is not None else {}
                saved_path = save_draft(message, "commit", self._output_directory, **options)
            except (OSError, UnicodeError) as exc:
                destination = str(output) if output is not None else f"draft in {self._output_directory}"
                save_error = ValueError(f"Could not save commit {destination}: {exc}")
            if saved_path is not None:
                success(f"Saved draft: {escape(str(saved_path))}")
                console.print()
            if save_error is not None:
                warning("Commit draft could not be saved; the preview and requested clipboard handoff remain available.")

        try:
            # Known output-only actions persist before optional rendering; interactive decisions still follow the preview.
            if should_commit is False or output is not None:
                save_message()
            if preview is not None:
                preview()
            if should_commit is None:
                should_commit = self.prompt_confirm("Commit changes directly?", default=True)
                console.print()
                if not should_commit:
                    save_message()
            if save_error is not None:
                self.handoff_to_clipboard(message, leading_space=False)
            elif should_commit:
                command = ["git", "commit"]
                if allow_empty:
                    command.append("--allow-empty")
                command.extend(["-m", message])
                try:
                    subprocess.run(command, check=True, timeout=GIT_COMMIT_TIMEOUT_SECONDS)
                except subprocess.CalledProcessError as exc:
                    self.logger.error("Failed to commit: %s", exc)
                    raise ValueError("Error committing changes. Review the Git output and repository state before retrying.") from exc
                except subprocess.TimeoutExpired as exc:
                    raise ValueError("Git commit timed out. Inspect repository state before retrying.") from exc
                console.print()
                success("Committed changes.")
            else:
                self.handoff_to_clipboard(message, leading_space=False)
        finally:
            if save_error is not None:
                raise save_error
        return saved_path

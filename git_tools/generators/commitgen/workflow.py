"""Fixed-subject workflow commits such as ``chore: open release``."""

import subprocess

from rich.markup import escape
from rich.panel import Panel

from ..base import ALIGN_PANEL, STYLE_BORDER, console, error, success

WORKFLOW_KIND_NORMAL = "normal"
WORKFLOW_KIND_OPEN_RELEASE = "open-release"


class WorkflowCommitMixin:
    """Resolve the commit mode and create workflow commits without the model."""

    def _resolve_commit_mode(self) -> str:
        if self._cli_workflow_kind is not None:
            return self._normalize_workflow_kind(self._cli_workflow_kind)

        if not self._interactive:
            return WORKFLOW_KIND_NORMAL

        choice = self.prompt_select(
            "Select commit mode",
            [
                "Conventional Commit",
                "chore: open release",
            ],
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

    def _handle_workflow_commit(self, workflow_kind: str) -> None:
        staged_files = self._get_staged_files()
        if staged_files and not self._check_sensitive_files():
            return

        try:
            subject = self._build_workflow_subject(workflow_kind)
        except ValueError as exc:
            error(str(exc))
            return

        console.print(
            Panel(
                escape(subject),
                title="[bold]Workflow Commit Subject[/bold]",
                border_style=STYLE_BORDER,
                title_align=ALIGN_PANEL,
            ),
            soft_wrap=False,
        )
        console.print()

        self._handle_fixed_subject_action(
            subject,
            allow_empty=not staged_files,
        )

    def _build_workflow_subject(self, workflow_kind: str) -> str:
        if workflow_kind == WORKFLOW_KIND_OPEN_RELEASE:
            return "chore: open release"
        raise ValueError(f"Unsupported workflow commit kind: {workflow_kind}")

    def _handle_fixed_subject_action(self, subject: str, *, allow_empty: bool) -> None:
        if self._cli_auto_commit is not None:
            should_commit = self._cli_auto_commit
        elif self._interactive:
            should_commit = self.prompt_confirm("Commit changes directly?", default=True)
        else:
            should_commit = True

        if should_commit:
            if self._interactive and self._cli_auto_commit is None:
                console.print()
            commit_command = ["git", "commit"]
            if allow_empty:
                commit_command.append("--allow-empty")
            commit_command.extend(["-m", subject])
            try:
                subprocess.run(commit_command, check=True, timeout=30)
                console.print()
                success("Committed changes.")
            except subprocess.CalledProcessError as exc:
                self.logger.error(f"Failed to create workflow commit: {exc}")
                error("Error committing changes.")
            except subprocess.TimeoutExpired:
                self.logger.error("Workflow commit command timed out")
                error("Git commit timed out.")
            return

        if self._cli_copy_clipboard is not None:
            if self._cli_copy_clipboard:
                if self._interactive and self._cli_auto_commit is None:
                    console.print()
                self.copy_to_clipboard_auto(subject, leading_space=False)
        elif self._interactive:
            self.ask_to_copy_to_clipboard(subject)
        else:
            self.copy_to_clipboard_auto(subject, leading_space=False)

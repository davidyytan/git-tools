"""Commit message generator module.

Generates conventional commit messages from staged git changes using LLM providers.
Includes security checks for sensitive files and validation of commit message format.
"""

import fnmatch
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rich.markup import escape

from git_tools.config.config import settings
from .base import (
    BaseGenerator, console, Panel, info, success, warning, error,
    STYLE_BORDER, STYLE_DIM, STYLE_ERROR, ALIGN_PANEL,
)

logger = logging.getLogger(__name__)
WORKFLOW_KIND_NORMAL = "normal"
WORKFLOW_KIND_OPEN_RELEASE = "open-release"


@dataclass(frozen=True)
class SensitiveFileMatch:
    """A staged file that matched a sensitive filename/path rule."""

    path: str
    pattern: str
    reason: str


class CommitGenerator(BaseGenerator):
    # Patterns for sensitive files that should not be committed
    # Uses fnmatch-style patterns for more precise matching
    SENSITIVE_FILE_PATTERNS = [
        # Environment files (exact matches and variants)
        ".env",
        ".env.*",
        "*.env",
        "git-tools.env",
        # Credential files
        "credentials.json",
        "credentials.yml",
        "credentials.yaml",
        "secrets.json",
        "secrets.yml",
        "secrets.yaml",
        "secrets.txt",
        # Private keys and certificates
        "*.key",
        "*.pem",
        "*.p12",
        "*.pfx",
        "*.crt",
        "*.cer",
        # SSH keys
        "id_rsa",
        "id_rsa.*",
        "id_dsa",
        "id_dsa.*",
        "id_ecdsa",
        "id_ecdsa.*",
        "id_ed25519",
        "id_ed25519.*",
        # AWS
        ".aws/credentials",
        "aws_credentials",
        # Other common sensitive files
        "*.keystore",
        "*.jks",
        "htpasswd",
        ".htpasswd",
        ".netrc",
        ".npmrc",
        ".pypirc",
    ]

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
        self._cli_auto_commit = auto_commit
        self._cli_copy_clipboard = copy_clipboard
        self._cli_force_sensitive = force_sensitive
        self._cli_workflow_kind = workflow_kind

    def _get_staged_files(self) -> List[str]:
        """Get list of staged files from git.

        Returns:
            List of staged file paths
        """
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Failed to get staged files: {e}")
            return []

    def _detect_sensitive_files(self) -> List[SensitiveFileMatch]:
        """Detect if any staged files match sensitive file patterns.

        Uses fnmatch for glob-style pattern matching against both the full path
        and the basename of each file.

        Returns:
            List of sensitive file matches found in staged changes
        """
        import os

        staged_files = self._get_staged_files()
        sensitive_files = []

        for file_path in staged_files:
            file_path_lower = file_path.lower()
            file_name_lower = os.path.basename(file_path).lower()

            for pattern in self.SENSITIVE_FILE_PATTERNS:
                pattern_lower = pattern.lower()
                # Match against both full path and basename
                if (
                    fnmatch.fnmatch(file_name_lower, pattern_lower)
                    or fnmatch.fnmatch(file_path_lower, pattern_lower)
                    or fnmatch.fnmatch(file_path_lower, f"*/{pattern_lower}")
                ):
                    sensitive_files.append(
                        SensitiveFileMatch(
                            path=file_path,
                            pattern=pattern,
                            reason=self._describe_sensitive_pattern(pattern),
                        )
                    )
                    break

        return sensitive_files

    def _describe_sensitive_pattern(self, pattern: str) -> str:
        """Return a human-readable reason for a sensitive file pattern."""
        if pattern in {".env", ".env.*", "*.env", "git-tools.env"}:
            return "environment/configuration file"
        if pattern in {
            "credentials.json",
            "credentials.yml",
            "credentials.yaml",
            "secrets.json",
            "secrets.yml",
            "secrets.yaml",
            "secrets.txt",
            ".aws/credentials",
            "aws_credentials",
        }:
            return "credentials or secrets file"
        if pattern in {
            "*.key",
            "*.pem",
            "*.p12",
            "*.pfx",
            "*.crt",
            "*.cer",
            "id_rsa",
            "id_rsa.*",
            "id_dsa",
            "id_dsa.*",
            "id_ecdsa",
            "id_ecdsa.*",
            "id_ed25519",
            "id_ed25519.*",
        }:
            return "private key, SSH key, or certificate file"
        if pattern in {"*.keystore", "*.jks"}:
            return "keystore file"
        if pattern in {"htpasswd", ".htpasswd", ".netrc", ".npmrc", ".pypirc"}:
            return "authentication/configuration file"
        return "sensitive filename/path pattern"

    def _format_sensitive_file_lines(
        self,
        sensitive_files: List[SensitiveFileMatch | str],
    ) -> List[str]:
        """Format sensitive file matches for CLI output."""
        lines = []
        for sensitive_file in sensitive_files:
            if isinstance(sensitive_file, SensitiveFileMatch):
                lines.append(
                    "  • "
                    f"{escape(sensitive_file.path)} - "
                    f"{escape(sensitive_file.reason)} "
                    f"(matched pattern: {escape(sensitive_file.pattern)})"
                )
            else:
                lines.append(f"  • {escape(sensitive_file)}")
        return lines

    def _format_sensitive_file_block(
        self,
        sensitive_files: List[SensitiveFileMatch | str],
    ) -> str:
        """Format sensitive file matches with context for hard failures."""
        files_list = "\n".join(self._format_sensitive_file_lines(sensitive_files))
        return f"""Sensitive files detected. Unstage them or re-run with --force-sensitive.

Flagged staged files:
{files_list}"""

    def _confirm_commit_sensitive_files(
        self,
        sensitive_files: List[SensitiveFileMatch | str],
    ) -> bool:
        """Prompt user to confirm committing sensitive files.

        Args:
            sensitive_files: List of sensitive file matches

        Returns:
            True if user confirms, False otherwise
        """
        # Build warning message
        files_list = "\n".join(self._format_sensitive_file_lines(sensitive_files))
        warning_text = f"""[bold red]Sensitive files detected in staged changes![/bold red]

The following staged files matched sensitive file rules:
{files_list}

Committing these files may expose:
  • API keys and credentials
  • Environment variables
  • Private keys
  • Secret tokens"""

        console.print()
        console.print(Panel(warning_text.strip(), title="[bold]⚠ WARNING[/bold]", border_style=STYLE_ERROR, title_align=ALIGN_PANEL))
        console.print()

        return self.prompt_confirm("Are you SURE you want to commit these files?", default=False)

    def _build_system_message(self, include_scope: bool, include_footer: bool) -> str:
        """Construct the system message using template.

        Args:
            include_scope: Whether to include scope in commit message
            include_footer: Whether to include footer in commit message

        Returns:
            Formatted system message for the LLM
        """
        scope_instruction = (
            "[optional scope] may be provided to a commit's type, to provide additional "
            "contextual information and is contained within parenthesis in lowercase, e.g., "
            "feat(parser): add ability to parse arrays."
            if include_scope
            else "Do not include the [optional scope]."
        )
        footer_instruction = (
            "Include [optional footer(s)] for breaking changes. If included as a footer, "
            "a breaking change MUST consist of the uppercase text BREAKING CHANGE, followed "
            "by a colon, space, and description, e.g., BREAKING CHANGE: environment variables "
            "now take precedence over config files."
            if include_footer
            else "Do not include the [optional footer(s)]."
        )
        return self.commit_prompt.format(
            scope_instruction=scope_instruction, footer_instruction=footer_instruction
        )

    def generate_commit_message(
        self, diff_content: str, system_msg: str
    ) -> Optional[Dict[str, Any]]:
        """Generate commit message using LangChain chat client.

        Args:
            diff_content: Git diff content
            system_msg: System message with instructions

        Returns:
            LLM response dictionary or None if failed
        """
        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": self._render_prompt_template(
                    "commitgen_user_prompt.txt",
                    diff_content=diff_content,
                ),
            },
        ]
        return self.invoke_llm(messages)

    def parse_commit_message(self, content: str) -> Optional[str]:
        """Extract commit message from code block, preserving original formatting.

        Args:
            content: Raw LLM response content

        Returns:
            Parsed commit message or None if invalid format
        """
        content = content.strip()

        # Extract from code block if present (remove ``` markers and optional language identifier)
        code_block_pattern = r"```(?:[a-z]*\n)?(.*?)```"
        match = re.search(code_block_pattern, content, re.DOTALL)

        if match:
            extracted_content = match.group(1).strip()
        else:
            # If no code block, use content as-is
            extracted_content = content

        # Split into lines and process
        lines = extracted_content.split("\n")
        if not lines:
            return None

        # First line should be the header (type: message or type(scope): message)
        header_line = lines[0].strip()

        # Validate header format (conventional commit structure)
        header_pattern = r"^[a-z]+(\([^)]*\))?!?:\s*.+"
        if not re.match(header_pattern, header_line):
            return None

        # Keep the description as-is (don't lowercase)
        # If there are more lines, validate and format the body
        if len(lines) > 1:
            # Skip the first empty line after header if present
            body_start_idx = 1
            if body_start_idx < len(lines) and not lines[body_start_idx].strip():
                body_start_idx = 2

            # Collect body lines (should be bullet points with dashes)
            body_lines = []
            for line in lines[body_start_idx:]:
                stripped = line.strip()
                if stripped:
                    body_lines.append(line)

            if body_lines:
                # Validate that body lines are bullet points starting with '-'
                for line in body_lines:
                    if not line.strip().startswith("-"):
                        # Body line doesn't follow bullet format, but allow it
                        pass

                body = "\n".join(body_lines)
                return f"{header_line}\n\n{body}"

        return header_line

    def generate_commit(self) -> None:
        """Main commit generation workflow."""
        # CLI mode: add leading blank line to separate from command
        if not self._interactive:
            console.print()

        workflow_kind = self._resolve_commit_mode()
        if workflow_kind != WORKFLOW_KIND_NORMAL:
            self._handle_workflow_commit(workflow_kind)
            return

        diff_content = self._get_and_validate_diff()
        if not diff_content:
            return

        # Check for sensitive files before processing
        if not self._check_sensitive_files():
            return

        diff_content = self._handle_large_diff_processing(diff_content)

        if not self._handle_external_provider_workflow(diff_content):
            return

    def _check_sensitive_files(self) -> bool:
        """Check for sensitive files and get user confirmation if found.

        Uses CLI force_sensitive flag to skip confirmation if set.
        """
        sensitive_files = self._detect_sensitive_files()

        if sensitive_files:
            # Skip confirmation if --force-sensitive was provided
            if self._cli_force_sensitive:
                warning(
                    f"Committing {len(sensitive_files)} sensitive file(s) "
                    "(--force-sensitive)"
                )
                console.print("\n".join(self._format_sensitive_file_lines(sensitive_files)))
                return True

            if not self._interactive:
                error(self._format_sensitive_file_block(sensitive_files))
                return False

            if not self._confirm_commit_sensitive_files(sensitive_files):
                warning("Commit cancelled. Please unstage sensitive files before continuing.")
                console.print(f"  [{STYLE_DIM}]You can unstage files with: git reset HEAD <file>[/{STYLE_DIM}]")
                return False

        return True

    def _get_and_validate_diff(self) -> Optional[str]:
        """Get staged diff and validate it exists."""
        diff_content = self.get_staged_diff()
        if not diff_content:
            warning("No staged changes detected! Exiting...")
            return None

        return diff_content

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
            )
        )
        if self._interactive:
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
                self.copy_to_clipboard_auto(subject)
        elif self._interactive:
            self.ask_to_copy_to_clipboard(subject)
        else:
            self.copy_to_clipboard_auto(subject)

    def _handle_large_diff_processing(self, diff_content: str) -> str:
        """Handle diff processing with size limiting (always prompts for limits)."""
        # Get processing parameters upfront
        max_token_count = self.get_diff_processing_params(settings.default_token_limit)

        # Apply enhanced diff processing
        enhanced_result = self.get_staged_diff_enhanced(max_token_count)
        if enhanced_result:
            enhanced_diff, quota_breakdown = enhanced_result

            # Display quota breakdown if available
            if quota_breakdown:
                # Only add spacing if interactive (questionary → panel transition)
                if self._interactive:
                    console.print()
                self.display_quota_breakdown(quota_breakdown, max_token_count)

            return enhanced_diff

        return diff_content

    def _handle_external_provider_workflow(self, diff_content: str) -> bool:
        """Handle the external provider workflow for commit generation.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults (no scope, no footer, use external providers)
        """
        # Add spacing before interactive prompts (after quota panel)
        if self._interactive:
            console.print()

        # Include scope: CLI param > interactive prompt > default (False)
        if self._cli_include_scope is not None:
            include_scope = self._cli_include_scope
        elif self._interactive:
            include_scope = self.prompt_confirm("Include conventional commit scope?", default=False)
        else:
            include_scope = False

        # Include footer: CLI param > interactive prompt > default (False)
        if self._cli_include_footer is not None:
            include_footer = self._cli_include_footer
        elif self._interactive:
            include_footer = self.prompt_confirm("Include conventional commit footer?", default=False)
        else:
            include_footer = False

        system_msg = self._build_system_message(include_scope, include_footer)

        # In interactive mode, ask if user wants to use external providers
        # In non-interactive mode, always use external providers
        if self._interactive:
            if not self.prompt_confirm("Generate commit message using external providers?", default=True):
                self._handle_local_mode(diff_content, system_msg)
                return False

        return self._generate_with_provider(diff_content, system_msg)

    def _handle_local_mode(self, diff_content: str, system_msg: str) -> None:
        """Handle local mode: build prompt and copy to clipboard."""
        prompt = self._build_full_prompt(diff_content, system_msg)
        self.ask_to_copy_to_clipboard(prompt)

    def _build_full_prompt(self, diff_content: str, system_msg: str) -> str:
        """Build the full prompt for local mode or fallback."""
        return (
            system_msg
            + "\n\n"
            + "Code diffs:\n```\n"
            + diff_content
            + "\n```\n"
            + "\nUsing the rules, template and code diffs, generate a conventional commit message.\n\nConventional commit message:"
        )

    def _generate_with_provider(self, diff_content: str, system_msg: str) -> bool:
        """Generate commit message using external provider."""
        provider = self.select_provider()

        # Check API key - if not configured, offer setup or fall back to local mode
        if not self.ensure_api_key_configured(provider):
            info("Falling back to local mode...")
            prompt = self._build_full_prompt(diff_content, system_msg)
            self.copy_to_clipboard_auto(prompt)
            return False

        model, temperature, max_tokens = self.select_model_params(provider)

        if not self._initialize_service(provider, model, temperature, max_tokens):
            error(f"Failed to initialize {provider} service. Please check your configuration and API keys.")
            return False

        # Spacing before spinner only in interactive mode (Questionary → Spinner)
        # In CLI mode, Panel → Spinner → Panel, spinner disappears leaving Panel → Panel (no spacing)
        if self._interactive:
            console.print()
        response = self.generate_commit_message(diff_content, system_msg)
        if not response:
            error("Failed to generate commit message")
            return False

        self._display_response(response)
        self.display_token_usage(response)
        # Only add spacing if interactive (panel → questionary transition)
        if self._interactive:
            console.print()
        self._handle_commit_action(response)
        return True

    def _display_response(self, response: Dict[str, Any]) -> None:
        """Display LLM response panels."""
        self.display_reasoning(response)
        console.print(Panel(escape(response["content"].strip()), title="[bold]Raw Response[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))
        commit_message = self.parse_commit_message(response["content"])
        if commit_message:
            console.print(Panel(escape(commit_message.strip()), title="[bold]Commit Message[/bold]", border_style=STYLE_BORDER, title_align=ALIGN_PANEL))

    def _handle_commit_action(self, response: Dict[str, Any]) -> None:
        """Handle the commit or clipboard action.

        Uses CLI parameters if provided. If not:
        - Interactive mode: prompts for input
        - Non-interactive mode: uses defaults (commit directly)

        Args:
            response: LLM response dictionary
        """
        raw_content = response["content"]
        commit_message = self.parse_commit_message(raw_content)

        if not commit_message:
            error("Invalid commit message format")
            return

        # Determine if we should commit directly: CLI param > interactive prompt > default (True)
        if self._cli_auto_commit is not None:
            should_commit = self._cli_auto_commit
        elif self._interactive:
            should_commit = self.prompt_confirm("Commit changes directly?", default=True)
        else:
            should_commit = True  # Default: commit directly

        if should_commit:
            # Spacing before git output (Panel → Text in CLI, Questionary → Text in interactive)
            console.print()
            try:
                subprocess.run(
                    ["git", "commit", "-m", commit_message], check=True, timeout=30
                )
                console.print()
                success("Committed changes.")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"Failed to commit: {e}")
                error("Error committing changes.")
            except subprocess.TimeoutExpired:
                self.logger.error("Git commit command timed out")
                error("Git commit timed out.")
        else:
            content_to_copy = (
                commit_message
                if commit_message and commit_message.strip()
                else raw_content
            )
            # Determine if we should copy to clipboard: CLI param > interactive prompt > default (True)
            if self._cli_copy_clipboard is not None:
                if self._cli_copy_clipboard:
                    self.copy_to_clipboard_auto(content_to_copy)
            elif self._interactive:
                self.ask_to_copy_to_clipboard(content_to_copy)
            else:
                self.copy_to_clipboard_auto(content_to_copy)


def generate_commit() -> None:
    """Entry point for commit generation.

    Creates a CommitGenerator instance and runs the generation workflow.
    """
    return CommitGenerator().generate_commit()


if __name__ == "__main__":
    generate_commit()

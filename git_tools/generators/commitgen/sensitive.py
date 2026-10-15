"""Sensitive-file detection for staged changes."""

import fnmatch
import subprocess
from dataclasses import dataclass
from typing import List

from rich.markup import escape
from rich.panel import Panel

from ..base import ALIGN_PANEL, STYLE_DIM, STYLE_ERROR, console, error, warning


@dataclass(frozen=True)
class SensitiveFileMatch:
    """A staged file that matched a sensitive filename/path rule."""

    path: str
    pattern: str
    reason: str


class SensitiveFileGuardMixin:
    """Flag staged files that look like secrets and gate the commit on them."""

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

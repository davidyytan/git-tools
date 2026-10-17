"""Azure DevOps PR description limits: detection, measurement, enforcement."""

import subprocess
from typing import Optional
from urllib.parse import urlparse

from git_tools.settings.settings import settings

from ..base import console, info, warning

# Azure DevOps caps the pull request description at 4000 characters.
AZURE_PR_DESCRIPTION_LIMIT = 4000

AZURE_PR_DESCRIPTION_INSTRUCTION = (
    "Keep the generated PR description within the configured PR length limit. "
    "Measure length in UTF-16 units and prioritize the most important changes."
)


def count_ado_chars(text: str) -> int:
    """Count UTF-16 code units, matching how Azure DevOps measures strings.

    Azure DevOps runs on .NET, so characters outside the Basic Multilingual
    Plane (e.g. emoji) count as two units. For ASCII text this equals
    ``len(text)``.
    """
    return len(text.encode("utf-16-le")) // 2


class AzureLimitMixin:
    """Decide whether to cap the PR description and retry once when it overflows."""

    @staticmethod
    def _is_azure_devops_url(url: Optional[str]) -> bool:
        """Return True when the remote URL points at Azure DevOps."""
        candidate = (url or "").strip()
        if not candidate:
            return False
        if "://" not in candidate:
            # Convert scp-like syntax (git@ssh.dev.azure.com:v3/...) to ssh://.
            if "@" in candidate and ":" in candidate:
                candidate = "ssh://" + candidate.replace(":", "/", 1)
            else:
                return False
        try:
            parsed = urlparse(candidate)
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname in {"dev.azure.com", "ssh.dev.azure.com"}:
            return True
        return hostname.endswith(".visualstudio.com")

    def _get_origin_url(self) -> Optional[str]:
        """Return the origin remote URL, or None when it cannot be determined."""
        try:
            output = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=10,
            ).strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None
        return output or None

    def _should_apply_azure_limit(self) -> bool:
        """Resolve the Azure PR description limit.

        Resolution order: CLI param > saved disable > origin detection.
        Saved auto detects origin without a routine confirmation. Interactive
        runs still report the detection; explicit overrides apply to one run.
        """
        if self._cli_azure_limit is not None:
            return self._cli_azure_limit

        if settings.azure_pr_limit == "false":
            return False

        origin_url = self._get_origin_url()
        is_azure = self._is_azure_devops_url(origin_url)

        if not self._interactive:
            return is_azure

        if is_azure:
            info("Origin remote: Azure DevOps repository")
        elif origin_url:
            info("Origin remote: Non-Azure DevOps repository")
        else:
            info("Origin remote: Not configured")
        console.print()

        return is_azure

    def _enforce_azure_pr_description_limit(
        self, parsed: str, content: str, system_msg: str
    ) -> str:
        """Retry once when the generated PR description exceeds the ADO limit.

        The count covers the generated description. No commit log is appended.
        When the description still exceeds the limit after the
        retry, warn but keep the content: nothing is truncated or discarded.
        """
        limit = settings.azure_pr_max_chars
        count = count_ado_chars(parsed)
        if count <= limit:
            return parsed

        info(
            f"PR description is {count}/{limit} characters; "
            "requesting a condensed rewrite."
        )
        retry_system_msg = (
            f"{system_msg}\n\n"
            "The previously generated PR description was "
            f"{count} characters, exceeding the configured PR limit of "
            f"{limit} characters. Rewrite the PR description "
            f"to fit within {limit} characters. Keep the most important details from the "
            "provided diffs and/or commits and do not invent new information. "
            "Wrap the rewritten PR in a single code block with triple backticks."
        )
        response = self.generate_content(content, retry_system_msg)
        if response:
            repaired = self._normalize_pr_output(
                self.parse_generated_content(response["content"])
            )
            if repaired:
                parsed = repaired
                count = count_ado_chars(parsed)

        if count > limit:
            warning(
                f"PR description is {count}/{limit} characters, "
                "which exceeds the configured PR limit. Keeping the content without truncation."
            )
        return parsed

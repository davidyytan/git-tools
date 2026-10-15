"""Fixed PR titles for workflow PRs and the output normalization that enforces them."""

import re
from typing import Optional

from ..bumpgen import Version
from .contexts import RELEASE_BRANCH_PATTERN, _format_release_tuple


class FixedTitleMixin:
    """Derive the fixed title, its prompt instructions, and normalize model output."""

    def _build_pr_title_block(self) -> str:
        fixed_title = self._resolve_fixed_pr_title()
        if fixed_title is not None:
            return f"## Title: {fixed_title}"

        placeholder_title = self._fixed_pr_title_placeholder()
        if placeholder_title is not None:
            return f"## Title: {placeholder_title}"

        return (
            "## Title: [Use a single Conventional Commit header for develop PRs]"
        )

    def _fixed_pr_title_placeholder(self) -> Optional[str]:
        if self.start_pr:
            return "Start <x.y.z>"
        if self.release_pr:
            return "Release <x.y.z>"
        if self.hotfix_pr:
            return "Hotfix <x.y.z>"
        if self.backmerge_release_pr:
            return "Backmerge Release <x.y.z>"
        if self.backmerge_hotfix_pr:
            return "Backmerge Hotfix <x.y.z>"
        return None

    def _build_pr_title_instruction(self) -> str:
        if self.start_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_start.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Start <x.y.z>",
            ).strip()

        if self.release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_release.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Release <x.y.z>",
            ).strip()

        if self.hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Hotfix <x.y.z>",
            ).strip()

        if self.backmerge_release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_backmerge_release.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Release <x.y.z>",
            ).strip()

        if self.backmerge_hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_pr_backmerge_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Hotfix <x.y.z>",
            ).strip()

        return self._load_prompt_template(
            "issuepr_title_instruction_pr_default.txt"
        ).strip()

    def _build_both_title_instruction(self) -> str:
        if self.start_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_start.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Start <x.y.z>",
            ).strip()

        if self.release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_release.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Release <x.y.z>",
            ).strip()

        if self.hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title() or "Hotfix <x.y.z>",
            ).strip()

        if self.backmerge_release_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_backmerge_release.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Release <x.y.z>",
            ).strip()

        if self.backmerge_hotfix_pr:
            return self._render_prompt_template(
                "issuepr_title_instruction_both_backmerge_hotfix.txt",
                fixed_title=self._resolve_fixed_pr_title()
                or "Backmerge Hotfix <x.y.z>",
            ).strip()

        return self._load_prompt_template(
            "issuepr_title_instruction_both_default.txt"
        ).strip()

    def _resolve_fixed_pr_title(self) -> Optional[str]:
        if self.start_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            inferred_target = self._infer_start_target_version()
            return f"Start {inferred_target}" if inferred_target else None

        if self.release_pr:
            if self._promotion_pr_context is not None:
                return f"Release {self._promotion_pr_context.target_version}"
            branch = self._get_current_branch_name()
            match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
            if match:
                return f"Release {match.group('version')}"
            return None

        if self.hotfix_pr:
            if self._promotion_pr_context is not None:
                return f"Hotfix {self._promotion_pr_context.target_version}"
            base_branch = self._default_release_base_branch()
            base_version_text = self._load_version_from_ref(base_branch)
            if base_version_text is None:
                return None
            base_version = Version.parse(base_version_text)
            return f"Hotfix {_format_release_tuple(base_version.bump('PATCH').release)}"

        if self.backmerge_release_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            branch = self._get_current_branch_name()
            match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
            if match:
                return f"Backmerge Release {match.group('version')}"
            return None

        if self.backmerge_hotfix_pr:
            if self._workflow_pr_context is not None:
                return self._workflow_pr_context.fixed_title
            if self._cli_workflow_version:
                target = self._validate_semver_tuple(
                    self._cli_workflow_version.strip(),
                    label="already-promoted hotfix version",
                )
                return f"Backmerge Hotfix {target}"
            return None

        return None

    def _normalize_pr_output(self, content: str) -> str:
        normalized = content.strip()
        fixed_title = self._resolve_fixed_pr_title()

        if self.generation_type in {"pr", "both"}:
            normalized = re.sub(
                r"(?ms)^## Related Issue\s*\nIssue:.*?(?:\n{2,}|(?=## )|$)",
                "",
                normalized,
            ).strip()
            normalized = re.sub(
                r"(?m)^Next Develop:.*(?:\n|$)",
                "",
                normalized,
            ).strip()

        if fixed_title is None or self.generation_type not in {"pr", "both"}:
            return normalized

        title_line = f"## Title: {fixed_title}"
        if re.search(r"(?m)^## Title:.*$", normalized):
            normalized = re.sub(
                r"(?m)^## Title:.*$",
                title_line,
                normalized,
                count=1,
            ).strip()
        else:
            normalized = f"{title_line}\n\n{normalized}".strip()

        return normalized

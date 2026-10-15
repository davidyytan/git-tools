"""System and user prompt assembly for issue and PR generation."""

from typing import Any, Dict, Optional

from git_tools.templates import get_issue_template, get_pr_template


class PromptAssemblyMixin:
    """Compose the templated system message and the user prompt."""

    def _build_system_message(self, content: str, input_source: str) -> str:
        """Construct appropriate system message based on generation type and input source.

        Args:
            content: The content to generate from
            input_source: Source of input ('d' for diffs, 'c' for commits, 'b' for both)

        Returns:
            Formatted system message for the LLM
        """
        pr_template = self._build_pr_template()
        issue_template = get_issue_template()

        template_map = {
            "pr": pr_template,
            "issue": issue_template,
            "both": pr_template + "\n\n" + issue_template,
        }
        instruction_map = {
            "issue": self._load_prompt_template("issuepr_generation_issue.txt").strip(),
            "pr": self._load_prompt_template("issuepr_generation_pr.txt").strip(),
            "both": self._load_prompt_template("issuepr_generation_both.txt").strip(),
        }
        title_instruction_map = {
            "issue": self._load_prompt_template("issuepr_title_instruction_issue.txt").strip(),
            "pr": self._build_pr_title_instruction(),
            "both": self._build_both_title_instruction(),
        }
        focus_instruction = self._load_prompt_template(
            {
                "d": "issuepr_focus_instruction_diffs.txt",
                "c": "issuepr_focus_instruction_commits.txt",
            }.get(input_source, "issuepr_focus_instruction_both.txt")
        ).strip()

        return self.issuepr_prompt.format(
            generation_type_instruction=instruction_map[self.generation_type],
            template_content=template_map[self.generation_type],
            title_instruction=title_instruction_map[self.generation_type],
            focus_instruction=focus_instruction,
        )

    def _build_pr_template(self) -> str:
        return get_pr_template().format(title_block=self._build_pr_title_block())

    def _build_full_prompt(self, content: str) -> str:
        """Build full prompt based on generation type."""
        prompt_map = {
            "both": self._load_prompt_template("issuepr_user_prompt_both.txt").strip(),
            "pr": self._load_prompt_template("issuepr_user_prompt_pr.txt").strip(),
            "issue": self._load_prompt_template("issuepr_user_prompt_issue.txt").strip(),
        }
        instruction = prompt_map.get(self.generation_type, prompt_map["both"])
        return f"{content}\n\n{instruction}"

    def generate_content(
        self, content: str, system_msg: str
    ) -> Optional[Dict[str, Any]]:
        """Generate content using LangChain chat client.

        Args:
            content: The content to generate from (diffs, commits, and/or user context)
            system_msg: System message with instructions and templates

        Returns:
            LLM response dictionary or None if failed
        """
        full_prompt = self._build_full_prompt(content)
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": full_prompt},
        ]
        return self.invoke_llm(messages)

    def parse_generated_content(self, content: str) -> str:
        """Remove first and last lines from the generated content.

        Args:
            content: Raw content from LLM response

        Returns:
            Parsed content with first and last lines removed
        """
        lines = content.split("\n")
        if len(lines) > 2:
            return "\n".join(lines[1:-1])
        return content

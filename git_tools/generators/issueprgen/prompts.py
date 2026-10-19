"""System and user prompt assembly for issue and PR generation."""

import re
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
        """Unwrap a complete outer code fence without discarding response text.

        Only a single fenced block covering the whole nonblank response is
        unwrapped. Unfenced, partial, or ambiguous wrappers are left untouched.
        Interior fences shorter than the outer marker remain part of the body.
        """
        lines = content.splitlines(keepends=True)
        first = 0
        last = len(lines) - 1
        while first <= last and not lines[first].strip():
            first += 1
        while last >= first and not lines[last].strip():
            last -= 1
        if first >= last:
            return content

        opening = re.fullmatch(
            r" {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)",
            lines[first].rstrip("\r\n"),
        )
        if opening is None:
            return content
        fence = opening.group("fence")
        if fence[0] == "`" and "`" in opening.group("info"):
            return content

        # A closing fence must use the opening marker and be at least as long.
        closing = re.compile(
            rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*"
        )
        if closing.fullmatch(lines[last].rstrip("\r\n")) is None:
            return content
        if any(
            closing.fullmatch(line.rstrip("\r\n"))
            for line in lines[first + 1:last]
        ):
            return content

        body = "".join(lines[first + 1:last])
        # The line ending before the closing fence belongs to the wrapper.
        if body.endswith("\r\n"):
            return body[:-2]
        if body.endswith(("\n", "\r")):
            return body[:-1]
        return body

"""Conventional Commit prompt construction and response parsing."""

import re
from typing import Any, Dict, Optional


class CommitMessageMixin:
    """Build the commit prompt, call the model, and validate the reply."""

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

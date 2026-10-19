"""Conventional Commit prompt construction and response parsing."""

import re
from typing import Any, Dict, Literal, Optional


class CommitMessageMixin:
    """Build the commit prompt, call the model, and validate the reply."""

    def _build_system_message(
        self,
        include_scope: bool,
        include_footer: bool,
        include_body: bool = True,
        body_style: Literal["bullets", "prose"] = "bullets",
    ) -> str:
        """Build instructions and a template for the chosen commit structure."""
        if body_style not in {"bullets", "prose"}:
            raise ValueError(f"Unsupported commit body style: {body_style}")

        message_template = "<type>" + ("[optional scope]" if include_scope else "")
        message_template += "[!]: <description>"
        if include_body:
            message_template += "\n\n[optional body]"
        if include_footer:
            message_template += "\n\n[optional footer(s)]"

        if include_body:
            body_instruction = (
                "[optional body] MAY provide additional context below the required header, "
                "beginning one blank line after it. "
            )
            body_instruction += (
                "Use concise dash (-) bullets for body details."
                if body_style == "bullets"
                else "Use concise prose paragraphs for body details, not list markers. "
                "Separate paragraphs with blank lines."
            )
        else:
            body_instruction = (
                "Do not include a body. Output only the required subject/header"
                + (" and any permitted, supported footer(s)." if include_footer else ".")
            )
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
            "now take precedence over config files. Include issue references only when "
            "supplied by the input. Include footers only for actual breaking changes or "
            "supported issue references; omit them otherwise. Never invent breaking changes, "
            "issue numbers, or other facts. Separate footers from the header or body with "
            "a blank line."
            if include_footer
            else "Do not include the [optional footer(s)]. For actual breaking changes, "
            "retain the ! marker before the header colon; do not put BREAKING CHANGE "
            "in the body."
        )
        return self.commit_prompt.format(
            message_template=message_template,
            scope_instruction=scope_instruction,
            body_instruction=body_instruction,
            footer_instruction=footer_instruction,
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
        """Validate the header and preserve body/footer formatting.

        Only complete matching outer fences are unwrapped; never search for an
        arbitrary inner block. Boundary blank lines and the header separator may
        be normalized, but paragraph breaks, indentation, and footer text remain.
        """
        lines = content.splitlines(keepends=True)
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()

        if len(lines) >= 2:
            opening = re.fullmatch(
                r" {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\r\n]*)",
                lines[0].rstrip("\r\n"),
            )
            if opening is not None:
                fence = opening.group("fence")
                closing = re.compile(
                    rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*"
                )
                valid_info = fence[0] != "`" or "`" not in opening.group("info")
                if (
                    valid_info
                    and closing.fullmatch(lines[-1].rstrip("\r\n"))
                    and not any(
                        closing.fullmatch(line.rstrip("\r\n"))
                        for line in lines[1:-1]
                    )
                ):
                    lines = lines[1:-1]

        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return None

        header_line = lines[0].strip()
        if not re.fullmatch(r"[a-z]+(?:\([^)]*\))?!?:[ \t]*\S[^\r\n]*", header_line):
            return None

        body_start = 1
        while body_start < len(lines) and not lines[body_start].strip():
            body_start += 1
        if body_start == len(lines):
            return header_line

        # Keep body line endings and whitespace; only its terminal newline is a
        # boundary. Use the header's line ending for an inserted blank separator.
        newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
        body = "".join(lines[body_start:]).rstrip("\r\n")
        return header_line + newline * 2 + body

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

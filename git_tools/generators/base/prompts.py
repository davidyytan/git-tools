"""Prompt loading and XML packaging for generator instructions and source evidence."""

import json
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def fenced_evidence(content: str) -> str:
    """Legacy display/replay helper; runtime source evidence uses XML instead."""
    longest = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{content}\n{fence}"


def _valid_xml_text(content: str) -> bool:
    return all(char in "\t\n\r" or 0x20 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD or 0x10000 <= ord(char) <= 0x10FFFF for char in content)


def _escape_xml(content: str) -> str:
    # Encode CR after escaping ampersands: XML parsers otherwise normalize CRLF.
    return escape(content).replace("\r", "&#13;")


def xml_evidence(tag: str, content: str) -> str:
    """Serialize source text reversibly, without adding whitespace to its value."""
    if tag not in {"commit", "commit_group", "diff", "context", "workflow_context"}:
        raise ValueError(f"Unsupported evidence tag: {tag}")
    encoding = ""
    if not _valid_xml_text(content):
        content = json.dumps(content, ensure_ascii=True)
        encoding = ' encoding="json"'
    return f"<{tag}{encoding}>{_escape_xml(content)}</{tag}>"


def split_diff_records(content: str) -> tuple[str, ...]:
    """Losslessly slice processed Git file diffs, retaining truncation annotations."""
    pattern = re.compile(r"(?m)^diff --git |^# Truncated diff for .+ \(original: \d+ tokens\)\r?$")
    starts = []
    annotated_header = None
    for match in pattern.finditer(content):
        if match.group().startswith("# Truncated diff for "):
            starts.append(match.start())
            annotated_header = match.end() + (1 if content[match.end():match.end() + 1] == "\n" else 0)
        elif match.start() != annotated_header:
            starts.append(match.start())
    if not starts:
        return (content,) if content else ()
    starts[0] = 0  # Retain any preamble with the first known record.
    ends = starts[1:] + [len(content)]
    return tuple(content[start:end] for start, end in zip(starts, ends))


def diff_evidence(content: str) -> str:
    return "\n\n".join(xml_evidence("diff", part) for part in split_diff_records(content))


def commit_evidence(messages: str | tuple[str, ...]) -> str:
    if isinstance(messages, str):
        # Older overrides/mocks may return an aggregate: never guess blank-line boundaries.
        return '<commit_messages boundaries="unknown">' + xml_evidence("commit_group", messages) + "</commit_messages>"
    return "<commit_messages>\n" + "\n".join(xml_evidence("commit", message) for message in messages) + "\n</commit_messages>"


def messages_have_content(messages: str | tuple[str, ...] | None) -> bool:
    values = (messages,) if isinstance(messages, str) else messages or ()
    return any(value.strip() for value in values)


def _system_text(tag: str, text: str, kind: str | None = None) -> str:
    if not _valid_xml_text(text):
        raise ValueError(f"Invalid XML character in system {tag} text")
    attribute = "" if kind is None else " kind=" + quoteattr(kind)
    return f"<{tag}{attribute}>{_escape_xml(text)}</{tag}>"


def wrap_system_prompt(content: str, *additional_instructions: str, templates: tuple[tuple[str, str], ...] | None = None) -> str:
    """Package independent instructions/layouts; append Azure instructions only to rules."""
    if content.startswith("<system_prompt"):
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise ValueError("Malformed structured system prompt") from exc
        children = list(root)
        if root.tag != "system_prompt" or root.attrib or (root.text or "").strip() or not children or children[0].tag != "rules" or children[0].attrib or sum(node.tag == "rules" for node in children) != 1:
            raise ValueError("Expected one rules block followed by system templates")
        if any(len(node) or (node.tail or "").strip() for node in children) or any(node.tag != "template" or set(node.attrib) != {"kind"} or node.attrib["kind"] not in {"commit", "pr", "issue"} for node in children[1:]):
            raise ValueError("Invalid system template structure")
        if templates is not None:
            raise ValueError("System templates are already packaged")
        if not additional_instructions:
            return content
        content = children[0].text or ""
        templates = tuple((node.attrib["kind"], node.text or "") for node in children[1:])
    rules = "\n\n".join((content, *additional_instructions))
    blocks = [_system_text("rules", rules)]
    for kind, text in templates or ():
        if kind not in {"commit", "pr", "issue"}:
            raise ValueError(f"Unsupported system template kind: {kind}")
        blocks.append(_system_text("template", text, kind))
    return "<system_prompt>\n" + "\n\n".join(blocks) + "\n</system_prompt>"


class PromptTemplateMixin:
    """Load and render prompt templates by file name."""

    def _load_prompt_template(self, filename: str) -> str:
        """Load a complete instruction or user-prompt asset."""
        try:
            with open(PROMPTS_DIR / filename, "r") as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"Failed to load prompt template {filename}: {str(e)}")
            raise e

    def _render_prompt_template(self, filename: str, **kwargs: Any) -> str:
        """Load and optionally format a prompt template from file."""
        template = self._load_prompt_template(filename)
        return template.format(**kwargs) if kwargs else template

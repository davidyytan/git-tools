"""Commitizen config model, discovery, and lossless TOML field updates."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..bumpgen import DEFAULT_SCHEME, Scheme

VERSION_SCHEME_LABEL: dict[Scheme, str] = {"semver2": "semver2", "semver": "semver"}
SUPPORTED_CONFIG_FILES = (".cz.toml",)
DEDICATED_CONFIG_FILES = (".cz.toml",)
LEGACY_UNSUPPORTED_CONFIG_FILES = ("cz.toml",)
COMMITIZEN_SECTION_HEADER = "[tool.commitizen]"
# Kept for compatibility. Updates use TOML tokens, not a section regex: headers
# can be quoted/spaced, and apparent headers can occur inside multiline strings.
COMMITIZEN_SECTION_REGEX = re.compile(
    r"(?ms)^\[tool\.commitizen\]\n.*?(?=^\[[^\n]+\]\n|\Z)"
)


class CzInitError(RuntimeError):
    """Raised when the init flow cannot write a safe config."""


@dataclass(frozen=True)
class CzInitOptions:
    config_file: str
    version: str
    tag_format: str
    major_version_zero: bool
    scheme: Scheme = DEFAULT_SCHEME


def find_existing_commitizen_config(root: Path) -> Path | None:
    path = root / ".cz.toml"
    return path if path.exists() else None


def find_legacy_commitizen_config(root: Path) -> Path | None:
    for relative_path in LEGACY_UNSUPPORTED_CONFIG_FILES:
        path = root / relative_path
        if path.exists():
            return path
    tool = read_toml(root / "pyproject.toml").get("tool")
    if isinstance(tool, dict) and isinstance(tool.get("commitizen"), dict):
        return root / "pyproject.toml"
    return None


def _parse_toml(text: str, location: object) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CzInitError(
            f"Invalid TOML in {location}: {exc}. No configuration was changed. "
            "Repair the TOML before updating; for a fresh config, back up and "
            "remove the existing file first. --force updates valid config, not resets it."
        ) from exc


def read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    return _parse_toml(path.read_text(encoding="utf-8"), path)


def read_nested_string(data: dict, keys: tuple[str, ...]) -> str | None:
    current: object = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, str) else None


def build_commitizen_section(options: CzInitOptions, *, updating: bool = False) -> str:
    lines = [
        COMMITIZEN_SECTION_HEADER,
        'name = "cz_conventional_commits"',
        f"tag_format = {json.dumps(options.tag_format, ensure_ascii=False)}",
        f"version_scheme = {json.dumps(VERSION_SCHEME_LABEL[options.scheme])}",
        f"version = {json.dumps(options.version)}",
    ]
    if options.major_version_zero or updating:
        lines.append(f"major_version_zero = {str(options.major_version_zero).lower()}")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class _Token:
    text: str
    start: int
    end: int


def _tokens(text: str) -> list[_Token]:
    """Lex validated TOML, retaining spans but skipping comments/spacing.

    Strings (including multiline strings and their escapes) are single tokens,
    so comments, equals signs and table-looking text inside them stay opaque.
    tomllib remains the authority on grammar and validity.
    """
    result: list[_Token] = []
    i = 0
    while i < len(text):
        start = i
        char = text[i]
        if char in " \t\r":
            i += 1
            continue
        if char == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if char in "\"'":
            quote = char * (3 if text.startswith(char * 3, i) else 1)
            i += len(quote)
            while i < len(text):
                if char == '"' and text[i] == "\\":
                    i += 2
                elif text.startswith(quote, i):
                    i += len(quote)
                    # Multiline delimiters may end in four or five quotes.
                    if len(quote) == 3:
                        while i < len(text) and text[i] == char:
                            i += 1
                    break
                else:
                    i += 1
        elif char in "\n[]=.,{}":
            i += 1
        else:
            while i < len(text) and text[i] not in " \t\r\n#\"'[]=.,{}":
                i += 1
        result.append(_Token(text[start:i], start, i))
    return result


def _key_path(tokens: list[_Token]) -> tuple[str, ...]:
    # Let tomllib decode quoted keys, escapes, whitespace and dotted key paths.
    value = tomllib.loads("".join(token.text for token in tokens) + " = 0")
    path: list[str] = []
    while isinstance(value, dict):
        key, value = next(iter(value.items()))
        path.append(key)
    return tuple(path)


def _field_spans(text: str) -> tuple[dict, dict, dict]:
    """Locate assignment values, explicit sections and inline table closers."""
    tokens = _tokens(text)
    fields: dict[tuple[str, ...], tuple[int, int, tuple[str, ...]]] = {}
    sections: dict[tuple[str, ...], int] = {}
    inline: dict[tuple[str, ...], tuple[int, bool]] = {}
    scope: tuple[str, ...] = ()
    i = 0

    def assignment(index: int, parent: tuple[str, ...], *, in_inline: bool) -> int:
        start = index
        while tokens[index].text != "=":
            index += 1
        path = parent + _key_path(tokens[start:index])
        index += 1
        value_start = tokens[index].start
        if tokens[index].text == "{":
            index += 1
            empty = tokens[index].text == "}"
            while tokens[index].text != "}":
                if tokens[index].text in (",", "\n"):
                    index += 1
                else:
                    index = assignment(index, path, in_inline=True)
            inline[path] = (tokens[index].start, empty)
            index += 1
        else:
            depth = 0
            while index < len(tokens):
                token = tokens[index].text
                if depth == 0 and (token == "\n" or (in_inline and token in (",", "}"))):
                    break
                if token in ("[", "{"):
                    depth += 1
                elif token in ("]", "}"):
                    depth -= 1
                index += 1
        fields[path] = (value_start, tokens[index - 1].end, scope)
        return index

    while i < len(tokens):
        if tokens[i].text == "\n":
            i += 1
        elif tokens[i].text == "[":
            sections[scope] = tokens[i].start
            i += 1
            array = tokens[i].text == "["
            i += int(array)
            start = i
            while tokens[i].text != "]":
                i += 1
            scope = _key_path(tokens[start:i])
            i += 1 + int(array)
        else:
            i = assignment(i, scope, in_inline=False)
    sections[scope] = len(text)
    return fields, sections, inline


def upsert_commitizen_section(existing_text: str, section_text: str) -> str:
    """Merge init fields without reserializing or replacing the user's policy.

    Existing custom plugin names are retained. Only init's resolved version,
    scheme, tag format and zero-major policy are updated; other values and all
    surrounding text survive. Validate the complete result before any write.
    """
    existing = _parse_toml(existing_text, "existing config")
    incoming = _parse_toml(section_text, "generated config")["tool"]["commitizen"]
    tool = existing.get("tool", {})
    if not isinstance(tool, dict) or not isinstance(tool.get("commitizen", {}), dict):
        raise CzInitError("Cannot update config: tool.commitizen must be a TOML table.")
    commitizen = tool.get("commitizen", {})
    path = ("tool", "commitizen")
    try:
        fields, sections, inline = _field_spans(existing_text)
    except (IndexError, ValueError, StopIteration) as exc:
        raise CzInitError(
            "Cannot safely update this TOML layout. No changes were written; "
            "edit the configuration manually or simplify its table layout first."
        ) from exc
    edits: list[tuple[int, int, str]] = []
    missing: dict[str, object] = {}
    for key, value in incoming.items():
        if key == "name" and key in commitizen:
            continue
        if key in commitizen and commitizen[key] == value:
            continue
        if key not in commitizen:
            missing[key] = value
            continue
        span = fields.get(path + (key,))
        if span is None:
            raise CzInitError(f"Cannot safely update tool.commitizen.{key}; no changes were written.")
        edits.append((span[0], span[1], json.dumps(value, ensure_ascii=False)))

    if missing:
        inline_parent = next((p for p in (path, ("tool",)) if p in inline), None)
        if inline_parent is not None:
            position, empty = inline[inline_parent]
            prefix = ".".join(path[len(inline_parent):])
            prefix = prefix + "." if prefix else ""
            added = ", ".join(f"{prefix}{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in missing.items())
            edits.append((position, position, ("" if empty else ", ") + added))
        else:
            # Dotted assignments define their parent table and cannot safely be
            # followed by a second declaration of that same table.
            parents = [scope for p, (_, _, scope) in fields.items()
                       if p[:2] == path and path[:len(scope)] == scope]
            parent = path if path in sections else (max(parents, key=len) if parents else None)
            if parent is not None:
                position = sections[parent]
                prefix = ".".join(path[len(parent):])
                prefix = prefix + "." if prefix else ""
                added = "".join(f"{prefix}{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in missing.items())
                if position and existing_text[position - 1] != "\n":
                    added = "\n" + added
            else:
                position = len(existing_text)
                added = ("\n\n" if existing_text and not existing_text.endswith("\n\n") else "")
                added += COMMITIZEN_SECTION_HEADER + "\n"
                added += "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in missing.items())
            edits.append((position, position, added))

    result = existing_text
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    _parse_toml(result, "updated config")
    return result

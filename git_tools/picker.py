"""agent-cli's pickers (``agent_cli/ui/shell/picker.py`` and ``keys.py``), for git-tools' settings.

The same UX as agent-cli's settings:

- ↑/↓ moves the ``▸`` marker; Enter picks the highlighted row.
- 1-9 jumps directly and resolves (while every row is on screen).
- A list longer than 12 rows pages (PgUp/PgDn) instead of growing.
- Esc backs out (returns ``None``).
- The picker erases itself when done, so a settings session leaves no scrollback trace beyond the status lines it prints.

Adapted to git-tools: synchronous; Ctrl+C raises ``KeyboardInterrupt`` (git-tools exits the whole command on it, while Esc goes back one level); and each picker is also offered as a questionary-shaped question (``select``, ``pick``, ``text``, ``password``) whose ``application`` and ``unsafe_ask`` are what ``git_tools.navigation.ask_with_back`` asks with. A ``← Back`` row is dropped, since Esc is the way back here, as in agent-cli.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Sequence

from git_tools.navigation import BACK

# prompt-toolkit waits 0.5s before deciding a bare Esc is not the start of an escape sequence; agent-cli's keys.py keeps a tiny grace window instead.
ESCAPE_FLUSH_TIMEOUT = 0.01
KEY_BINDING_SEQUENCE_TIMEOUT = 0.05

#: Picker chrome: the title and the cursor in agent-cli's prompt blue, the row numbers, the about line and the key hint in its status grey.
_ACCENT = "bold #87d7ff"
_DIM = "#6b7280"
#: Lists longer than this page instead of growing (agent-cli's ``_pick`` threshold).
PAGE_THRESHOLD = 12
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: One row's text as styled pieces, prompt_toolkit style: ``[(style, text), …]``.
Fragments = Sequence[tuple[str, str]]


def tune_escape_latency(app: Any) -> Any:
    """agent-cli's keys.tune_escape_latency: fast bare-Esc response."""
    try:
        app.ttimeoutlen = ESCAPE_FLUSH_TIMEOUT
        app.timeoutlen = KEY_BINDING_SEQUENCE_TIMEOUT
    except Exception:  # pragma: no cover - defensive for prompt-toolkit changes
        pass
    return app


def _row_number(index: int, total: int) -> str:
    """Row number, zero-padded to the width of the largest one."""
    return f"{index + 1:0{len(str(total))}d}"


def _cancel_binding(kb: Any, result: dict[str, Any]) -> None:
    @kb.add("escape", eager=True)
    def _cancel(event: Any) -> None:
        result["value"] = None
        event.app.exit()

    @kb.add("c-c", eager=True)
    def _interrupt(event: Any) -> None:
        event.app.exit(exception=KeyboardInterrupt())


def _application(body: Callable[[], Any], kb: Any, *, style: Any = None, input: Any = None, output: Any = None) -> Any:
    from prompt_toolkit import Application
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    window = Window(content=FormattedTextControl(body), always_hide_cursor=True)
    extra = {key: value for key, value in (("style", style), ("input", input), ("output", output)) if value is not None}
    return tune_escape_latency(Application(
        layout=Layout(HSplit([window])),
        key_bindings=kb,
        full_screen=False,
        mouse_support=False,
        erase_when_done=True,
        **extra,
    ))


def pick_app(
    options: Iterable[str],
    *,
    prompt: str = "",
    about: str = "",
    header: str = "",
    initial: int = 0,
    styled: Sequence[Fragments] | None = None,
    style: Any = None,
    input: Any = None,
    output: Any = None,
) -> tuple[Any, dict[str, Any]] | None:
    """agent-cli's ``pick_option`` as an application to run: (app, result), where ``result["value"]`` is the chosen index once it has run (None on Esc). None when there are no options."""
    from prompt_toolkit.application import get_app
    from prompt_toolkit.formatted_text import ANSI, FormattedText
    from prompt_toolkit.key_binding import KeyBindings

    items = list(options)
    if not items:
        return None
    selected = [max(0, min(initial, len(items) - 1))]
    result: dict[str, Any] = {"value": None}
    header_lines = header.rstrip("\n").split("\n") if header else []
    about_lines = about.rstrip("\n").split("\n") if about else []
    scroll = [0]

    def _about_rows() -> list[str]:
        """The about text wrapped to the terminal, so no line is cut off."""
        if not about_lines:
            return []
        try:
            columns = get_app().output.get_size().columns
        except Exception:
            columns = 80
        rows: list[str] = []
        for line in about_lines:
            rows.extend(textwrap.wrap(line, max(20, columns - 1)) or [""])
        return rows

    def _view_height() -> int:
        """Rows the header may use, after reserving the options block."""
        try:
            rows = get_app().output.get_size().rows
        except Exception:
            rows = 24
        reserved = len(items) + 5 + (1 if prompt else 0) + len(_about_rows())
        return max(3, rows - reserved)

    def _max_scroll() -> int:
        return max(0, len(header_lines) - _view_height())

    def body() -> Any:
        if header_lines:
            view = _view_height()
            top = max(0, min(scroll[0], _max_scroll()))
            scroll[0] = top
            text = "\n".join(header_lines[top: top + view])
            above, below = top, max(0, len(header_lines) - top - view)
            if above or below:
                marks = []
                if above:
                    marks.append(f"↑ {above} more")
                if below:
                    marks.append(f"↓ {below} more")
                text += "\n  [" + " · ".join(marks) + " — PgUp/PgDn to scroll]"
            text += "\n\n"
            if prompt:
                text += prompt + "\n"
            for line in _about_rows():
                text += f"\x1b[90m{line}\x1b[0m\n"
            for i, label in enumerate(items):
                marker = "▸" if i == selected[0] else " "
                text += f" {marker} {_row_number(i, len(items))}  {label}\n"
            text += "\n[↑/↓ navigate · enter to confirm · 1-{n} to jump · esc back]".format(n=len(items))
            return ANSI(text)

        rows: list[tuple[str, str]] = []
        if prompt:
            rows.append((_ACCENT, prompt + "\n"))
        for line in _about_rows():
            rows.append((_DIM, line + "\n"))
        for i, label in enumerate(items):
            current = i == selected[0]
            rows.append((_ACCENT if current else "", f" {'▸' if current else ' '} "))
            rows.append((_DIM, f"{_row_number(i, len(items))}  "))
            if styled is not None and i < len(styled):
                rows.extend((piece_style, text) for piece_style, text in styled[i])
            else:
                rows.append(("", label))
            rows.append(("", "\n"))
        rows.append((_DIM, "\n[↑/↓ navigate · enter to confirm · 1-{n} to jump · esc back]".format(n=len(items))))
        return FormattedText(rows)

    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        selected[0] = (selected[0] - 1) % len(items)
        event.app.invalidate()

    @kb.add("down")
    def _down(event: Any) -> None:
        selected[0] = (selected[0] + 1) % len(items)
        event.app.invalidate()

    @kb.add("pageup")
    def _scroll_up(event: Any) -> None:
        scroll[0] = max(0, scroll[0] - _view_height())
        event.app.invalidate()

    @kb.add("pagedown")
    def _scroll_down(event: Any) -> None:
        scroll[0] = min(_max_scroll(), scroll[0] + _view_height())
        event.app.invalidate()

    @kb.add("enter")
    def _enter(event: Any) -> None:
        result["value"] = selected[0]
        event.app.exit()

    for i in range(min(len(items), 9)):  # digits 1..9
        digit = str(i + 1)

        @kb.add(digit, eager=True)
        def _pick(event: Any, _i: int = i) -> None:
            selected[0] = _i
            result["value"] = _i
            event.app.exit()

    _cancel_binding(kb, result)
    return _application(body, kb, style=style, input=input, output=output), result


def paged_app(
    rows: list[str],
    *,
    prompt: str = "",
    page_size: int = PAGE_THRESHOLD,
    initial: int = 0,
    styled: Sequence[Fragments] | None = None,
    style: Any = None,
    input: Any = None,
    output: Any = None,
) -> tuple[Any, dict[str, Any]] | None:
    """agent-cli's ``paged_pick`` (one "all" view) as an application to run: a viewport of ``page_size`` rows around the cursor, "… N more above/below" beyond it, PgUp/PgDn a page at a time, digits only while the list fits in 9 rows. ``prompt`` may span lines (a header); ``styled`` rows render in place of the plain ones."""
    from prompt_toolkit.formatted_text import ANSI, FormattedText, to_formatted_text
    from prompt_toolkit.key_binding import KeyBindings

    if not rows:
        return None
    cursor = [max(0, min(initial, len(rows) - 1))]
    result: dict[str, Any] = {"value": None}

    def body() -> Any:
        cursor[0] = max(0, min(cursor[0], len(rows) - 1))
        out: list[tuple[str, str]] = []
        if prompt:
            out.extend(to_formatted_text(ANSI(prompt + "\n")))
        first = max(0, min(cursor[0] - page_size // 2, len(rows) - page_size))
        window = list(range(len(rows)))[first: first + page_size]
        if first > 0:
            out.append((_DIM, f"   … {first} more above\n"))
        for index in window:
            current = index == cursor[0]
            out.append(("bold #87d7ff" if current else "", f" {'▸' if current else ' '} "))
            if styled is not None and index < len(styled):
                out.extend((piece_style, text) for piece_style, text in styled[index])
            else:
                out.extend(to_formatted_text(ANSI(rows[index])))
            out.append(("", "\n"))
        below = len(rows) - first - len(window)
        if below > 0:
            out.append((_DIM, f"   … {below} more below\n"))
        bits = [f"{cursor[0] + 1}/{len(rows)}", "↑/↓ move · pgup/pgdn page · enter select · esc back"]
        out.append((_DIM, "\n[" + " · ".join(bits) + "]"))
        return FormattedText(out)

    kb = KeyBindings()

    @kb.add("up")
    def _up(event: Any) -> None:
        cursor[0] = (cursor[0] - 1) % len(rows)
        event.app.invalidate()

    @kb.add("down")
    def _down(event: Any) -> None:
        cursor[0] = (cursor[0] + 1) % len(rows)
        event.app.invalidate()

    @kb.add("pageup")
    def _pageup(event: Any) -> None:
        cursor[0] = max(0, cursor[0] - page_size)
        event.app.invalidate()

    @kb.add("pagedown")
    def _pagedown(event: Any) -> None:
        cursor[0] = min(len(rows) - 1, cursor[0] + page_size)
        event.app.invalidate()

    @kb.add("enter")
    def _select(event: Any) -> None:
        result["value"] = cursor[0]
        event.app.exit()

    for _i in range(9):
        digit = str(_i + 1)

        @kb.add(digit, eager=True)
        def _jump(event: Any, _idx: int = _i) -> None:
            # Digits only act when unambiguous — the whole list is on screen.
            if len(rows) <= 9 and _idx < len(rows):
                result["value"] = _idx
                event.app.exit()

    _cancel_binding(kb, result)
    return _application(body, kb, style=style, input=input, output=output), result


@dataclass
class Question:
    """A picker shaped like a questionary question: ``application`` to add key bindings to, ``unsafe_ask`` to run it."""

    application: Any
    run: Callable[[], Any]

    def unsafe_ask(self) -> Any:
        return self.run()

    def ask(self) -> Any:  # questionary's name; git-tools asks with unsafe_ask (navigation.ask_with_back)
        return self.run()


class _Nothing:
    """No options: answers Esc at once, as an empty agent-cli picker does."""

    application = type("_NoApplication", (), {"key_bindings": None})()

    def unsafe_ask(self) -> None:
        return None


def _title_fragments(title: Any) -> list[tuple[str, str]]:
    if isinstance(title, str):
        return [("", title)]
    return [(piece[0], piece[1]) for piece in title]


def plain(text: Any) -> str:
    """A row's text without its styling."""
    if isinstance(text, str):
        return _ANSI.sub("", text)
    return "".join(piece[1] for piece in text)


def _choice_parts(choice: Any) -> tuple[Any, Any]:
    """(title, value) of a questionary Choice, or of a plain string."""
    if isinstance(choice, str):
        return choice, choice
    return choice.title, choice.value


def select(
    message: str,
    choices: Sequence[Any],
    *,
    default: Any = None,
    about: str = "",
    style: Any = None,
    input: Any = None,
    output: Any = None,
    **_questionary_options: Any,
) -> Question | _Nothing:
    """A list of questionary ``Choice`` rows asked in agent-cli's picker; answers the chosen row's value (None on Esc).

    The ``message`` is the picker's title, ``about`` the grey line under it. A ``← Back`` row is dropped (Esc goes back). Rows keep their styling; ``default`` (a row's value, or the ``Choice`` itself, as questionary takes it) puts the cursor on its row. questionary-only options (qmark, pointer, instruction, search) are ignored.
    """
    rows = [(title, value) for title, value in map(_choice_parts, choices) if value != BACK]
    values = [value for _title, value in rows]
    if default is not None and not isinstance(default, str) and hasattr(default, "value"):
        default = default.value  # questionary also takes the Choice itself as the default
    initial = values.index(default) if default is not None and default in values else 0
    titles = [_title_fragments(title) for title, _value in rows]
    prompt = message.rstrip().removesuffix(":")
    if len(rows) > PAGE_THRESHOLD:
        header = prompt + (f"\n\x1b[90m{about}\x1b[0m" if about else "")
        built = paged_app([plain(title) for title, _value in rows], prompt=header, initial=initial, styled=titles, style=style, input=input, output=output)
    else:
        built = pick_app([plain(title) for title, _value in rows], prompt=prompt, about=about, initial=initial, styled=titles, style=style, input=input, output=output)
    if built is None:
        return _Nothing()
    app, result = built

    def run() -> Any:
        app.run()
        index = result["value"]
        return None if index is None else values[index]

    return Question(app, run)


def pick(
    labels: Sequence[str],
    *,
    header: str = "",
    initial: int = 0,
    input: Any = None,
    output: Any = None,
) -> Question | _Nothing:
    """agent-cli's window picker: ANSI ``labels`` under an ANSI ``header`` (its title and grey about lines), as agent-cli's ``_pick`` asks them; answers the chosen index (None on Esc). Long lists page with the header as their prompt."""
    labels = list(labels)
    if len(labels) > PAGE_THRESHOLD:
        built = paged_app(labels, prompt=header, initial=initial, input=input, output=output)
    else:
        built = pick_app(labels, header=header, initial=initial, input=input, output=output)
    if built is None:
        return _Nothing()
    app, result = built

    def run() -> Any:
        app.run()
        return result["value"]

    return Question(app, run)


def _line(message: str, *, default: str = "", password: bool = False, input: Any = None, output: Any = None) -> Question:
    """agent-cli's ``prompt_line``: one in-place input line that erases itself; Esc answers None, distinct from a blank Enter."""
    from prompt_toolkit.history import DummyHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import PromptSession

    kb = KeyBindings()

    @kb.add("escape", eager=True)
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    extra = {key: value for key, value in (("input", input), ("output", output)) if value is not None}
    session = PromptSession(history=DummyHistory(), key_bindings=kb, erase_when_done=True, **extra)
    tune_escape_latency(session.app)
    text = message if message.endswith((" ", "> ")) else f"{message} "

    def run() -> Optional[str]:
        return session.prompt(text, default=default or "", is_password=password)

    return Question(session.app, run)


def text(message: str, *, default: str = "", input: Any = None, output: Any = None, **_questionary_options: Any) -> Question:
    """A typed line, questionary ``text``-shaped."""
    return _line(message, default=default, input=input, output=output)


def password(message: str, *, input: Any = None, output: Any = None, **_questionary_options: Any) -> Question:
    """A masked line, questionary ``password``-shaped."""
    return _line(message, password=True, input=input, output=output)


__all__ = ["PAGE_THRESHOLD", "Question", "paged_app", "pick", "pick_app", "password", "plain", "select", "text", "tune_escape_latency"]

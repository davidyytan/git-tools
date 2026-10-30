"""Back navigation shared by menus and generator prompts.

The signal and module import are stdlib-only. UI dependencies are imported only
when asking a question, so the CI bump engine still works without UI extras.
"""

from typing import Any


BACK = "__git_tools_back__"


class NavigationBack(BaseException):
    """Leave the current operation, never an error or implicit consent.

    Like KeyboardInterrupt, this bypasses broad ``except Exception`` recovery
    that might otherwise continue into generation, persistence, or clipboard
    handoff. Unlike KeyboardInterrupt, the root menu catches it and reopens.
    """


def ask_with_back(question: Any) -> Any:
    """Ask with Esc returning None and Ctrl+C raising KeyboardInterrupt.

    Settings intentionally use the None result to move back exactly one level.
    Generator callers pass it through ``require_answer`` to cancel the command.
    """
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

    bindings = KeyBindings()

    @bindings.add("escape", eager=True)
    def _back(event: Any) -> None:
        event.app.exit(result=None)

    application = question.application
    existing = application.key_bindings
    application.key_bindings = (
        merge_key_bindings([existing, bindings]) if existing else bindings
    )
    # Questionary.ask() catches Ctrl+C; unsafe_ask preserves its exit semantics.
    return question.unsafe_ask()


def require_answer(answer: Any) -> Any:
    """Reject Back/Esc instead of interpreting it as a choice or default."""
    if answer is None or answer == BACK:
        raise NavigationBack
    return answer

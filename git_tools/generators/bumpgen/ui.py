"""Interactive UI imports with a stdlib fallback.

CI workflows import the bump engine from a bare checkout where Rich,
Questionary, and tiktoken are absent. The engine and strategy code never
prompt, so those imports are optional; only interactive ``BumpGenerator``
use requires them.
"""

from __future__ import annotations

import logging

_OPTIONAL_BASE_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from ..base import BaseGenerator, info, print_panel
except ModuleNotFoundError as exc:
    if exc.name not in {"questionary", "rich", "tiktoken"}:
        raise

    _OPTIONAL_BASE_IMPORT_ERROR = exc

    def info(message: str) -> None:
        print(f"• {message}")

    def print_panel(content: str, title: str = "", border_style: str = "") -> None:
        if title:
            print(f"{title}\n{content.strip()}")
        else:
            print(content.strip())

    class BaseGenerator:
        """Fallback base class for stdlib-only bump and strategy flows."""

        def __init__(self, *_: object, interactive: bool = False, **__: object) -> None:
            self.logger = logging.getLogger(self.__class__.__name__)
            self._interactive = interactive

        def _raise_optional_dependency_error(self) -> None:
            missing = (
                _OPTIONAL_BASE_IMPORT_ERROR.name
                if _OPTIONAL_BASE_IMPORT_ERROR and _OPTIONAL_BASE_IMPORT_ERROR.name
                else "questionary"
            )
            raise ModuleNotFoundError(
                f"Optional dependency '{missing}' is required for interactive bump generation."
            ) from _OPTIONAL_BASE_IMPORT_ERROR

        def prompt_select(self, *_: object, **__: object) -> str:
            self._raise_optional_dependency_error()

        def prompt_confirm(self, *_: object, **__: object) -> bool:
            self._raise_optional_dependency_error()


__all__ = ["BaseGenerator", "info", "print_panel"]

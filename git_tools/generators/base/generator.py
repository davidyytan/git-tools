"""``BaseGenerator``: the shared foundation for every git-tools generator."""

import logging
import re
from typing import Optional

from .clients import ChatClientMixin
from .diffs import DiffProcessingMixin
from .display import DisplayMixin
from .interaction import InteractionMixin
from .llm import LLMInvocationMixin
from .models import ModelSelectionMixin
from .prompts import PromptTemplateMixin


class BaseGenerator(
    PromptTemplateMixin,
    InteractionMixin,
    ModelSelectionMixin,
    ChatClientMixin,
    DiffProcessingMixin,
    DisplayMixin,
    LLMInvocationMixin,
):
    """Base class for all LLM-powered generators."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        token_limit: Optional[int] = None,
        interactive: bool = False,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._provider_configs = {}  # Cache for loaded provider configs
        self.chatclient = None

        # Interactive mode controls workflow choices and external-generation consent.
        self._interactive = interactive

        # Model/sampling overrides: None uses saved settings in either mode.
        # The input diff budget can still be prompted for in interactive mode.
        self._cli_model = model
        self._cli_temperature = temperature
        self._cli_max_tokens = max_tokens
        self._cli_token_limit = token_limit

    @staticmethod
    def extract_code_block(
        content: str, pattern: str = r"```[\w]*(?:\n|\s)(.*?)```"
    ) -> Optional[str]:
        """Extract content from code blocks.

        Handles both formats:
        ```
        code here
        ```

        and:
        ```python
        code here
        ```
        """
        content = content.rstrip()
        match = re.search(pattern, content, re.DOTALL)
        return match.group(1).strip() if match else None

"""LLM invocation with retry handling."""

import time
from typing import Any, Dict, List, Optional

from git_tools.settings.settings import settings

from .terminal import console, warning


class LLMInvocationMixin:
    """Call the configured chat client and normalize its response."""

    def invoke_llm(
        self,
        messages: List[Dict[str, str]],
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Unified method to invoke LLM and format response with retry logic.

        Args:
            messages: List of message dicts with 'role' and 'content' keys
            max_retries: Maximum number of retries after the initial attempt (default: global settings.default_max_retries)
            retry_delay: Delay between retries in seconds (default: global settings.default_retry_delay)

        Returns:
            Formatted response dict with 'content', 'response_metadata', 'additional_kwargs'
        """
        # Use global application retry defaults when arguments are omitted.
        if max_retries is None:
            max_retries = settings.default_max_retries

        if retry_delay is None:
            retry_delay = settings.default_retry_delay

        last_error = None
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                if attempt > 0:
                    warning(f"Retrying LLM request (attempt {attempt + 1}/{max_retries + 1})...")

                with console.status("Generating response from LLM...", spinner="dots"):
                    response = self.chatclient.invoke(messages)

                output = {"content": response.content}

                if response.response_metadata:
                    output["response_metadata"] = response.response_metadata

                if response.additional_kwargs:
                    output["additional_kwargs"] = response.additional_kwargs

                return output

            except Exception as e:
                last_error = e
                self.logger.warning(
                    f"LLM invocation attempt {attempt + 1} failed: {type(e).__name__}"
                )

                # Skip further retries for these authentication-related text markers, not for invalid requests in general.
                error_str = str(e).lower()
                if any(
                    term in error_str
                    for term in [
                        "unauthorized",
                        "invalid_api_key",
                        "authentication",
                        "forbidden",
                    ]
                ):
                    self.logger.error(f"Non-retryable error: {type(e).__name__}")
                    break

                # Wait before retrying (except on last attempt)
                if attempt < max_retries:
                    self.logger.info(f"Waiting {retry_delay}s before retry...")
                    time.sleep(retry_delay)

        self.logger.error(
            f"LLM invocation failed after {max_retries + 1} attempts: {last_error}"
        )
        return None

"""Token counting with tiktoken, guarding against special-token injection."""

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=1)
def _get_encoder() -> tiktoken.Encoding:
    """Load the tokenizer only when counting or truncating text, never for CLI help."""
    return tiktoken.get_encoding("cl100k_base")


def _escape_special_tokens(text: str) -> str:
    """Escape tiktoken special tokens to prevent them from being encoded as single tokens.

    Args:
        text: The text that may contain special tokens

    Returns:
        Text with special tokens escaped (e.g., <|endoftext|> -> <\\|endoftext\\|>)
    """
    for token in _get_encoder().special_tokens_set:
        if token in text:
            escaped = token.replace("|", "\\|")
            text = text.replace(token, escaped)
    return text


def count_tokens(text: str) -> int:
    """Count tokens in a string using cl100k_base encoding.

    Args:
        text: The text to count tokens for

    Returns:
        Number of tokens in the text
    """
    return len(_get_encoder().encode(_escape_special_tokens(text)))

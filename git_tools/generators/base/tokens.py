"""Token counting with tiktoken, guarding against special-token injection."""

import tiktoken

# Initialize tiktoken encoder once at module level
_ENCODER = tiktoken.get_encoding("cl100k_base")
_SPECIAL_TOKENS = _ENCODER.special_tokens_set


def _escape_special_tokens(text: str) -> str:
    """Escape tiktoken special tokens to prevent them from being encoded as single tokens.

    Args:
        text: The text that may contain special tokens

    Returns:
        Text with special tokens escaped (e.g., <|endoftext|> -> <\\|endoftext\\|>)
    """
    for token in _SPECIAL_TOKENS:
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
    return len(_ENCODER.encode(_escape_special_tokens(text)))

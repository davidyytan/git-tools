"""CLIProxyAPI: a local OpenAI-compatible proxy in front of other accounts.

Nothing provider-specific to parse: the picker lists whatever its ``/models``
returns through the shared catalog fetch. The preset base URL is the loopback
address a shell on the host reaches; agent-core's own default is the Docker
host alias, and the container launcher rewrites one into the other.
"""

from __future__ import annotations

PROVIDER_ID = "cliproxyapi"
BASE_URL = "http://127.0.0.1:8317/v1"
DEFAULT_MODEL = "gpt-6-astra"
PROFILE = "default"
ALIASES = ("proxy",)

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

__all__ = ["ALIASES", "BASE_URL", "DEFAULT_MODEL", "PRESET", "PROFILE", "PROVIDER_ID"]

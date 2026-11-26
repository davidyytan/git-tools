"""CLIProxyAPI: a local OpenAI-compatible proxy in front of other accounts.

Nothing provider-specific to parse: the picker lists whatever its ``/models`` returns through the shared catalog fetch. The preset base URL is the loopback address a shell on the host reaches; agent-core's own default is the Docker host alias, and the container launcher rewrites one into the other.

agent-proxy keeps the proxy's accounts in groups (``personal``, ``work``, …) and the proxy serves each group's models as ``<group>/<model>``; a plain model name reaches only the accounts in no group. ``split_model_group`` is agent-core's reading of such an id. The account-group window itself is ``git_tools.proxy_accounts``.
"""

from __future__ import annotations

import re

PROVIDER_ID = "cliproxyapi"
BASE_URL = "http://127.0.0.1:8317/v1"
DEFAULT_MODEL = "gpt-6.2-sol"
PROFILE = "default"
ALIASES = ("proxy",)

#: The proxy's stock client key, as agent-proxy's env example and agent-core set it: what is sent when no key is given.
DEFAULT_API_KEY = "cliproxyapi_sEcr3Tk3Y"

# What /settings provider seeds a fresh profile with.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "base_url": BASE_URL,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

#: A CLIProxyAPI account group in front of a model id ("work/gpt-6.2-sol"). The proxy sends such a request only to the credentials tagged with that group and drops the group before calling upstream.
_MODEL_GROUP = re.compile(r"([A-Za-z0-9][A-Za-z0-9_-]*)/(.+)")


def split_model_group(model_id: str | None, provider: str | None) -> tuple[str | None, str]:
    """``(group, model)`` of a model id: the CLIProxyAPI account group in front of it, if any, and the model that group serves.

    Only a CLIProxyAPI id carries a group. Any other provider's id is returned whole with no group, since a slash there names a vendor (OpenRouter's ``openai/gpt-5``), not an account group.
    """
    text = (model_id or "").strip()
    if (provider or "").strip().lower() == PROVIDER_ID:
        match = _MODEL_GROUP.fullmatch(text)
        if match:
            return match.group(1), match.group(2)
    return None, text


def model_not_found_hint(model_id: str | None) -> str:
    """What a CLIProxyAPI ``model_not_found`` means, as agent-core adds it to the error: for a grouped id, no account in that group is logged in or none serves the model; for a plain id, the proxy keeps its accounts in groups and wants ``<group>/<model>``. Empty without a model id."""
    group, name = split_model_group(model_id, PROVIDER_ID)
    if not name:
        return ""
    if group is None:
        return (
            f"The proxy serves no {name} without an account group. A proxy that keeps its accounts in groups (agent-proxy's default) "
            f"is asked for `<group>/<model>`, for example `personal/{name}`: choose a model with its group."
        )
    return (
        f'The proxy has no {name} in the account group "{group}": no account in that group is logged in, or none of its accounts serves that model. '
        f"Log an account into the group with agent-proxy's `login.sh --group {group}` (if the group no longer exists, create it first with "
        f"`group.sh --create {group}`), or choose another group or model."
    )


__all__ = [
    "ALIASES",
    "BASE_URL",
    "DEFAULT_API_KEY",
    "DEFAULT_MODEL",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "model_not_found_hint",
    "split_model_group",
]

"""Alibaba Cloud Model Studio (DashScope) endpoint and model choices.

Model Studio has no single endpoint or catalog: the host that serves a key
depends on the plan, region and workspace, and the OpenAI-compatible ``/models``
listing varies with it. So the endpoint is typed (``BASE_URL`` is only what the
prompt starts from) and the model list is a curated constant with a
manual-entry escape hatch in the picker.
"""

from __future__ import annotations

from .catalog import CatalogFetchResult, ModelCatalogEntry

PROVIDER_ID = "qwen"
DEFAULT_MODEL = "qwen3.8-max"
PROFILE = "qwen"
ALIASES = ("dashscope", "alibaba")

# What /settings provider seeds a fresh profile with. No base_url on purpose:
# Model Studio's endpoint depends on the plan, region and workspace, so the
# flow asks for it rather than presetting one.
PRESET: dict[str, str] = {
    "type": PROVIDER_ID,
    "default_model": DEFAULT_MODEL,
    "profile": PROFILE,
}

# The one endpoint the picker offers besides whatever is already configured.
# Not a runtime default — agent-core refuses to guess an endpoint — and not a
# prompt prefill: the real URL differs per account, so typing one starts empty.
BASE_URL = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"

# Order is the picker's order; the default leads (the profile's current model
# is pinned above it when there is one).
MODELS: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(id=DEFAULT_MODEL, display_name="Qwen3.8-Max"),
    ModelCatalogEntry(id="qwen3.8-max-preview", display_name="Qwen3.8-Max Preview"),
)


def catalog() -> CatalogFetchResult[ModelCatalogEntry]:
    """The curated Model Studio catalog, shaped like a live fetch result."""

    return CatalogFetchResult(entries=MODELS, source="live")


__all__ = [
    "ALIASES",
    "BASE_URL",
    "DEFAULT_MODEL",
    "MODELS",
    "PRESET",
    "PROFILE",
    "PROVIDER_ID",
    "catalog",
]

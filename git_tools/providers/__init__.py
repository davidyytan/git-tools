"""Provider integrations and shared provider infrastructure.

Originally lifted from agent-cli (``agent_cli/providers``), with compatible metadata and pure helpers aligned to agent-core. Catalog codecs and endpoint discovery remain in these standalone modules, wrapped by git-tools' registry. Each module names its ``PROVIDER_ID`` (with compatibility aliases where git-tools retains a saved key), ``PRESET`` (fresh profile defaults), ``ALIASES`` (accepted alternate names), and any provider-specific catalog logic beyond the shared OpenAI-compatible fetch in ``catalog``:

- ``cliproxyapi`` — local proxy; plain live ``/models``
- ``kimi_code``   — account-aware ``/models`` schema, thinking choices, cache
- ``openrouter``  — upstream endpoint pinning per model
- ``acrc``        — live ``/models`` only, no static replacement catalog
- ``qwen``        — typed endpoint, curated list (``qwencode`` compatibility)
- ``zcode``       — Z.ai GLM Coding Plan endpoint, curated list and effort tiers
- ``openai``      — heuristic-filtered live ``/models``, no static replacement catalog
- ``anthropic``   — native ``/models`` (its own headers), no static replacement catalog
- ``copilot``     — git-tools only; plain live ``/models`` behind a local proxy

git-tools wires these into its own registry in ``git_tools.settings.mappings`` (credential env vars, config classes, which pickers are live, per-model knobs) and into the chat clients in ``git_tools.generators.base.clients``. Live-discovery catalogs have no static fallback; single profile defaults, Qwen/Zcode curated choices, and Kimi's scoped cache are separate policies. The modules themselves stay independent of settings and client imports.
"""

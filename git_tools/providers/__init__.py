"""Provider integrations and shared provider infrastructure.

Copied from agent-cli (``agent_cli/providers``), byte for byte where a module
exists there, so the catalog codecs, endpoint discovery and presets are the
ones that repo has already proven. One module per provider, each naming its
``PROVIDER_ID`` (agent-core's canonical key), ``PRESET`` (what a fresh profile
is seeded with), ``ALIASES`` (what the user may type instead of the id) and any
catalog logic the provider needs beyond the shared OpenAI-compatible fetch in
``catalog``:

- ``cliproxyapi`` — local proxy; plain live ``/models``
- ``kimi_code``   — account-aware ``/models`` schema, thinking choices, cache
- ``openrouter``  — upstream endpoint pinning per model
- ``acrc``        — live ``/models`` with a built-in fallback list
- ``qwen``        — typed endpoint, curated list (no stable ``/models``)
- ``openai``      — live ``/models`` narrowed to chat models, built-in fallback
- ``anthropic``   — native ``/models`` (its own headers), built-in fallback
- ``copilot``     — git-tools only; plain live ``/models`` behind a local proxy

git-tools wires these into its own registry in ``git_tools.settings.mappings``
(credential env vars, config classes, which pickers are live, per-model knobs)
and into the chat clients in ``git_tools.generators.base.clients``; the
modules themselves stay free of git-tools imports so they can be re-copied.
"""

# Configuration

[Documentation index](README.md) · [CLI reference](usage.md#settings-name-value) · [Versioning](versioning.md)

## Configure a Provider

```bash
git-tools settings
```

Choose **Provider** for a continuous setup: provider → credentials/endpoint → main model → OpenRouter upstream (with available price, context, quantization, caching and uptime metadata, cheapest first) or Kimi thinking (off, on or a declared tier) → reasoning effort for the other supported providers. Most current choices are preselected, but the Kimi tier-only case has a [known default-selection defect](#current-limitations). A blank key keeps an existing/default key. Back retains pending choices and revisits the preceding step; canceling discards the whole unfinished setup. Choices are saved together only after completing the flow.

```bash
git-tools settings provider                     # Interactive provider selector and setup
git-tools settings provider openrouter          # Same wizard, starting with OpenRouter in a terminal
git-tools settings provider openrouter --interactive
git-tools settings provider openrouter --non-interactive  # Save provider/defaults without prompts
```

Named-provider commands automatically use the wizard in a terminal and retain non-interactive behavior without a terminal. Explicit flags override that choice. **API Key** and **Main Model** can also be edited separately afterward. Endpoints, default models and curated choices are defined by the upstream-derived modules in `git_tools/providers/` and git-tools' registry integration; they are defaults, not allowed-model whitelists. Use Esc or **← Back** to return a level; use **Done** to finish. Prefer the masked credential prompt over secret command arguments.

| Provider | Credential variable | Default endpoint | Default model |
| --- | --- | --- | --- |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | `deepseek/deepseek-v4-flash-0731` |
| `kimicode` (`kimicli`) | `KIMICODE_API_KEY` | `https://api.kimi.com/coding/v1` | `kimi-for-coding` |
| `cliproxyapi` | `CLIPROXYAPI_API_KEY` | `http://127.0.0.1:8317/v1` | `gpt-6-astra` |
| `acrc` | `ACRC_API_KEY` | `https://fmodel.ai.acrc.a-star.edu.sg/v1` | `deepseek-v4.1-flash` |
| `copilot` | `COPILOT_API_KEY` | `http://127.0.0.1:4141/v1` | `gpt-4.1` fallback; select a served model |
| `qwen` | `DASHSCOPE_API_KEY` | **Required explicit plan/region endpoint** | `qwen3.8-max` |
| `openai` | `OPENAI_API_KEY` | `https://api.openai.com/v1` | `gpt-6-astra` |
| `anthropic` (`claude`) | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` | `claude-opus-5-5` |

`kimi` and `kimicode` are aliases for the retained `kimicli` storage key; `router`, `proxy`, `claude`, and `dashscope`/`alibaba` are also accepted. The table records repository defaults, not current model availability or account access. All generation clients use OpenAI-compatible chat completions; Anthropic is also called through that compatibility interface, not its native Messages API. Confirm endpoint support and parameter acceptance with your service.

The implementation classifies nonempty OpenAI-platform model IDs as reasoning-capable except IDs beginning with `gpt-3`, `gpt-4`, `chatgpt-`, `o1-mini` or `o1-preview`, or containing `-chat` (case-insensitive). For models classified as reasoning-capable, it omits temperature and sends a configured effort other than `none`. Unlisted OpenAI-platform IDs therefore receive a configured tier unless excluded; this is a client policy, not a guarantee that every server/model accepts it. CLIProxyAPI sends configured temperature and only an explicitly configured reasoning tier for IDs classified as OpenAI-family reasoning models by the repository's non-reasoning exclusions. ACRC and Copilot use the same OpenAI-family reasoning classification before forwarding a configured `reasoning_effort`; acceptance is endpoint/model-dependent. `none` omits the tier for OpenAI, CLIProxyAPI, Copilot, ACRC, Qwen and Kimi; OpenRouter forwards `none` as a tier. The Anthropic client omits temperature, sends `thinking.type=disabled` for `none`, and otherwise forwards a configured effort. Whether the service applies those fields is outside local validation. See the Kimi catalog precedence below.

ACRC VPN access and Copilot proxy authentication are managed externally. Host-local proxies default to loopback addresses. CLIProxyAPI requires a separately running/authenticated proxy; its client key defaults to the placeholder `cliproxyapi`, overridden when your proxy requires another key. Its reasoning effort is unset by default.

Saved provider choices are mirrored into per-provider profiles: model, effort, Kimi thinking, OpenRouter pin and custom endpoint (`GIT_TOOLS_OPENAI_MODEL_MAIN`, `GIT_TOOLS_KIMICLI_KIMI_THINKING`, `OPENAI_BASE_URL`, …). This also applies when OpenRouter is selected implicitly by default; API keys are already per provider. Switching reads the target profile into shared settings. This is not a lossless restoration guarantee: resetting to a provider default removes its user-file endpoint key, which can expose a lower-priority custom endpoint on a later switch. Verify destinations after switching; see [current limitations](#current-limitations).

To configure through environment variables instead:

```bash
export GIT_TOOLS_PROVIDER="kimicli"
export KIMICODE_API_KEY="your-key"
```

Or copy [the commented example](../git-tools.env.example) from your git-tools checkout into the repository where you will run commands (replace the example checkout path):

```bash
cp /path/to/git-tools/git-tools.env.example ./git-tools.env
```

Do not commit real credentials. Ordinary AI commit/issue/PR generation needs a provider; bump, init, and versioning CI do not require an LLM API key.

## Files and Precedence

| Location | Purpose |
| --- | --- |
| `~/.git-tools/settings.env` | Saved user-level settings and credentials |
| `~/.git-tools/model-catalog.json` | Kimi Code's last-known-good catalog, in agent-cli's format, scoped to endpoint and credential fingerprint |
| `./git-tools.env` | Optional settings in the command's current working directory |

For normal settings loading, exported environment variables override env files; `settings.env` overrides matching values in `git-tools.env`. CLI options override their corresponding generation defaults. A stale exported variable can therefore hide a newly saved setting.

The application settings readers and credential prechecks use that order, resolving aliases within each source. An exported provider-specific endpoint therefore overrides a saved shared endpoint. Empty exported variables and empty saved credentials are treated as unset. In env files, an explicitly assigned blank for endpoint, model, effort, routing, or thinking controls (including provider profiles) masks lower-priority file values; a bare variable name without `=` remains unset. A saved blank Qwen endpoint fails required configuration validation. **For other compatible providers a blank can instead become `None` and trigger an unrelated transport default; do not use blank endpoint controls.** See [current limitations](#current-limitations). The endpoint and credential rows show their application-resolved source without exposing keys; this display does not establish the actual transport destination when the endpoint is absent. After saving, an environment override remains authoritative. Endpoint lookup itself does not require valid credentials.

When `settings.env` is absent, legacy `~/.git-tools/config.env` or `$XDG_CONFIG_HOME/git-tools/config.env` (default `~/.config/git-tools/config.env`) is migrated automatically. The `.git-tools` legacy location takes priority. A failed move remains readable as a fallback; legacy files are ignored once `settings.env` exists.

For a full reset, back up credentials, then remove the saved settings/catalog and any legacy files you no longer want. Unset exported overrides and reconcile any local `git-tools.env` values too. Otherwise a remaining legacy file may migrate again.

## Models and Reasoning

Model catalogs are resolved through the provider modules copied from agent-cli and git-tools' registry integration. ACRC, OpenAI, and Anthropic show the endpoint's own list with the default first and the modules' display names overlaid, and fall back to the module's built-in list when the call cannot be made (OpenAI's list is narrowed to its chat models; Anthropic's comes from its native Models API with its own headers). OpenRouter and CLIProxyAPI show exactly what the endpoint serves, with no built-in list. Copilot also uses the endpoint's list, but falls back to its built-in `gpt-4.1` choice when discovery fails or returns no entries. Kimi Code keeps a last-known-good copy per endpoint and credential and shows it, clearly warned, when a refresh fails. Qwen is curated. The saved main model is pinned first even when the endpoint does not list it, and any ID can be typed manually; there is no separate saved list of additional manually entered IDs. Large catalogs are searchable. Kimi thinking/effort capabilities come from its catalog entries.

ACRC lists what its endpoint currently serves, with its default first when present and built-in display names overlaid. Its three built-in models are the fallback when the VPN or endpoint is unreachable, with the failure reported. Qwen uses curated choices plus manual entry rather than probing `/models`, because its catalog varies by plan and region; it must be given the actual endpoint, and no runtime endpoint is guessed. Select **Model → Enter a model ID manually…** to save an exact ID under that provider. Interactive generation reuses the configured provider and main model after you accept external generation; it does not reopen the model picker or ask for temperature and output-token limits. Use `git-tools settings` to change saved choices, or `--model`, `--temp`, and `--max-tokens` for invocation-only overrides. Saved/manual IDs remain valid choices even when absent from the catalog. Generation still reports catalog failures and stale/fallback status. Canceling the external-generation confirmation stops the operation; it does not accept the default or enter the prompt-copy path.

```bash
git-tools settings model deepseek/deepseek-v4-flash-0731
git-tools settings temperature 0.6
git-tools settings effort xhigh
```

### Main Model

```bash
git-tools settings main-model vendor/model
```

The main model handles all commit/issue/PR generation. `model` remains an alias for editing main. Resolution in both direct and interactive generation is explicit `--model` → effective main-model setting → provider fallback. `GIT_TOOLS_MODEL_MAIN` and legacy `GIT_TOOLS_DEFAULT_MODEL` are aliases: source precedence wins first, with `MODEL_MAIN` preferred within the same source. Temperature and maximum output tokens likewise use explicit CLI overrides before their saved global defaults. Provider-specific endpoint, routing, reasoning, and thinking settings are reused without additional configuration questions.

**Compatibility:** `support-model` and `sub-model` (including `support_model` and `sub_model`) are removed and treated as unknown settings, not deprecated no-ops. Obsolete `GIT_TOOLS_MODEL_SUPPORT`, `GIT_TOOLS_MODEL_SUB`, and `GIT_TOOLS_<PROVIDER>_MODEL_SUPPORT` keys are ignored. Existing entries are not automatically removed and cannot affect the main model.

Catalogs depend on endpoint and credentials. A failed Kimi Code refresh may use a clearly warned last-known-good cache for that exact identity; changed credentials/endpoints do not reuse another account's cache. Without a suitable cache, saved/manual and fallback choices remain. Other HTTP client errors bypass the disk cache; authentication/payment/permission errors (401/402/403), server errors, network failures, and malformed responses may use a matching last-known-good catalog, with a warning. Listing or saving an ID does not guarantee your account can access it.

Provider modules live in `git_tools/providers/` (copied from agent-cli) and are wired into the registry in `git_tools/settings/mappings.py`; there is no `mappings.json` to maintain.

### Endpoint, Routing, and Thinking

```bash
git-tools settings api-base https://your-endpoint.example/v1
git-tools settings openrouter-provider any  # Unpinned routing
# Interactive upstream discovery for the selected main model:
git-tools settings openrouter-provider
git-tools settings kimi-thinking enabled   # or disabled, or a tier such as high
```

OpenRouter upstream choices come from `/models/<model>/endpoints`; manual slugs are also accepted. A pin uses `provider.only` and disables fallbacks. Upstream availability is per model, so changing the main model interactively re-asks the pin for the new model; the non-interactive `settings main-model <id>` keeps a pin the new model's upstream list still contains, clears one it verifiably does not (with a warning), and keeps an unverifiable one with a warning. On OpenRouter, `effort none` is a real wire value, not clearing the override; other providers handle it as described above. Use `effort unset` to clear the saved override. Kimi thinking/effort choices respect catalog capabilities where declared, and a direct `settings effort <value>` is checked against the same Kimi catalog tiers before it is saved. Kimi first honors the catalog's `only`/`no` thinking mode. Otherwise an explicit `kimi-thinking disabled` sends `thinking.type=disabled`, suppresses tier validation, and saving it clears the effort override; a real tier alone enables thinking when thinking is unset. With neither an explicit thinking choice nor a tier, catalog `only`/`no` still forces enabled/disabled respectively; other modes leave the service default in effect. Kimi treats effort `none` as no tier, not as a disable-thinking instruction. Qwen uses its provider-specific thinking parameters.

Provider switching loads remembered choices where present, otherwise provider defaults (no default endpoint for Qwen) and no routing/thinking/effort overrides. General effort prompts preselect saved choices. Kimi's combined thinking picker can instead change a saved tier-only choice when Enter accepts the default; endpoint reset/roundtrip behavior also has a known gap. Neither should be assumed lossless; see [current limitations](#current-limitations). Noninteractive provider switches do not probe model catalogs. Exported variables still win over saved settings; unset stale exports when switching providers.

## Generation Preferences

Settings define stable defaults; modes apply them without re-asking routine configuration. Configure input budgets separately from the maximum **output** budget:

```bash
git-tools settings commit-input-budget 200000
git-tools settings issue-pr-input-budget 200000
git-tools settings max-tokens 32000       # output-budget alias
git-tools settings commit-format          # Scope, body, style, and footer submenu
git-tools settings commit-scope false
git-tools settings commit-body true
git-tools settings commit-body-style prose # bullets (point form) or prose
git-tools settings commit-footer false
git-tools settings issue-pr-source b     # d: diffs, c: messages, b: both
```

**Settings → Commit format** groups scope, description/body, description style, and footer, following [Commitizen's separation of summary, body, and footer](https://commitizen-tools.github.io/commitizen/tutorials/writing_commits/). The short `<type>(scope): summary` header always remains required; “description (body)” means the optional multiline text below it, not that summary. Defaults preserve the prior format: scope off, body enabled with point-form (`bullets`) details, footer off. Choose `prose` for paragraphs without list markers, or turn the body off for a header plus any permitted footer. Style is remembered while the body is off. Completed submenu edits save immediately; Back/Esc leaves the current level, and canceling an individual choice does not save it.

These apply in direct and interactive generation. `--token-limit`, `--scope`/`--no-scope`, `--body`/`--no-body`, `--body-style bullets|prose`, `--footer`/`--no-footer`, and `--source` override them for one run without saving. Both provider and prepared local prompts use the chosen structure. The parser preserves body paragraphs, list continuation indentation, and footer separation rather than converting their style afterward. The prompts instruct the model to include footers only for supported breaking-change facts or supplied issue references, never to invent them; review the generated result. The fixed `chore: open release` subject ignores these format preferences. Budgets limit diff processing, not the entire request (templates, messages and context are additional input). Task modes, release versions, extra context, and write/send consent are not remembered as preferences.

## Environment Reference

Defaults below are application defaults; model/provider capabilities may constrain which request parameters are used. Blank exported variables and credentials are unset; designated assigned file blanks mask lower file values as described in [Files and Precedence](#files-and-precedence). Do not clear endpoints to blank while the destination-safety defect below remains.

| Variable | Default / purpose |
| --- | --- |
| `GIT_TOOLS_PROVIDER` | `openrouter`; selects provider |
| `GIT_TOOLS_API_BASE` | The current provider's endpoint |
| `<PROVIDER>_BASE_URL` (e.g. `OPENAI_BASE_URL`) | Per-provider endpoint/profile input; verify after switches and explicit resets |
| `GIT_TOOLS_<PROVIDER>_MODEL_MAIN`, `…_REASONING_EFFORT`, `…_KIMI_THINKING`, `…_OPENROUTER_PROVIDER` | The provider's remembered profile, written automatically and restored on a switch |
| `GIT_TOOLS_MODEL_MAIN` | Main-model alias; preferred over the legacy alias within the same source |
| `GIT_TOOLS_DEFAULT_MODEL` | Legacy alias for the main-model setting |
| `GIT_TOOLS_OPENROUTER_PROVIDER` | Upstream slug, or `any`/unset for unpinned routing |
| `GIT_TOOLS_KIMI_THINKING` | Optional true/false override |
| `GIT_TOOLS_REASONING_EFFORT` | Provider/model-dependent effort override |
| `GIT_TOOLS_DEFAULT_TEMPERATURE` | `0.6`, range 0–2 |
| `GIT_TOOLS_DEFAULT_MAX_TOKENS` | `32000`, positive output budget |
| `GIT_TOOLS_DEFAULT_MAX_RETRIES` | `1`, nonnegative |
| `GIT_TOOLS_DEFAULT_RETRY_DELAY` | `1.0` seconds, nonnegative |
| `GIT_TOOLS_DEFAULT_TOKEN_LIMIT` | `200000`, commit input budget |
| `GIT_TOOLS_DEFAULT_ISSUE_PR_TOKEN_LIMIT` | `200000`, issue/PR input budget |
| `GIT_TOOLS_COMMIT_INCLUDE_SCOPE` | `false`, include a Conventional Commit scope by default |
| `GIT_TOOLS_COMMIT_INCLUDE_BODY` | `true`, allow the optional multiline description/body below the required summary |
| `GIT_TOOLS_COMMIT_BODY_STYLE` | `bullets`; `bullets` (point form) or `prose` for the optional body |
| `GIT_TOOLS_COMMIT_INCLUDE_FOOTER` | `false`, include a commit footer by default |
| `GIT_TOOLS_ISSUE_PR_SOURCE` | `b`, default input source: diffs `d`, messages `c`, or both `b` |
| `GIT_TOOLS_LARGE_DIFF_THRESHOLD` | `5000` |
| `GIT_TOOLS_MIN_FILE_TOKEN_THRESHOLD` | `1000`; small files protected from dropping |
| `GIT_TOOLS_CONSOLE_WIDTH_OFFSET` | `-2`, terminal width adjustment |
| `GIT_TOOLS_AZURE_PR_LIMIT` | `auto` or `false`; default `auto` |
| `GIT_TOOLS_AZURE_PR_MAX_CHARS` | `4000`, range 1–4000 UTF-16 units |

## PR Length Preferences

```bash
git-tools settings pr-limit auto
git-tools settings pr-max-chars 3500
```

`auto` detects Azure from `origin` and applies the result without a routine question; GitHub/unknown origins default to no limit. `false` disables automatic limiting. There is no saved `true` mode: use `--pr-limit` to force it for a command. `--no-pr-limit` disables it for a command. Legacy `azure-pr-limit` / `azure-pr-max-chars` setting aliases are accepted.

Length handling is best-effort, not a hard cap: see [CLI usage](usage.md#pr-description-length-handling) for retries, UTF-16 counting, and oversized output behavior.

## Current limitations

These are confirmed implementation defects, not intended behavior or fixes supplied by this documentation:

- **Destination safety — do not use blank endpoints.** For example, a user-file `OPENROUTER_BASE_URL=""` masks a local `GIT_TOOLS_API_BASE`. The application resolves no endpoint, but the pinned OpenAI-compatible client can silently use `https://api.openai.com/v1/` (or its own environment fallback), with the non-OpenAI key and request content. This is not fail-closed. Keep the intended endpoint explicitly nonblank in the effective source and verify it after provider changes before sending content. This destination risk was reproduced by inspecting the client configuration offline, not by sending credentials or content.
- **Default endpoint reset is not durable across sources.** Resetting to the official/default URL can remove the remembered user-file endpoint key. A lower-priority provider-specific custom URL can then return on switch-away/back and become active. Do not assume a reset survives switching: inspect the effective endpoint and explicitly set the intended nonblank URL again when needed. Remove or reconcile stale local/env endpoint values deliberately rather than treating the profile as authoritative isolation.
- **Kimi tier-only picker default is not a no-op.** With thinking unset and valid effort `high`, generation can use enabled/high, while the combined picker selects the catalog's default `low` or off. Enter can persist that different choice. Explicitly choose the intended tier, or set it directly with `git-tools settings kimi-thinking high` when that tier is supported; recheck saved values afterward. Explicit off and catalog restrictions still apply.

Additional defensive gaps: malformed Kimi cache metadata can raise an exception instead of falling back, and catalog HTTP diagnostics can include server-supplied error text. Treat logs as potentially sensitive; a reflected credential in an upstream error could appear in that text. Review/redact logs before sharing. These are conditional robustness risks, not evidence that a real service reflected a key.

The workarounds above reduce exposure but do not repair the implementation. Do not treat passing unit tests, an endpoint menu row, or a successful model listing as proof that every subsequent destination/profile transition is safe.

## Repository Version Configuration

Provider settings are separate from version configuration. `.cz.toml` is the sole version/tag authority; Python, Node, and supported Cargo manifests/lockfiles are best-effort sync consumers. See [versioning](versioning.md) for fields, examples, monorepos, and failure behavior.

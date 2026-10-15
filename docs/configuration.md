# Configuration

[Documentation index](README.md) · [CLI reference](usage.md#settings-name-value) · [Versioning](versioning.md)

## Configure a Provider

```bash
git-tools settings
```

Choose **Provider** for a continuous setup: provider → credentials/endpoint → main model → support model → OpenRouter upstream or Kimi thinking → applicable reasoning effort. Support is still reserved/unused. A blank key keeps an existing/default key. The choices are saved together only after completing the flow; canceling does not partially update saved settings.

```bash
git-tools settings provider                     # Interactive provider selector and setup
git-tools settings provider openrouter          # Same wizard, starting with OpenRouter in a terminal
git-tools settings provider openrouter --interactive
git-tools settings provider openrouter --non-interactive  # Save provider/defaults without prompts
```

Named-provider commands automatically use the wizard in a terminal and retain non-interactive behavior without a terminal. Explicit flags override that choice. **API Key** and **Main Model** can also be edited separately afterward. The source uses provider presets too (`agent-cli`'s `_PROVIDER_PRESETS`, `agent-core`'s `PROVIDER_CONFIGS`); these describe services, not allowed-model whitelists. OpenRouter's existing git-tools default remains Claude for compatibility, unlike agent-cli's DeepSeek default.
Use Esc or **← Back** to return a level; use **Done** to finish.
Prefer the masked credential prompt over secret command arguments.

| Provider | Credential variable | Default endpoint | Default model |
| --- | --- | --- | --- |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4.6` |
| `kimicode` (`kimicli`) | `KIMICODE_API_KEY` | `https://api.kimi.com/coding/v1` | `kimi-for-coding` |
| `cliproxyapi` | `CLIPROXYAPI_API_KEY` | `http://localhost:8317/v1` | `gpt-6-astra` |
| `acrc` | `ACRC_API_KEY` | `https://fmodel.ai.acrc.a-star.edu.sg/v1` | `deepseek-v4.1-flash` |
| `copilot` | `COPILOT_API_KEY` | `http://localhost:4141/v1` | `gpt-4.1` fallback; select a served model |
| `qwen` | `DASHSCOPE_API_KEY` | **Required explicit plan/region endpoint** | `qwen3.8-max` |

`kimi` and `kimicode` are aliases for the retained `kimicli` storage key; `router`, `proxy`, and `dashscope`/`alibaba` are also accepted. ACRC VPN access and Copilot proxy authentication are managed externally. Host-local proxies default to localhost rather than agent-core's container host alias. CLIProxyAPI requires a separately
running/authenticated proxy; its client key defaults to the placeholder
`cliproxyapi`. Set a different key only if your proxy requires it. Its default
reasoning effort is `xhigh` for effort-capable models.

To configure through environment variables instead:

```bash
export GIT_TOOLS_PROVIDER="kimicli"
export KIMICODE_API_KEY="your-key"
```

Or copy [the commented example](../git-tools.env.example) into the current repository:

```bash
cp git-tools.env.example git-tools.env
```

Do not commit real credentials. Ordinary AI commit/issue/PR generation needs a
provider; bump, init, and versioning CI do not require an LLM API key.

## Files and Precedence

| Location | Purpose |
| --- | --- |
| `~/.git-tools/settings.env` | Saved user-level settings and credentials |
| `~/.git-tools/models.json` | Manually saved model IDs, grouped by provider |
| `~/.git-tools/model-catalog.json` | Last-known-good discovered models, scoped to endpoint and credential fingerprint |
| `./git-tools.env` | Optional settings in the command's current working directory |

For normal settings loading, exported environment variables override env files;
`settings.env` overrides matching values in `git-tools.env`. CLI options override
their corresponding generation defaults. A stale exported variable can therefore
hide a newly saved setting.

The credential-availability precheck scans env files in the opposite order (local
first), while provider configuration uses normal settings precedence. Avoid keeping
different values for the same credential in both files.

When `settings.env` is absent, legacy `~/.git-tools/config.env` or
`$XDG_CONFIG_HOME/git-tools/config.env` (default `~/.config/git-tools/config.env`)
is migrated automatically. The `.git-tools` legacy location takes priority.
A failed move remains readable as a fallback; legacy files are ignored once
`settings.env` exists.

For a full reset, remove saved settings/models and any legacy files you no longer
want, then unset exported overrides. Otherwise a remaining legacy file may migrate
again. Back up credentials before resetting.

## Models and Reasoning

OpenRouter, Kimi Code, CLIProxyAPI, Copilot, and ACRC attempt live OpenAI-compatible `/models` discovery using the selected endpoint and credentials. Served IDs drive the picker; old fallback IDs not served by a successful catalog are dropped, while explicit saved/manual IDs remain available. Large catalogs are searchable. Display labels and Kimi thinking/effort capabilities are retained when supplied.

ACRC lists what its endpoint currently serves; its three built-in models lead the picker and are the fallback when the VPN or endpoint is unreachable, with the failure reported. Qwen uses curated choices plus manual entry rather than probing `/models`, because its catalog varies by plan and region; it must be given the actual endpoint, and no runtime endpoint is guessed.
Select **Model → Enter a model ID manually…** to save an exact ID under that provider.
Interactive generation uses the same searchable picker, retains the configured main
model even when absent from the catalog, and permits manual IDs for that invocation
without changing saved defaults. Canceling the picker cancels generation rather
than silently selecting another model. Generation also reports catalog failures
and stale/fallback status.

```bash
git-tools settings model anthropic/claude-sonnet-4.6
git-tools settings temperature 0.6
git-tools settings effort xhigh
```

### Main and Support Models

```bash
git-tools settings main-model vendor/model
git-tools settings support-model follow-main
# Or reserve a separate support ID (not invoked):
git-tools settings sub-model vendor/smaller-model
```

Main and support share the selected provider/account, as in the agent projects. **Only main is used today** for commit/issue/PR generation; configuring support never causes a second request. Support defaults to `follow-main`. `model` remains an alias for editing main. Resolution is explicit `--model` → `GIT_TOOLS_MODEL_MAIN` → legacy `GIT_TOOLS_DEFAULT_MODEL` → provider fallback; interactive commands can choose a model for that invocation.

Catalogs depend on endpoint and credentials. Discovery failures may use a clearly warned last-known-good cache for that exact identity; changed credentials/endpoints do not reuse another account's cache. Without a suitable cache, saved/manual and fallback choices remain. An ordinary HTTP error does not use the disk cache. Listing or saving an ID does not guarantee your account
can access it.

Provider metadata and static catalogs live in `git_tools/settings/mappings.py`;
there is no `mappings.json` to maintain.

### Endpoint, Routing, and Thinking

```bash
git-tools settings api-base https://your-endpoint.example/v1
git-tools settings openrouter-provider any  # Unpinned routing
# Interactive upstream discovery for the selected main model:
git-tools settings openrouter-provider
git-tools settings kimi-thinking enabled
```

OpenRouter upstream choices come from `/models/<model>/endpoints`; manual slugs are also accepted. A pin uses `provider.only` and disables fallbacks. `effort none` is a real wire value, not clearing the override; use `effort unset` to clear. Kimi thinking/effort choices respect catalog capabilities where declared. Qwen uses its native thinking parameters.

Provider switching resets the saved endpoint to the selected provider's default (empty for Qwen), support to `follow-main`, and routing/thinking/effort overrides. Exported variables still win over saved settings; unset stale exports when switching providers. Re-selecting the same provider keeps its configured endpoint.

## Environment Reference

Defaults below are application defaults; model/provider capabilities may constrain
which request parameters are used. Empty settings values are generally treated as unset.

| Variable | Default / purpose |
| --- | --- |
| `GIT_TOOLS_PROVIDER` | `openrouter`; selects provider |
| `GIT_TOOLS_API_BASE` | Provider endpoint override |
| `GIT_TOOLS_MODEL_MAIN` | Main model; preferred over legacy model default |
| `GIT_TOOLS_MODEL_SUPPORT` | Reserved support model; `follow-main` by default (`GIT_TOOLS_MODEL_SUB` alias) |
| `GIT_TOOLS_DEFAULT_MODEL` | Legacy main-model fallback |
| `GIT_TOOLS_OPENROUTER_PROVIDER` | Upstream slug, or `any`/unset for unpinned routing |
| `GIT_TOOLS_KIMI_THINKING` | Optional true/false override |
| `GIT_TOOLS_REASONING_EFFORT` | Provider/model-dependent effort override |
| `GIT_TOOLS_DEFAULT_TEMPERATURE` | `0.6`, range 0–2 |
| `GIT_TOOLS_DEFAULT_MAX_TOKENS` | `32000`, positive output budget |
| `GIT_TOOLS_DEFAULT_MAX_RETRIES` | `1`, nonnegative |
| `GIT_TOOLS_DEFAULT_RETRY_DELAY` | `1.0` seconds, nonnegative |
| `GIT_TOOLS_DEFAULT_TOKEN_LIMIT` | `200000`, commit input budget |
| `GIT_TOOLS_DEFAULT_ISSUE_PR_TOKEN_LIMIT` | `200000`, issue/PR input budget |
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

`auto` detects Azure from `origin`; GitHub/unknown origins default to no limit.
`false` disables automatic limiting. There is no saved `true` mode: use `--pr-limit`
to force it for a command. `--no-pr-limit` disables it for a command. Legacy
`azure-pr-limit` / `azure-pr-max-chars` setting aliases are accepted.

Length handling is best-effort, not a hard cap: see [CLI usage](usage.md#pr-description-length-handling)
for retries, UTF-16 counting, and oversized output behavior.

## Repository Version Configuration

Provider settings are separate from version configuration. `.cz.toml` is the sole
version/tag authority; Python, Node, and supported Cargo manifests/lockfiles are best-effort sync
consumers. See [versioning](versioning.md) for fields, examples, monorepos, and failure behavior.

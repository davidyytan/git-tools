# Configuration

[Documentation index](README.md) · [CLI reference](usage.md#settings-name-value) · [Versioning](versioning.md)

## Configure a Provider

```bash
git-tools settings
```

Choose **Provider** for a continuous setup: provider → credentials/endpoint → main model → support model → OpenRouter upstream (each with price, context, quantization, caching and uptime, cheapest first) or Kimi thinking (off, on or a declared tier, in one list with the model's default preselected) → reasoning effort for the other providers. Support is still reserved/unused. A blank key keeps an existing/default key. The choices are saved together only after completing the flow; canceling does not partially update saved settings.

```bash
git-tools settings provider                     # Interactive provider selector and setup
git-tools settings provider openrouter          # Same wizard, starting with OpenRouter in a terminal
git-tools settings provider openrouter --interactive
git-tools settings provider openrouter --non-interactive  # Save provider/defaults without prompts
```

Named-provider commands automatically use the wizard in a terminal and retain non-interactive behavior without a terminal. Explicit flags override that choice. **API Key** and **Main Model** can also be edited separately afterward. Endpoints, default models and curated lists are agent-cli's provider modules, copied into `git_tools/providers/`; they describe services, not allowed-model whitelists. Use Esc or **← Back** to return a level; use **Done** to finish. Prefer the masked credential prompt over secret command arguments.

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

`kimi` and `kimicode` are aliases for the retained `kimicli` storage key; `router`, `proxy`, `claude`, and `dashscope`/`alibaba` are also accepted. OpenAI and Anthropic are both spoken as OpenAI-compatible chat completions (Anthropic's Messages API host also answers `/v1/chat/completions`). On OpenAI the reasoning effort is sent to every model except those known to reject it (gpt-3.5, gpt-4.x, gpt-4o, chatgpt-*, the `*-chat` variants, o1-mini and o1-preview); those never receive it and do not show the effort setting, and a newly released model gets the tier on day one without a code change. `none` sends nothing, so the model uses its server default; the same holds on CLIProxyAPI, Copilot, ACRC, Qwen and Kimi, where only a real tier is forwarded (OpenRouter sends `none` as its own tier and Anthropic turns thinking off). Reasoning families use the server's default temperature. Every other provider, CLIProxyAPI included (its Codex backend accepts it), receives the configured temperature, 0.6 by default; through CLIProxyAPI the tier is sent only when `GIT_TOOLS_REASONING_EFFORT` is set (no implicit default, as in agent-core). On Anthropic no temperature is ever sent (Claude 4.7 and later reject values below 1), thinking is adaptive by default, `none` turns it off, and the other tiers are forwarded but currently ignored by Anthropic's compatibility layer. ACRC VPN access and Copilot proxy authentication are managed externally. Host-local proxies default to the loopback address rather than agent-core's container host alias. Every provider keeps its own profile, as agent-cli does: its model, support model, effort, Kimi thinking, OpenRouter pin and custom endpoint are mirrored under provider-scoped keys (`GIT_TOOLS_OPENAI_MODEL_MAIN`, `GIT_TOOLS_KIMICLI_KIMI_THINKING`, `OPENAI_BASE_URL`, …) whenever they are saved, and switching back to that provider restores them into the plain keys, which always hold the current provider's values. The default endpoint is not remembered, and setting it again forgets a remembered custom one. API keys are per provider already. CLIProxyAPI requires a separately running/authenticated proxy; its client key defaults to the placeholder `cliproxyapi`. Set a different key only if your proxy requires it. Its default reasoning effort is unset; effort-capable models receive a tier only when configured.

To configure through environment variables instead:

```bash
export GIT_TOOLS_PROVIDER="kimicli"
export KIMICODE_API_KEY="your-key"
```

Or copy [the commented example](../git-tools.env.example) into the current repository:

```bash
cp git-tools.env.example git-tools.env
```

Do not commit real credentials. Ordinary AI commit/issue/PR generation needs a provider; bump, init, and versioning CI do not require an LLM API key.

## Files and Precedence

| Location | Purpose |
| --- | --- |
| `~/.git-tools/settings.env` | Saved user-level settings and credentials |
| `~/.git-tools/model-catalog.json` | Kimi Code's last-known-good catalog, in agent-cli's format, scoped to endpoint and credential fingerprint |
| `./git-tools.env` | Optional settings in the command's current working directory |

For normal settings loading, exported environment variables override env files; `settings.env` overrides matching values in `git-tools.env`. CLI options override their corresponding generation defaults. A stale exported variable can therefore hide a newly saved setting.

The credential-availability precheck scans env files in the opposite order (local first), while provider configuration uses normal settings precedence. Avoid keeping different values for the same credential in both files.

When `settings.env` is absent, legacy `~/.git-tools/config.env` or `$XDG_CONFIG_HOME/git-tools/config.env` (default `~/.config/git-tools/config.env`) is migrated automatically. The `.git-tools` legacy location takes priority. A failed move remains readable as a fallback; legacy files are ignored once `settings.env` exists.

For a full reset, remove saved settings/models and any legacy files you no longer want, then unset exported overrides. Otherwise a remaining legacy file may migrate again. Back up credentials before resetting.

## Models and Reasoning

Model catalogs are resolved exactly as agent-cli's provider flow resolves them, by the copied provider modules. ACRC, OpenAI, and Anthropic show the endpoint's own list with the default first and the modules' display names overlaid, and fall back to the module's built-in list when the call cannot be made (OpenAI's list is narrowed to its chat models; Anthropic's comes from its native Models API with its own headers). OpenRouter and CLIProxyAPI show exactly what the endpoint serves, with no built-in list. Copilot also uses the endpoint's list, but falls back to its built-in `gpt-4.1` choice when discovery fails or returns no entries. Kimi Code keeps a last-known-good copy per endpoint and credential and shows it, clearly warned, when a refresh fails. Qwen is curated. The saved main model is pinned first even when the endpoint does not list it, any id can be typed manually, and nothing beyond the saved main model is remembered. Large catalogs are searchable. Kimi thinking/effort capabilities come from its catalog entries.

ACRC lists what its endpoint currently serves, with its default first when present and built-in display names overlaid. Its three built-in models are the fallback when the VPN or endpoint is unreachable, with the failure reported. Qwen uses curated choices plus manual entry rather than probing `/models`, because its catalog varies by plan and region; it must be given the actual endpoint, and no runtime endpoint is guessed. Select **Model → Enter a model ID manually…** to save an exact ID under that provider. Interactive generation reuses the configured provider and main model after you accept external generation; it does not reopen the model picker or ask for temperature and output-token limits. Use `git-tools settings` to change saved choices, or `--model`, `--temp`, and `--max-tokens` for invocation-only overrides. Saved/manual IDs remain valid choices even when absent from the catalog. Generation still reports catalog failures and stale/fallback status. Canceling the external-generation confirmation stops the operation; it does not accept the default or enter the prompt-copy path.

```bash
git-tools settings model deepseek/deepseek-v4-flash-0731
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

Main and support share the selected provider/account, as in the agent projects. **Only main is used today** for commit/issue/PR generation; configuring support never causes a second request. Support defaults to `follow-main`. `model` remains an alias for editing main. Resolution in both direct and interactive generation is explicit `--model` → `GIT_TOOLS_MODEL_MAIN` → legacy `GIT_TOOLS_DEFAULT_MODEL` → provider fallback. Temperature and maximum output tokens likewise use explicit CLI overrides before their saved global defaults. Provider-specific endpoint, routing, reasoning, and thinking settings are reused without additional configuration questions.

Catalogs depend on endpoint and credentials. A failed Kimi Code refresh may use a clearly warned last-known-good cache for that exact identity; changed credentials/endpoints do not reuse another account's cache. Without a suitable cache, saved/manual and fallback choices remain. An ordinary HTTP error does not use the disk cache. Listing or saving an ID does not guarantee your account can access it.

Provider modules live in `git_tools/providers/` (copied from agent-cli) and are wired into the registry in `git_tools/settings/mappings.py`; there is no `mappings.json` to maintain.

### Endpoint, Routing, and Thinking

```bash
git-tools settings api-base https://your-endpoint.example/v1
git-tools settings openrouter-provider any  # Unpinned routing
# Interactive upstream discovery for the selected main model:
git-tools settings openrouter-provider
git-tools settings kimi-thinking enabled   # or disabled, or a tier such as high
```

OpenRouter upstream choices come from `/models/<model>/endpoints`; manual slugs are also accepted. A pin uses `provider.only` and disables fallbacks. Upstream availability is per model, so changing the main model interactively re-asks the pin for the new model; the non-interactive `settings main-model <id>` keeps a pin the new model's upstream list still contains, clears one it verifiably does not (with a warning), and keeps an unverifiable one with a warning. On OpenRouter, `effort none` is a real wire value, not clearing the override; other providers handle it as described above. Use `effort unset` to clear the saved override. Kimi thinking/effort choices respect catalog capabilities where declared, and a direct `settings effort <value>` is checked against the same Kimi catalog tiers before it is saved. An explicit `kimi-thinking disabled` wins over a saved tier, as in agent-core: nothing thinking-related is sent, the tier is not validated, and saving `disabled` clears the effort override. The catalog's own `only`/`no` mode wins over both. With neither a thinking choice nor a tier configured, nothing thinking-related is sent and Kimi applies the model's own default, as in agent-core; on Kimi `effort none` likewise sends nothing, since it has no `none` tier. Qwen uses its native thinking parameters.

Provider switching restores the selected provider's remembered custom endpoint and profile choices. Without remembered values, it uses the provider's default endpoint (empty for Qwen), support `follow-main`, and no routing/thinking/effort overrides. Interactive setup lets you review or change these choices before saving. **Current setup limitations:** the support-model and reasoning-effort prompts do not preselect remembered values, so explicitly select any overrides you want to keep. Re-selecting the same provider normally keeps its configured endpoint, but if its credentials are missing, a custom endpoint saved only in the settings file can be replaced by the provider default; verify the endpoint before configuring credentials. Exported variables still win over saved settings; unset stale exports when switching providers.

## Environment Reference

Defaults below are application defaults; model/provider capabilities may constrain which request parameters are used. Empty settings values are generally treated as unset.

| Variable | Default / purpose |
| --- | --- |
| `GIT_TOOLS_PROVIDER` | `openrouter`; selects provider |
| `GIT_TOOLS_API_BASE` | The current provider's endpoint |
| `<PROVIDER>_BASE_URL` (e.g. `OPENAI_BASE_URL`) | A custom endpoint remembered per provider, restored when you switch back |
| `GIT_TOOLS_<PROVIDER>_MODEL_MAIN`, `…_MODEL_SUPPORT`, `…_REASONING_EFFORT`, `…_KIMI_THINKING`, `…_OPENROUTER_PROVIDER` | The provider's remembered profile, written automatically and restored on a switch |
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

`auto` detects Azure from `origin`; GitHub/unknown origins default to no limit. `false` disables automatic limiting. There is no saved `true` mode: use `--pr-limit` to force it for a command. `--no-pr-limit` disables it for a command. Legacy `azure-pr-limit` / `azure-pr-max-chars` setting aliases are accepted.

Length handling is best-effort, not a hard cap: see [CLI usage](usage.md#pr-description-length-handling) for retries, UTF-16 counting, and oversized output behavior.

## Repository Version Configuration

Provider settings are separate from version configuration. `.cz.toml` is the sole version/tag authority; Python, Node, and supported Cargo manifests/lockfiles are best-effort sync consumers. See [versioning](versioning.md) for fields, examples, monorepos, and failure behavior.

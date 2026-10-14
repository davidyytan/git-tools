# Configuration

[Documentation index](README.md) · [CLI reference](usage.md#settings-name-value) · [Versioning](versioning.md)

## Configure a Provider

```bash
git-tools settings
```

Choose **Provider** to configure provider → API key → model. A blank key keeps an
existing/default key. **API Key** and **Model** can be edited separately afterward.
Use Esc or **← Back** to return a level; use **Done** to finish.
Prefer the masked credential prompt over secret command arguments.

| Provider | Credential variable | Default endpoint | Default model |
| --- | --- | --- | --- |
| `openrouter` | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4.6` |
| `kimicli` | `KIMICODE_API_KEY` | `https://api.kimi.com/coding/v1` | `kimi-k2.5` |
| `cliproxyapi` | `CLIPROXYAPI_API_KEY` | `http://localhost:8317/v1` | `gpt-5.6-sol` |

`kimi` and `kimicode` are aliases for `kimicli`. CLIProxyAPI requires a separately
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

Every provider's picker attempts live OpenAI-compatible `/models` discovery and
keeps static fallback choices plus saved/manual IDs. Large catalogs are searchable.
Select **Model → Enter a model ID manually…** to save an exact ID under that provider.

```bash
git-tools settings model anthropic/claude-sonnet-4.6
git-tools settings temperature 0.6
git-tools settings effort xhigh
```

A model can also be supplied with `--model` or `GIT_TOOLS_DEFAULT_MODEL`.
Catalogs depend on endpoint and credentials; a failed refresh may retain the last
successful catalog for the same configuration. Changed configuration falls back
to saved/static choices. Listing or saving an ID does not guarantee your account
can access it.

Provider metadata and static catalogs live in `git_tools/settings/mappings.py`;
there is no `mappings.json` to maintain.

## Environment Reference

Defaults below are application defaults; model/provider capabilities may constrain
which request parameters are used. Empty settings values are generally treated as unset.

| Variable | Default / purpose |
| --- | --- |
| `GIT_TOOLS_PROVIDER` | `openrouter`; selects provider |
| `GIT_TOOLS_API_BASE` | Provider endpoint override |
| `GIT_TOOLS_DEFAULT_MODEL` | Selected provider's default model |
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
version/tag authority; Python and Node manifests/lockfiles are best-effort sync
consumers. See [versioning](versioning.md) for fields, examples, monorepos, and failure behavior.

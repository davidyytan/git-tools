# git-tools

AI-powered CLI tool for conventional commit generation, issue/PR documentation, version bumping, and Commitizen-style init.

## Installation

```bash
uv tool install -e .
git-tools --install-completion
```

If the tool is already installed and you want to refresh the installed tool environment:

```bash
uv tool install -e . --reinstall
```

Because the tool is installed in editable mode, normal source changes are picked up without reinstalling. Use `--reinstall` when you want to refresh the tool environment itself, such as after dependency changes.

After install, the main entrypoints are:

```bash
# Configure provider, API key, and defaults
git-tools config

# Interactive menu
git-tools

# Direct commands
git-tools commit
git-tools issue
git-tools pr
git-tools bump
git-tools init
```

Configuration and local state live here:

- `~/.git-tools/config.env`
  Written by `git-tools config`. Stores user-level provider, API key, and default overrides. Delete `~/.git-tools/` to reset all user config from scratch.
- `~/.git-tools/models.json`
  Written by `git-tools config` when you add a custom OpenRouter model. Holds your saved OpenRouter model slugs so they reappear in the picker. Created at runtime; never committed.
- `./git-tools.env`
  Optional repo-local env override file for the current working directory.

## Configuration

Run the config command to configure the provider, API key, and model defaults:

```bash
git-tools config
```

This saves settings to `~/.git-tools/config.env`.

Alternatively, copy the example env file and choose a provider:

```bash
cp git-tools.env.example git-tools.env
```

Supported providers:

- `openrouter` with `OPENROUTER_API_KEY`
- `kimicli` with `KIMICODE_API_KEY`
- `cliproxyapi` — local [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) proxy for Codex/GPT-5; defaults to `gpt-5.5` at `xhigh` reasoning. `CLIPROXYAPI_API_KEY` is optional (defaults to the `cliproxyapi` placeholder the proxy ships with); set it only if your proxy uses a different key.

The active provider is selected with `GIT_TOOLS_PROVIDER`.

You can also export the variables directly, for example:

```bash
export GIT_TOOLS_PROVIDER="kimicli"
export KIMICODE_API_KEY="your-kimi-api-key"
```

For a local CLIProxyAPI proxy (Codex/GPT-5), just point at the proxy — the client key defaults to `cliproxyapi`, so you only need to select the provider. The default model is `gpt-5.5` at `xhigh` reasoning; override the effort with `GIT_TOOLS_REASONING_EFFORT` for effort-capable models if desired:

```bash
export GIT_TOOLS_PROVIDER="cliproxyapi"
export GIT_TOOLS_API_BASE="http://localhost:8317/v1"   # default
# export CLIPROXYAPI_API_KEY="my-key"   # only if your proxy uses a non-default key
```

Provider metadata and the curated model lists for `kimicli` and `cliproxyapi` are defined in code (`git_tools/config/mappings.py`); there is no `mappings.json` to copy or maintain.

OpenRouter is open-ended: run `git-tools config`, choose **Model → Enter a new model…**, and type any slug (for example `z-ai/glm-5.2`). Custom slugs are saved to `~/.git-tools/models.json` so they show up in the picker next time. When nothing is configured, OpenRouter defaults to `anthropic/claude-sonnet-4.6`. You can also set a model directly with `--model <slug>` or `GIT_TOOLS_DEFAULT_MODEL`.

`git-tools config` writes provider, model, and default overrides to `~/.git-tools/config.env` (and OpenRouter model slugs to `~/.git-tools/models.json`).

For release workflow and branch policy details, see [GitHub Setup](docs/github-setup.md), [Git Flow Guide](docs/git-flow-guide.md), [Classic Flow](docs/git-flow-classic.md), [Classic — Reviewed](docs/git-flow-classic-reviewed.md), [Variant — Release-led](docs/git-flow-variant-release-led.md), and [Variant — Reviewed](docs/git-flow-variant-reviewed.md).

This repo uses `.cz.toml` as the authoritative Commitizen config and version source. `cz.toml` is not supported. `pyproject.toml` and `uv.lock` are auxiliary sync targets during bumps when they already expose matching version fields, but they are never treated as the source of truth.

## Usage

### Generate commit message

```bash
# Stage changes first, then run the direct command
git add .

# Direct command mode
git-tools commit

# With options
git-tools commit --model anthropic/claude-sonnet-4 --no-scope --no-footer --commit

# Fixed workflow subject
git-tools commit --workflow-kind open-release
```

`git-tools commit --workflow-kind ...` bypasses the LLM and writes the exact workflow subject directly. Use normal `git-tools commit` for ordinary Conventional Commits on feature, release, and hotfix branch work.

### Configure provider and defaults

```bash
git-tools config
```

`git-tools config` is interactive. Use it to choose the provider, save the matching API key, and set default model and request settings.

### Generate issue documentation

```bash
# Direct command mode
git-tools issue

# With options
git-tools issue --base develop --source b
```

### Generate pull request documentation

```bash
# Direct command mode
git-tools pr

# With options
git-tools pr --base develop --source b
git-tools pr --start-pr --workflow-version 1.7.0
git-tools pr --release-pr
git-tools pr --hotfix-pr
git-tools pr --backmerge-release-pr
git-tools pr --backmerge-hotfix-pr --workflow-version 1.6.1
```

`git-tools pr` stays in the ordinary PR mode by default (Conventional Commit title; base branch auto-detected). Fixed-title PR helpers (`--start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, `--backmerge-hotfix-pr`) generate the correct workflow titles automatically. When repo state alone cannot safely infer the tuple, pass `--workflow-version X.Y.Z`.

For the full naming policy, branch flow, and step-by-step workflow, see [GitHub Setup](docs/github-setup.md), [Git Flow Guide](docs/git-flow-guide.md), [Classic Flow](docs/git-flow-classic.md), [Classic — Reviewed](docs/git-flow-classic-reviewed.md), [Variant — Release-led](docs/git-flow-variant-release-led.md), and [Variant — Reviewed](docs/git-flow-variant-reviewed.md).

### Bump version

```bash
# Preview the next bump from Conventional Commits
git-tools bump --dry-run

# Signed prerelease example
git-tools bump --yes --increment MINOR --prerelease alpha --gpg-sign

# CI-friendly prerelease example: treat other conventional types as PATCH, without tagging
git-tools bump --yes --prerelease alpha --default-increment PATCH --no-tag

# Print only the next version
git-tools bump --get-next
```

The bump flow follows Conventional Commits increment detection and preserves whichever Commitizen version scheme the repo declares in `.cz.toml`: semver2 (`1.2.0-alpha.0`) or semver (`1.2.0-a0`). When `version_scheme = "semver2" | "semver"` is set in `[tool.commitizen]`, that scheme is always honored, including when the current version is stable and otherwise ambiguous. Bare `git-tools bump` uses the normal bump defaults: auto-detect increment, stable release, no explicit `--yes`, and no explicit `--gpg-sign`. `git-tools bump` always reads the current version from `.cz.toml`; when present, `pyproject.toml` and `uv.lock` are synced as auxiliary targets without becoming the source of truth. By default it respects `tag.gpgSign`; when that is enabled, it makes the signed-tag path explicit so Git does not block on opening an editor for the tag message. Use `--ignore-git-config` if you want the older signed-commit plus lightweight-tag shape, or `--gpg-sign` if you want an explicit signed tag.

`--default-increment` is an opt-in fallback for conventional commit types outside the built-in bump rules. The built-in rules remain:

- `type!` or `BREAKING CHANGE:` -> `MAJOR`
- `feat` -> `MINOR`
- `fix`, `refactor`, `perf` -> `PATCH`

If you pass `--default-increment PATCH`, other conventional headers such as `style`, `docs`, `test`, `ci`, `build`, `chore`, or `revert` also advance versions as `PATCH`. This is mainly useful in CI workflows where every merged PR should produce a new referenceable build.

When you launch bump from the interactive `git-tools` menu, it prompts for the increment, release channel, initial-tag behavior, and tag signing before running the same bump engine.

### Initialize Commitizen config

```bash
# Write a Commitizen config using detected defaults
git-tools init

# Explicit alias for the same direct-mode behavior
git-tools init --defaults
```

The init flow writes a Commitizen-compatible config to `.cz.toml`. For a new repo, the primary branch must already be `master` before you run `git-tools init`. Direct `git-tools init` defaults to `.cz.toml` and writes the primary managed version there. `pyproject.toml` and `uv.lock` remain auxiliary synced targets during bumps, not alternate version sources. This repo uses `.cz.toml`; `cz.toml` and Commitizen config embedded in `pyproject.toml` are intentionally unsupported. When you launch `init` from the interactive `git-tools` menu, it prompts for the supported settings instead. The generated section follows Commitizen's config layout so you can hand the repo back to `cz` later.

### Interactive menu

```bash
git-tools
```

## Options

### Commit

| Option | Short | Description |
|--------|-------|-------------|
| `--model` | `-m` | Model name (e.g., 'anthropic/claude-sonnet-4') |
| `--temp` | `-t` | Temperature (0.0-2.0) |
| `--max-tokens` | | Maximum tokens for completion |
| `--token-limit` | `-l` | Token limit for diff processing |
| `--scope/--no-scope` | | Include conventional commit scope |
| `--footer/--no-footer` | | Include conventional commit footer |
| `--commit/--no-commit` | | Commit changes directly |
| `--copy/--no-copy` | | Copy to clipboard |
| `--force-sensitive` | | Allow committing sensitive files |
| `--workflow-kind` | | Create the `chore: open release` helper commit instead of using the LLM |

### Issue

| Option | Short | Description |
|--------|-------|-------------|
| `--base` | `-b` | Base branch to compare against |
| `--source` | `-s` | Input source: 'd' (diffs), 'c' (commits), 'b' (both) |
| `--context` | `-c` | Additional context for generation |
| `--model` | `-m` | Model name |
| `--temp` | `-t` | Temperature (0.0-2.0) |
| `--max-tokens` | | Maximum tokens for completion |
| `--token-limit` | `-l` | Token limit for diff processing |

### Pull Request

| Option | Short | Description |
|--------|-------|-------------|
| `--base` | `-b` | Base branch to compare against |
| `--source` | `-s` | Input source: 'd' (diffs), 'c' (commits), 'b' (both) |
| `--context` | `-c` | Additional context for generation |
| `--release-pr/--no-release-pr` | | Use fixed-title release-promotion PR guidance for `release/* -> master` |
| `--hotfix-pr/--no-hotfix-pr` | | Use fixed-title hotfix-promotion PR guidance for `hotfix/* -> master` |
| `--start-pr/--no-start-pr` | | Use fixed-title develop PR guidance for the PR that must land as `Start X.Y.Z` into `develop` |
| `--backmerge-release-pr/--no-backmerge-release-pr` | | Use fixed-title backmerge guidance for `release/* -> develop` |
| `--backmerge-hotfix-pr/--no-backmerge-hotfix-pr` | | Use fixed-title backmerge guidance for `hotfix/* -> develop` |
| `--workflow-version` | | Provide the exact `X.Y.Z` tuple for Start or Backmerge PR modes when inference is ambiguous |
| `--model` | `-m` | Model name |
| `--temp` | `-t` | Temperature (0.0-2.0) |
| `--max-tokens` | | Maximum tokens for completion |
| `--token-limit` | `-l` | Token limit for diff processing |

### Config

`git-tools config` is interactive and currently has no user-facing CLI flags.

### Bump

| Option | Short | Description |
|--------|-------|-------------|
| `--increment` | | Explicit MAJOR, MINOR, or PATCH increment |
| `--default-increment` | | Fallback MAJOR, MINOR, or PATCH increment for other conventional commit types |
| `--prerelease` | | Create or continue an alpha, beta, or rc prerelease |
| `--increment-mode` | | Choose `linear` or `exact` prerelease bump behavior |
| `--allow-no-commit` | | Allow bumping even when no new commits are found |
| `--dry-run` | | Print the computed bump without changing files or git state |
| `--get-next` | | Print only the next version |
| `--yes` | `-y` | Treat a missing current-version tag as an initial tag only when the repository has no existing tags |
| `--tag/--no-tag` | | Create or skip the git tag for this bump |
| `--annotated-tag` | | Create an annotated tag |
| `--gpg-sign` | | Create a signed tag |
| `--annotated-tag-message` | | Custom tag message for annotated or signed tags |
| `--respect-git-config/--ignore-git-config` | | Respect or ignore `git config tag.gpgSign` during tag creation |
| `--check-consistency/--no-check-consistency` | | Require managed version fields to match before writing |
| `--major-version-zero/--no-major-version-zero` | | Override major-version-zero behavior for this run |

### Init

| Option | Short | Description |
|--------|-------|-------------|
| `--config-file` | | Choose `.cz.toml` |
| `--version` | | Set the initial version; scheme is auto-detected as semver2 (`1.0.0-alpha.0`) or semver (`1.0.0-a0`) |
| `--tag-format` | | Set the tag format, for example `$version` or `v$version` |
| `--major-version-zero/--no-major-version-zero` | | Control breaking-change behavior while major is zero |
| `--defaults` | | Write config using detected defaults without prompting |
| `--force` | | Update an existing Commitizen config in place |

Provider metadata and model lists are defined in `git_tools/config/mappings.py`. OpenRouter models are open-ended and managed via `git-tools config` (saved to `~/.git-tools/models.json`).

## Useful Git Commands

Raw git commands for manually replicating the commit logs used by the CLI.

### Develop-style PR log

```bash
git log --reverse -n 1 --pretty=format:'## %h %s%n%n%b%n' origin/develop..HEAD
```

### Release PR log

```bash
git log --reverse -n 1 --pretty=format:'## %h %s%n%n' origin/master..HEAD
```

### Cherry-pick commit log

```bash
git log --no-walk --reverse --pretty=format:'## %h %s%n%n%b%n' 2539dec 31cae4e
```

## Contributing

For development setup, branch naming, validation steps, and contribution expectations, see [Contributing](CONTRIBUTING.md).

## Code of Conduct

Community expectations and reporting guidance are in [Code of Conduct](CODE_OF_CONDUCT.md).

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

- `~/.config/git-tools/config.env`
  Written by `git-tools config`. Stores user-level provider, API key, and default overrides.
- `./git-tools.env`
  Optional repo-local env override file for the current working directory.
- `./mappings.json`
  Optional repo-local provider/model default map. If absent, `git-tools` falls back to `mappings.json.example`.

## Configuration

Run the config command to configure the provider, API key, and model defaults:

```bash
git-tools config
```

This saves settings to `~/.config/git-tools/config.env`.

Alternatively, copy the example env file and choose a provider:

```bash
cp git-tools.env.example git-tools.env
```

Supported providers:

- `openrouter` with `OPENROUTER_API_KEY`
- `kimicli` with `MOONSHOT_API_KEY`

The active provider is selected with `GIT_TOOLS_PROVIDER`.

You can also export the variables directly, for example:

```bash
export GIT_TOOLS_PROVIDER="kimicli"
export MOONSHOT_API_KEY="your-kimi-api-key"
```

Provider and model defaults come from `mappings.json` when present, otherwise from `mappings.json.example`.

If you want repo-local provider/model defaults, copy and edit `mappings.json`:

```bash
cp mappings.json.example mappings.json
```

`git-tools config` does not edit `mappings.json`; it only writes user overrides to `~/.config/git-tools/config.env`.

For release workflow and branch policy details, see [Git Flow Guide](docs/git-flow-guide.md).

By default, `.cz.toml` is the authoritative version source. When present, `pyproject.toml` and `uv.lock` are treated as auxiliary sync targets during bumps and should not block a bump just because they are behind.

## Usage

### Generate commit message

```bash
# Stage changes first, then run the direct command
git add .

# Direct command mode
git-tools commit

# With options
git-tools commit --model anthropic/claude-sonnet-4 --no-scope --no-footer --commit
```

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
git-tools pr --base master --release-pr
git-tools pr --base master --hotfix-pr
git-tools pr --base develop --sync-pr
```

`git-tools pr` stays in the normal develop/squash PR mode by default. Use `--release-pr` for release-promotion PRs from `release/* -> master`; when you do, the generator switches to a fixed release-title mode, defaults the base branch to `master` when you do not pass `--base`, and resolves the release target like this:

- if the current branch is `release/<version>` and the current prerelease line already matches it, that is treated as classic Git Flow
- if the current branch is `release/<version>` and the current prerelease line does not match it, that branch target is treated as the variant target

In all cases, the chosen release target is validated as a legal MAJOR, MINOR, or PATCH step from the base branch version. Release PR mode requires the current branch to be named `release/<x.y.z>`, and the tool fixes the PR title to `Release <target>`.

Use `--hotfix-pr` for hotfix-promotion PRs from `hotfix/* -> master`. In that mode, the generator switches to a fixed hotfix-title mode, defaults the base branch to `master` when you do not pass `--base`, and targets the next patch version from the base branch. If the hotfix branch is already on that patch `rc` line, the promotion context uses that prerelease line directly. The tool fixes the PR title to `Hotfix <target>`.

Use `--sync-pr` for branch-sync PRs from a dedicated `sync/*` branch into `develop` after a release or hotfix. In that mode, the generator switches to a fixed sync-title mode, defaults the base branch to `develop` when you do not pass `--base`, and frames the body as branch synchronization rather than a feature PR or release promotion. The tool fixes the PR title to `Sync <stable-version>`.

Pull Request output no longer includes `## Related Issue` or `Issue: #...` placeholders.

### Recommended Variant Workflow

This is the workflow to use if you want `develop` to stay as the integration branch and `release/<target>` to choose the final release version.

Bootstrap the repository locally first:

```bash
git init
git branch -M master
git-tools init
git add -A
git commit -m "Release 0.0.1"
```

Rename the initial branch to `master` before running `git-tools init`, so the first managed version is bootstrapped on the stable branch. Direct `git-tools init` seeds `.cz.toml` with `0.0.1` by default. That initial `Release 0.0.1` commit establishes the baseline on `master`. You do not need to create a `0.0.1` tag manually.

Then create the GitHub repository, add `origin`, and push `master` first:

```bash
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin master
```

The first workflow run on `master` turns that untagged bootstrap baseline into the first managed stable release:

```text
0.0.1 -> 0.1.0
```

After that bump lands, update local `master`, create `develop` from the bumped stable branch, and push it:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push -u origin develop
```

After that, use the workflow below for all later feature, release, hotfix, and sync work.

1. Normal feature and bugfix work starts from `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/commitizen-title

# make changes
git add -A
git-tools commit
git push origin feature/commitizen-title
git-tools pr --base develop
```

Use `feature/<name>` or `bugfix/<name>` branch names. Keep the PR title in Conventional Commit form because these PRs are usually squash-merged into `develop`.

2. Later production releases start from `release/<target>`:

```bash
git checkout develop
git pull origin develop
git checkout -b release/1.0.0
git push origin release/1.0.0
git-tools pr --base master --release-pr
```

The PR title is fixed to `Release <target>`, for example `Release 1.0.0`.

3. Production bug fixes start from `master` on a `hotfix/*` branch:

```bash
git checkout master
git pull origin master
git checkout -b hotfix/session-timeout

# make changes
git add -A
git-tools commit
git push origin hotfix/session-timeout
git-tools pr --base master --hotfix-pr
```

The PR title is fixed to `Hotfix <next-patch-version>`.

4. After any release or hotfix lands on `master`, sync it back into `develop` with a dedicated `sync/*` branch:

1. Start from `develop` and create a dedicated sync branch:

```bash
git checkout develop
git pull origin develop
git checkout -b sync/back-to-develop
```

2. Merge the released `master` branch into that sync branch:

```bash
git merge origin/master
```

3. Fix conflicts if needed, then finish the merge and push the sync branch:

```bash
git add -A
git commit -m "Sync 1.0.1"
git push origin sync/back-to-develop
```

4. Open a PR from `sync/back-to-develop` to `develop`. You can still use:

```bash
git-tools pr --base develop --sync-pr
```

5. Merge that PR once it is clean.

Treat `sync/*` like `release/*` and `hotfix/*`: it is a special-purpose branch for one workflow step. Do not manually bump `develop` after the sync; the next normal PR merged into `develop` starts the next alpha line.

For the full branch and version policy, see [Git Flow Guide](docs/git-flow-guide.md).

### Bump version

```bash
# Preview the next bump from Conventional Commits
git-tools bump --dry-run

# Signed prerelease example
git-tools bump --yes --increment MINOR --prerelease alpha --gpg-sign

# CI-friendly prerelease example: treat other conventional types as PATCH
git-tools bump --yes --prerelease alpha --default-increment PATCH --gpg-sign

# Print only the next version
git-tools bump --get-next
```

The bump flow follows Conventional Commits increment detection and semver2 prerelease behavior. Bare `git-tools bump` uses the normal bump defaults: auto-detect increment, stable release, no explicit `--yes`, and no explicit `--gpg-sign`. `.cz.toml` is treated as the authoritative version source by default; when present, `pyproject.toml` and `uv.lock` are synced as auxiliary targets without becoming the source of truth. By default it respects `tag.gpgSign`; when that is enabled, it makes the signed-tag path explicit so Git does not block on opening an editor for the tag message. Use `--ignore-git-config` if you want the older signed-commit plus lightweight-tag shape, or `--gpg-sign` if you want an explicit signed tag.

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

The init flow writes a Commitizen-compatible config to `.cz.toml`, `cz.toml`, or `pyproject.toml`. For a new repo, switch the primary branch to `master` first, then run `git-tools init`. Direct `git-tools init` defaults to `.cz.toml` and writes the primary managed version into the Commitizen section there unless you explicitly override `--config-file` or `--version-provider`. `pyproject.toml` and `uv.lock` are treated as auxiliary synced targets during bumps, not as the default source of truth. When you launch `init` from the interactive `git-tools` menu, it prompts for the supported settings instead. The generated section follows Commitizen's config layout so you can hand the repo back to `cz` later.

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
| `--release-pr/--develop-pr` | | Use release-promotion PR guidance for `release/* -> master`, or the default develop/squash Conventional Commit PR guidance |
| `--hotfix-pr/--no-hotfix-pr` | | Use hotfix-promotion PR guidance for `hotfix/* -> master` |
| `--sync-pr/--no-sync-pr` | | Use branch-sync PR guidance for PRs such as `sync/* -> develop` after a release or hotfix |
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
| `--annotated-tag` | | Create an annotated tag |
| `--gpg-sign` | | Create a signed tag |
| `--annotated-tag-message` | | Custom tag message for annotated or signed tags |
| `--respect-git-config/--ignore-git-config` | | Respect or ignore `git config tag.gpgSign` during tag creation |
| `--version-source` | | Choose `auto`, `commitizen`, or `pyproject` as the version source |
| `--check-consistency/--no-check-consistency` | | Require managed version fields to match before writing |
| `--major-version-zero/--no-major-version-zero` | | Override major-version-zero behavior for this run |

### Init

| Option | Short | Description |
|--------|-------|-------------|
| `--config-file` | | Choose `.cz.toml`, `cz.toml`, or `pyproject.toml` |
| `--version` | | Set the initial semver2 version |
| `--version-provider` | | Write a compatibility hint such as `commitizen`, `pep621`, or `uv` |
| `--tag-format` | | Set the tag format, for example `$version` or `v$version` |
| `--major-version-zero/--no-major-version-zero` | | Control breaking-change behavior while major is zero |
| `--defaults` | | Write config using detected defaults without prompting |
| `--force` | | Update an existing Commitizen config in place |

Model routing is configurable through `mappings.json`.

## Contributing

For development setup, branch naming, validation steps, and contribution expectations, see [Contributing](CONTRIBUTING.md).

## Code of Conduct

Community expectations and reporting guidance are in [Code of Conduct](CODE_OF_CONDUCT.md).

# CLI Reference and Interactive Usage

Run `git-tools` in the repository you want to work on. See the [project README](../README.md) for installation, the [documentation index](README.md) for platform workflows, and [configuration](configuration.md) for providers, credentials, and `.cz.toml`.

## Choose an entry point

```bash
git-tools                  # Interactive menu in a terminal
git-tools --help            # Command overview
git-tools commit --help     # Options for one command
```

Bare `git-tools` requires both stdin and stdout to be terminals to open the menu; otherwise it prints help. Direct subcommands do not prompt by default. To request prompts for a particular operation, use the supported but hidden `--interactive` / `-i` option on `commit`, `issue`, `pr`, `bump`, or `init`.

| Command | What it does | Important side effects |
| --- | --- | --- |
| `commit` | Generates a Conventional Commit message from staged changes, or a fixed release opener | **Commits by default in direct mode**; does not push |
| `issue` | Generates issue text from branch changes and commits | Prints/copies text; does not create a hosted issue |
| `pr` | Generates a PR description and title guidance | Prints/copies text; does not submit or merge a PR |
| `bump` | Computes the next version from Conventional Commits | Normally updates managed files, commits them, and creates a tag; does not push |
| `init` | Writes Commitizen-compatible `.cz.toml` | Does not initialize Git, create branches, commit, tag, or push |
| `settings` | Edits saved user settings | Writes `~/.git-tools/settings.env`; model discovery can contact the provider |

Commit/issue/PR generation normally sends selected diffs, commit messages, and context to the configured LLM provider. Review the input for confidential data first. Initialization and bumping do not require an LLM. Interactive generation can instead prepare a prompt for use elsewhere; unavailable provider credentials can also cause a local-prompt fallback rather than generated output.

## Shared generation options

These options apply to `commit`, `issue`, and `pr`. They override configured values for one run; they do not save settings.

| Option | Meaning and default |
| --- | --- |
| `--model`, `-m TEXT` | Model identifier; otherwise the configured/provider default |
| `--temp`, `-t FLOAT` | Sampling temperature; configured default is `0.6` (settings range `0.0–2.0`; model support varies) |
| `--max-tokens INTEGER` | Completion token budget; configured default is `32000` |
| `--token-limit`, `-l INTEGER` | Input diff-processing budget; default is `200000` for commits and independently `200000` for issues/PRs |

Large inputs may be reduced during processing. A processing budget is not a guarantee that the provider accepts that many input/output tokens. Model-specific capabilities and parameter handling are described in [configuration](configuration.md).

## `commit`

Stage only the changes you intend to include, then generate without committing first:

```bash
git add <files>
git-tools commit --no-commit --no-copy
# After reviewing the input and output, generate and commit:
git-tools commit --commit
```

| Option | Behavior when omitted in direct mode |
| --- | --- |
| `--scope` / `--no-scope` | No Conventional Commit scope |
| `--footer` / `--no-footer` | No footer |
| `--commit` / `--no-commit` | **Creates a real commit** with the generated message |
| `--copy` / `--no-copy` | Automatically attempts clipboard copy when not committing; this is not a separate copy-after-commit action |
| `--force-sensitive` | Off; refuses generation when staged paths match sensitive-file rules |
| `--workflow-kind open-release` | Off; uses the fixed subject `chore: open release` instead of an LLM |

**Current fallback limitation:** if the provider key is unavailable, commit generation automatically attempts to copy a locally prepared prompt, even with `--no-copy`. The flag is honored on the normal generated-message path, but not this missing-key fallback.

Ordinary generation needs a staged diff and does not stage files for you. Sensitive-file checks match filenames/path patterns, not secret contents: they are not a substitute for reviewing the diff or using a secret scanner. In interactive mode you can confirm matched files; direct mode requires unstaging them or explicitly using `--force-sensitive`. This override also allows the selected content to enter the generation workflow.

### Release-opening commit

```bash
git-tools commit --workflow-kind open-release --no-commit --no-copy
# Creates the fixed commit, allowing an empty commit:
git-tools commit --workflow-kind open-release
```

The fixed mode does not need an LLM. If files are staged, it commits those files too and still checks sensitive paths. An empty release opener alone may not produce a reviewable PR; reviewed flows require actual stabilization changes for their inner review PRs. Follow the chosen [flow guide](git-flow-guide.md), not just the subject convention.

## `issue` and `pr`

Check out the source branch and refresh the target refs with Git before generating. Choose an explicit base when reproducibility matters.

```bash
git-tools issue --base develop --source c --context "Explain the migration"
git-tools pr --base develop --source b
git-tools pr --base main --source d --no-pr-limit
```

| Option | Meaning and default |
| --- | --- |
| `--base`, `-b TEXT` | Base branch or commit hash. Ordinary mode auto-detects from checkout reflog, then `origin/HEAD`, then common branch names; final fallback is `main` |
| `--source`, `-s TEXT` | `d`: diffs; `c`: commit messages; `b`: both (default). An unrecognized value falls back to `b` |
| `--context`, `-c TEXT` | Additional intent/context; none by default |

The comparison uses committed branch history, not a substitute for `commit`'s staged-diff workflow. Branch detection/validation consults local and `origin` refs; it does not fetch. Invalid or unavailable base input can warn and fall back to a detected base, so inspect the displayed branch summary. Keep local target branches and remote-tracking refs current: commit-range discovery and diffs use the supplied base ref; diffs compare its merge-base with `HEAD` (`<base>...HEAD`).

Ordinary generation needs commits to describe. Fixed workflow modes can use validated repository/version context when no unique commits are present. Both commands display output and automatically attempt clipboard copy in direct mode; interactive mode asks before copying. There are no `--copy` or `--no-copy` flags on `issue`/`pr`.

### PR-only options

| Option | Purpose |
| --- | --- |
| `--start-pr` / `--no-start-pr` | Fixed `Start X.Y.Z` guidance for a PR into `develop` |
| `--release-pr` / `--no-release-pr` | Fixed `Release X.Y.Z` guidance for release promotion |
| `--hotfix-pr` / `--no-hotfix-pr` | Fixed `Hotfix X.Y.Z` guidance for hotfix promotion |
| `--backmerge-release-pr` / `--no-backmerge-release-pr` | Fixed `Backmerge Release X.Y.Z` guidance into `develop` |
| `--backmerge-hotfix-pr` / `--no-backmerge-hotfix-pr` | Fixed `Backmerge Hotfix X.Y.Z` guidance into `develop` |
| `--workflow-version X.Y.Z` | Explicit release tuple for Start/backmerge modes; required for noninteractive hotfix backmerge, using the already-promoted version |
| `--pr-limit` / `--no-pr-limit` | Apply/disable the configured PR-description limit for this run, on any host; aliases: `--azure-limit` / `--no-azure-limit` |

Only one fixed-title mode may be enabled. All are off by default; a release-looking branch does not automatically enable promotion mode. Release/hotfix modes default to `master`, or `main` if discovered, while Start/backmerge modes require `develop`. The documented CI flows target `master`; select the actual target required by your chosen flow. Promotion modes validate branch/version relationships when the needed configuration is available. `--workflow-version` is not a release/hotfix target override.

```bash
git-tools pr --base develop --start-pr --workflow-version 1.7.0
git-tools pr --base master --release-pr
git-tools pr --base master --hotfix-pr
git-tools pr --base develop --backmerge-release-pr --workflow-version 1.6.0
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version 1.6.1
```

Hotfix backmerge uses the **already-promoted** hotfix version, not the next patch. Supply it with `--workflow-version`; interactive mode asks for it without a guessed default. Neither latest master nor a source version synchronized with develop reliably identifies that earlier promotion, so this mode does not infer a version.

Review generated titles and the final merge/squash subject: those subjects drive CI strategy decisions. These flags generate guidance, not hosting actions or branch transitions. See [GitHub flows](github/README.md) or [Azure DevOps flows](azure-devops/README.md) for completion policy.

### PR-description length handling

Saved `auto` mode detects Azure DevOps from the `origin` URL; GitHub/unknown origins default to no limit. Saved `false` disables detection and its interactive question. CLI flags override either setting. Detection may not recognize a self-hosted Azure Server URL; use `--pr-limit` or answer Yes interactively when appropriate.

The default limit is `4000` **UTF-16 units**, configurable downward. An oversized parsed description gets one condensed-generation retry. If it is still oversized, the tool warns and retains/copies it rather than truncating it. This is best-effort handling, not a hard validator; raw-output fallback is not a guarantee of compliant length. Inspect the final description before pasting it.

## `bump`

The authoritative version configuration is `.cz.toml`; see [versioning](versioning.md) for best-effort Python/Node/Rust sync targets and supported schemes. All auxiliary sync failures warn and skip without blocking the core bump/tag; core configuration and Git failures still stop it. Prefer a clean working tree and index: the bump stages managed files and runs `git commit`, so unrelated already-staged changes can be included.

```bash
git-tools bump --dry-run       # Compute and describe the change, without writes
git-tools bump --get-next      # Print only the computed next version
git-tools bump                 # Update, commit, and tag locally
git-tools bump --increment MINOR --prerelease alpha --gpg-sign
```

| Option | Meaning and default |
| --- | --- |
| `--increment MAJOR\|MINOR\|PATCH` | Explicit increment; otherwise infer from Conventional Commits |
| `--default-increment MAJOR\|MINOR\|PATCH` | Fallback for Conventional Commit types outside built-in bump rules; unset by default |
| `--prerelease alpha\|beta\|rc` | Create/continue that prerelease channel; unset means stable release behavior |
| `--increment-mode linear\|exact` | Prerelease bump behavior; default `linear` |
| `--allow-no-commit` | Off; allows a bump without new commits, using PATCH when no increment is detected |
| `--dry-run` | Off; compute and describe without file/Git writes |
| `--get-next` | Off; compute and print only the next version, without writes |
| `--yes`, `-y` | Off; permits initial untagged history when no tags or matching prior bump anchor exist; not a general confirmation/repair flag |
| `--tag` / `--no-tag` | Create the new version tag by default |
| `--annotated-tag` | Off; request an annotated tag |
| `--gpg-sign` | Off; explicitly request a signed tag |
| `--annotated-tag-message TEXT` | Custom annotation/signature message; supplying it implies annotation |
| `--respect-git-config` / `--ignore-git-config` | Respect Git tag signing configuration by default; ignoring it does not cancel explicit `--gpg-sign` |
| `--check-consistency` / `--no-check-consistency` | Check the authoritative `.cz.toml` version before writing; on by default. Auxiliary versions remain best-effort |
| `--major-version-zero` / `--no-major-version-zero` | One-run override of configured breaking-change behavior while major is zero |

By default, breaking changes cause MAJOR (or MINOR under major-version-zero policy), `feat` causes MINOR, and `fix`/`refactor`/`perf` cause PATCH. Other types need an applicable fallback or explicit increment. Prerelease continuation/finalization depends on the current version, channel, and increment mode; inspect the computed result rather than assuming every run increments the release tuple.

History is anchored at the current version's tag, or a matching prior bump commit when the tag is absent. `--yes` does not waive inconsistent tagged history and does not recreate a missing tag. See [publication and recovery](publication.md).

Preview modes return before managed-file consistency/write checks, commit hooks, and tag creation. A successful preview is not proof the actual bump will succeed. The write/commit/tag sequence is not transactional: a failure can leave updated/staged files or a bump commit without its tag. Inspect state before retrying. Bump never publishes remote refs.

## `init`

```bash
git-tools init --version 0.0.1 --tag-format '$version'
git-tools init --defaults
# Explicitly update an existing .cz.toml:
git-tools init --force --version 1.2.3
```

| Option | Meaning and default |
| --- | --- |
| `--config-file .cz.toml` | Only supported target; `.cz.toml` is also the default |
| `--version TEXT` | Existing valid config version, otherwise latest supported version tag, otherwise `0.0.1`; explicit value overrides detection |
| `--tag-format TEXT` | Detect from supported tags, otherwise `$version`; must contain `$version`. Quote it to prevent shell expansion |
| `--major-version-zero` / `--no-major-version-zero` | Defaults to enabled for a zero-major version; disabled for nonzero major |
| `--defaults` | Accepted compatibility flag; direct init already uses detected values without prompts. It does not suppress explicit `--interactive` prompts |
| `--force` | Allow updating an existing config; normally refuse to overwrite |

The version syntax selects `semver2` (for example `1.0.0-alpha.0`) or `semver` (for example `1.0.0-a0`). Legacy `cz.toml` and a Commitizen section in `pyproject.toml` are rejected rather than migrated automatically. A valid existing `.cz.toml` updated with `--force` keeps unrelated sections but replaces its Commitizen section; invalid TOML may be overwritten. Review custom Commitizen fields before using it.

## `settings [NAME [VALUE]]`

```bash
git-tools settings                         # Interactive settings picker
git-tools settings provider                # Complete interactive provider setup
git-tools settings provider openrouter --interactive
git-tools settings provider openrouter --non-interactive
git-tools settings temperature             # Edit one setting interactively
git-tools settings temperature 0.4         # Save a value without prompts
git-tools settings pr-limit auto
git-tools settings pr-max-chars 3500
```

Supported names: `provider`, `main-model` (`model` alias), `support-model` (`sub-model` alias; reserved/unused), `api-base` (`endpoint` alias), `openrouter-provider`, `kimi-thinking`, `effort`, `api-key`, `temperature`, `max-tokens`, `max-retries`, `pr-limit`, and `pr-max-chars`. The last two also accept `azure-pr-limit` and `azure-pr-max-chars`. Underscores in names are normalized to hyphens. Bare settings and edits without a value require an interactive terminal. The command is `settings`, not the removed `config` command.

For provider choices, credential handling, model discovery, validation, defaults, and setting precedence, use [configuration](configuration.md). Prefer the masked API-key prompt over passing secrets as command arguments (which may enter shell history/process listings).

## Practical interactive walkthrough

Use **Up/Down** and **Enter** for selections, and type into text prompts/searchable model lists. Yes/No questions are selections too. **Ctrl+C** cancels. In settings, **Esc** or **← Back** returns to the prior level; standalone settings ends with **Done**. Settings opened from the main menu returns to that menu, with saved values reloaded. A content command finishes the invocation; run `git-tools` again for the next operation.

| Menu choice | Practical sequence |
| --- | --- |
| **init** | Confirm initial version and tag format, select zero-major policy when asked, review the summary, then answer **Write Commitizen config now?**. Continue with the platform bootstrap guide. |
| **commit** | Stage files first. Select **Conventional Commit** or **chore: open release**, review warnings/input, and choose scope/footer preferences. Inspect the result before **Commit changes directly?**; decline to copy/use the text yourself. |
| **issue** / **pr** | Check out the source and refresh target refs first. Select the PR mode when applicable; confirm base/version and inspect the branch summary. Choose diffs/commits/both, input budget, and additional context when prompted. Inspect/copy the result for your hosting UI. |
| **bump** | Inspect repository context; select increment, release channel, prerelease mode when shown, initial-history permission, and tag signing. Choose preview first, then repeat with write options on a clean index. |

For ordinary content generation, keep **Generate … using external providers?** enabled to use the configured LLM, then follow model/parameter prompts. Decline to prepare a prompt for another tool. Clipboard prompts depend on the path taken and clipboard availability.

For PRs in saved `auto` mode, inspect origin detection before answering the description-limit question; choose Yes for Azure Server URLs not recognized automatically. The **issue** and **pr** menu entries already select the output type, so there is normally no separate content-type question.

**Bump warning:** **Preview only without changing files or git state?** defaults to **No**. There is no separate final confirmation after the options summary before the bump runs.

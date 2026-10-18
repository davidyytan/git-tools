# CLI Reference and Interactive Usage

Run `git-tools` in the repository you want to work on. See the [project README](../README.md) for installation, the [documentation index](README.md) for platform workflows, and [configuration](configuration.md) for providers, credentials, and `.cz.toml`.

## Choose an entry point

```bash
git-tools                  # Interactive menu in a terminal
git-tools --help            # Command overview
git-tools commit --help     # Options for one command
```

Bare `git-tools` requires both stdin and stdout to be terminals to open the menu; otherwise it prints help. Direct generation, bump, and init subcommands do not prompt by default. To request prompts for a particular operation, use the `--interactive` / `-i` option on `commit`, `issue`, `pr`, `bump`, or `init`. The `settings` command has its own terminal-dependent setup/edit behavior described below.

| Command | What it does | Important side effects |
| --- | --- | --- |
| `commit` | Generates a Conventional Commit message from staged changes, or a fixed release opener | **Commits by default in direct mode**; does not push |
| `issue` | Generates issue text from branch changes and commits | Prints/copies text; does not create a hosted issue |
| `pr` | Generates a PR description and title guidance | Prints/copies text; does not submit or merge a PR |
| `bump` | Computes the next version from Conventional Commits | Normally updates managed files, commits them, and creates a tag; does not push |
| `init` | Writes Commitizen-compatible `.cz.toml` | Does not initialize Git, create branches, commit, tag, or push |
| `settings` | Edits saved user settings | Writes `~/.git-tools/settings.env`; model discovery can contact the provider |

Commit/issue/PR generation normally sends selected diffs, commit messages, and context to the configured LLM provider. Review the input for confidential data first, and check the [current destination/profile limitations](configuration.md#current-limitations) before sending it. Initialization and bumping do not require an LLM. Interactive generation can instead prepare a prompt for use elsewhere; unavailable provider credentials can also cause a local-prompt fallback rather than generated output.

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
| `--scope` / `--no-scope` | Saved scope preference; off by default |
| `--body` / `--no-body` | Saved optional multiline description/body preference; enabled by default; short summary always required |
| `--body-style bullets\|prose` | Saved body style; `bullets` (point form) by default, or prose paragraphs |
| `--footer` / `--no-footer` | Saved footer preference; off by default |
| `--commit` / `--no-commit` | **Creates a real commit** with the generated message |
| `--copy` / `--no-copy` | Automatically attempts clipboard copy when not committing; this is not a separate copy-after-commit action |
| `--force-sensitive` | Off; refuses generation when staged paths match sensitive-file rules |
| `--workflow-kind open-release` | Off; uses the fixed subject `chore: open release` instead of an LLM |

Use **Settings → Commit format** (or `git-tools settings commit-format`) to edit scope, description/body, body style, and footer together. Each completed edit saves immediately; Back leaves the group and returns to its caller. “Description (body)” is below the required one-line summary. Turning it off still permits factual footers when enabled; choosing prose removes body bullet instructions from both provider and prepared local prompts. The style is retained when the body is disabled. These are generation instructions, not a post-processing rewrite; inspect the output before committing.

```bash
# One-run overrides; do not commit or copy the result:
git-tools commit --body --body-style prose --no-commit --no-copy
git-tools commit --no-body --no-scope --no-footer --no-commit --no-copy
```

`--no-copy` is honored on generated, local-prompt, and missing-key paths. Prepared local prompts are always displayed. Missing credentials do not authorize automatic copying: interactive mode asks, while direct mode copies a fallback prompt only with explicit `--copy`. Normal generated output still auto-copies in direct mode when not committing.

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
| `--base`, `-b TEXT` | Base branch/ref or commit hash. Ordinary mode infers from checkout reflog, then `origin/HEAD`, then common branch names; fails clearly if no usable base is found |
| `--source`, `-s TEXT` | `d`: diffs; `c`: commit messages; `b`: both. Uses the saved source preference, initially `b`; an unrecognized explicit value falls back to `b` |
| `--context`, `-c TEXT` | Additional intent/context; one optional field in interactive mode |
| `--copy` / `--no-copy` | Override clipboard handling for this run; otherwise interactive mode asks and direct generated output auto-copies |

The comparison uses committed branch history, not a substitute for `commit`'s staged-diff workflow. Resolution is read-only: it does not fetch or switch branches. Explicit bare names prefer an existing local branch; a remote-tracking ref is used when the local branch is absent. Use `--base origin/develop` to request that ref explicitly. Inferred defaults prefer remote-tracking refs and skip the current branch; ordinary mode also avoids equal-HEAD comparisons, while fixed modes can use a distinct target at the same tip for context-only output. Invalid explicit refs fail rather than silently changing the base. The exact resolved ref is retained for version lookup and comparison; commit messages come from the same merge-base-to-HEAD range as the summary, and diffs retain merge-base semantics (`<base>...HEAD`). Keep target refs current and inspect the displayed summary.

Ordinary generation needs commits to describe. Fixed workflow modes can use validated repository/version context when no unique commits are present. Output parsing removes only a verified matching outer code fence; unfenced or partial content is preserved. PR clipboard text matches the parsed preview. Issue/both output retains its existing raw-response clipboard format for compatibility. Prepared local prompts are always displayed; missing-key fallback follows the same explicit-copy rule as `commit`.

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

Only one fixed-title mode may be enabled. All are off by default; a release-looking branch does not automatically enable promotion mode. Release/hotfix modes default to `master`, or `main` if discovered, while Start/backmerge modes require `develop`. The documented CI flows target `master`; select the actual target required by your chosen flow. Promotion modes validate branch/version relationships when the needed configuration is available. `--workflow-version` is not a release/hotfix target override. An explicit Start tuple is validated and never replaced with an inferred version; missing current/base version context produces a targeted error.

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

Saved `auto` mode detects Azure DevOps from the `origin` URL and applies that result without a routine confirmation; GitHub/unknown origins default to no limit. Saved `false` disables automatic limiting. CLI flags override either setting. Detection may not recognize a self-hosted Azure Server URL; use `--pr-limit` when appropriate.

The default limit is `4000` **UTF-16 units**, configurable downward. An oversized parsed description gets one condensed-generation retry. If it is still oversized, the tool warns and retains/copies it rather than truncating it. This is best-effort handling, not a hard validator; raw-output fallback is not a guarantee of compliant length. Inspect the final description before pasting it.

## `bump`

The authoritative version configuration is `.cz.toml`; see [versioning](versioning.md) for best-effort Python/Node/Rust sync targets and supported schemes. Handled auxiliary sync failures warn and skip rather than blocking the core bump/tag; core configuration and Git failures still stop it. Known planning/snapshot defects remain; read [current versioning limitations](versioning.md#current-limitations). Apply requires an empty index: all pre-staged changes, including managed files, are rejected before mutation. Unstage them deliberately before retrying (for example `git restore --staged .`); this leaves working-tree edits intact. Existing unstaged edits in managed files can still enter the bump commit, so review the complete plan. Unmanaged unstaged files are not staged by bump.

```bash
git-tools bump --dry-run       # Preview planned files/diffs without writes
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
| `--dry-run` | Off; compute the managed-file plan and show diffs without file/Git writes |
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

`--get-next` remains a lightweight version calculation. `--dry-run` also runs the in-memory file planner and consistency checks, showing changed paths, diffs, warnings, commit scope, and effective tag/signing behavior; staged repositories may be previewed. Interactive bump computes one plan, then offers **Preview / Apply / Cancel**, defaulting to Preview; after preview, Apply uses that same plan without repeating the wizard. Changes to the captured HEAD, branch, tags, managed-file bytes, discovery metadata, or selected Git settings invalidate the plan before writes. Git executable-mode changes are not currently captured, and nonregular metadata paths can hang planning even when auxiliary sync is disabled; see [current limitations](versioning.md#current-limitations). Initial-history consent is requested only when no tag or prior bump anchor exists.

A successful preview cannot guarantee that hooks, signing, or Git will succeed. The write/commit/tag sequence remains nontransactional: a failure can leave updated/staged files or a bump commit without its tag. Inspect state before retrying. Bump never publishes remote refs.

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
| `--tag-format TEXT` | Preserve an existing configured format; for new config, detect from tags or use `$version`. Explicit values must contain `$version`; quote them to prevent shell expansion |
| `--major-version-zero` / `--no-major-version-zero` | Preserve existing policy when updating; new config enables it for zero-major versions |
| `--defaults` | Use resolved defaults without prompts, even if `--interactive` is also supplied |
| `--force` | Update an existing valid config while retaining custom fields and comments; otherwise refuse overwrite |

For new config, the version syntax selects `semver2` (for example `1.0.0-alpha.0`) or `semver` (for example `1.0.0-a0`). Updating a stable `X.Y.Z` version preserves an explicit existing scheme, so future prerelease formatting does not change. Legacy `cz.toml` and a Commitizen section in `pyproject.toml` are rejected rather than migrated automatically. Updating a valid `.cz.toml` with `--force` preserves custom Commitizen fields, comments, nested tables, and saved tag/zero-major policy while applying the resolved version and explicit overrides. Invalid TOML is rejected without writing: repair it, or deliberately back up/remove it before creating a fresh config. Existing-config refusal happens before collecting unusable answers.

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
git-tools settings commit-input-budget 200000
git-tools settings issue-pr-input-budget 200000
git-tools settings commit-format          # Open the grouped editor
git-tools settings commit-scope false
git-tools settings commit-body true
git-tools settings commit-body-style prose
git-tools settings commit-footer false
git-tools settings issue-pr-source b
```

Supported names: `provider`, `main-model` (`model` alias), `api-base` (`endpoint` alias), `openrouter-provider`, `kimi-thinking`, `effort`, `api-key`, `temperature`, `max-tokens` (`output-budget` alias), `commit-input-budget` (`token-limit` alias), `issue-pr-input-budget` (`issue-pr-token-limit` alias), `commit-format` (interactive group), `commit-scope`, `commit-body`, `commit-body-style`, `commit-footer`, `issue-pr-source`, `max-retries`, `pr-limit`, and `pr-max-chars`. The removed `support-model` / `sub-model` editors (also `support_model` / `sub_model`) are unknown settings, not deprecated no-ops. PR limit settings also accept `azure-pr-limit` and `azure-pr-max-chars`. Underscores in names are normalized to hyphens. Bare settings and edits without a value require an interactive terminal. The command is `settings`, not the removed `config` command.

For provider choices, credential handling, model discovery, validation, defaults, and setting precedence, use [configuration](configuration.md). Prefer the masked API-key prompt over passing secrets as command arguments (which may enter shell history/process listings).

## Practical interactive walkthrough

Use **Up/Down** and **Enter** for selections, and type into text prompts/searchable model lists. Yes/No questions are selections too. **Ctrl+C** cancels. In settings, **Esc** or **← Back** returns to the prior level; standalone settings ends with **Done**. Settings opened from the main menu returns to that menu, with saved values reloaded. A content command finishes the invocation; run `git-tools` again for the next operation.

| Menu choice | Practical sequence |
| --- | --- |
| **init** | Confirm initial version and tag format, select zero-major policy when asked, review the summary, then answer **Write Commitizen config now?**. Continue with the platform bootstrap guide. |
| **commit** | Stage files first. Select **Conventional Commit** or **chore: open release**, review warnings/input using saved budget and commit-format preferences. Inspect the result before **Commit changes directly?**; decline to copy/use the text yourself. |
| **issue** / **pr** | Check out the source and refresh target refs first. Select the PR mode when applicable; confirm base/version and inspect the branch summary. Saved source/budget/PR-limit preferences apply automatically; enter optional additional context. Inspect/copy the result for your hosting UI. |
| **bump** | Inspect repository context; select increment, release channel, and prerelease mode when shown. Initial-history permission is conditional. Review the computed version, files and effective signing, then Preview / Apply / Cancel; Apply reuses the reviewed plan on an empty index. |

For ordinary content generation, answer **Yes** to **Generate … using external providers?** to use the provider, main model, and options already configured in `git-tools settings`. Provider/model parameters, input budgets, commit format, source, and PR-limit preferences are reused without routine reconfiguration. CLI flags override saved values for that invocation only. Modes, base/version/context, external-send consent, and final commit/write actions remain task-specific decisions.

Answer **No** to prepare a prompt for another tool and choose whether to copy it. Canceling the confirmation stops the operation without proceeding to provider setup, generation, clipboard copy, or a commit action. Missing credentials can still offer inline key setup; routine configured generation does not ask for configuration again. Prepared prompts are displayed even if copying is declined or unavailable. Explicit `--no-copy` never copies or asks to copy. `--copy` requests copying for generated output or prepared local prompts when handed off; for `commit`, copying occurs only when the command does not commit.

For PRs in saved `auto` mode, inspect the origin detection result; use `--pr-limit` for Azure Server URLs not recognized automatically. The **issue** and **pr** menu entries already select the output type, so there is normally no separate content-type question.

**Bump safety:** interactive Apply is explicit and uses the reviewed plan, subject to the [FIFO, executable-mode, and custom-selector limitations](versioning.md#current-limitations). Direct `git-tools bump` remains automation-friendly and applies without an extra confirmation, but rejects pre-staged content. Git-configured signing remains authoritative; the plan shows its effective behavior.

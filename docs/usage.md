# Direct CLI and Interactive Usage

Both entry points use the same local generators. Choose direct commands when
reproducible flags matter; choose the interactive terminal menu when you want
prompts to guide you. GitHub and Azure DevOps use the same CLI. Their CI,
repository permissions, and PR completion instructions are separate:

- [GitHub setup and flows](github/README.md)
- [Azure DevOps setup and flows](azure-devops/README.md)
- [Flow comparison and shared policy](git-flow-guide.md)

## Install and Start

Follow the [installation instructions](../README.md#installation) first. Run
commands inside the target Git repository, not the git-tools source checkout.
Configure an LLM provider for commit/issue/PR generation; initialization and
version bumping do not require an LLM.

```bash
# Open the terminal menu
git-tools
# Or inspect direct commands and their supported flags
git-tools --help
git-tools pr --help
```

The menu is:

```text
Select command:
  commit
  issue
  pr
  bump
  init
  settings
  exit
```

Use **Up/Down** to highlight an item and **Enter** to select it. These are
terminal selections, not browser buttons. Yes/No questions also use selectable
choices. Type into text prompts; searchable model lists accept typed searches.
Use **Ctrl+C** to cancel. In settings, **Esc** or **← Back** returns to the
previous level; the standalone settings menu ends with **Done**. Returning from
settings opened through the main menu brings you back to **Select command:**.
After a content command finishes, run `git-tools` again for another operation.
Without an interactive terminal, bare `git-tools` prints help rather than
opening the menu. Direct commands use defaults and flags instead of the menu,
though some operations can still request a final confirmation.

## Configure a Provider and Model

### Direct CLI

```bash
git-tools settings provider openrouter
git-tools settings api-key             # Secure interactive key entry
git-tools settings model anthropic/claude-sonnet-4.6
git-tools settings temperature 0.6
git-tools settings max-tokens 32000
```

`settings api-key` without a value deliberately prompts so the key need not be
placed in shell history. Direct provider selection does not perform the full
interactive key/model wizard: configure the key and model separately. Provider
names include `openrouter`, `kimicli`, and `cliproxyapi`. See the
[configuration reference](../README.md#configuration) for endpoints, environment
variables, and local proxy defaults.

### Interactive Navigation

1. Run `git-tools`, select **settings**, and press Enter. Alternatively run
   `git-tools settings` to go straight to settings.
2. At **Select setting to edit:**, select **Provider** (the row also shows the
   current value).
3. Choose the desired provider, follow its API-key prompt when required, then
   select its model. Complete the wizard to save the provider change; cancelling
   before completion leaves the previous provider configuration intact.
4. To change a model later, select **Model**. Pick a discovered model, search a
   large catalog, or choose **Enter a model ID manually…** and enter its exact ID.
   If discovery fails, saved/manual and static fallback models remain available.
5. Select **API Key**, **Temperature**, **Max Tokens**, or **Max Retries** to edit
   those values. **Effort** applies to models that support reasoning effort;
   its available choices depend on the model.
6. Choose **← Back** to return to the main menu, or **Done** when using the
   standalone settings command.

User defaults are saved in `~/.git-tools/settings.env`; manual model IDs are
saved in `~/.git-tools/models.json`. Process environment variables can override
saved values. Repo-local `git-tools.env` is another configuration source, not a
file that is automatically committed or required for CI version bumps.

## Initialize Commitizen Configuration

First initialize Git on the primary branch if needed:

```bash
git init -b master
```

### Direct CLI

```bash
git-tools init
# Explicit initial prerelease for the documented bootstrap
git-tools init --version 0.1.0-rc.0
```

### Interactive Navigation

1. Run `git-tools` → select **init**.
2. At **Enter the initial version**, enter the version required by your platform
   setup guide (the bootstrap baseline is `0.1.0-rc.0`).
3. At **Enter the tag format**, use `$version` unless your repository intentionally
   uses another format containing `$version`.
4. If major is zero, answer **Treat breaking changes as MINOR while major version
   is zero?** according to your version policy.
5. Review the configuration and confirm **Write Commitizen config now?**.

This writes `.cz.toml`; it does not initialize Git, add a remote, commit files,
create `develop`, or push. Follow the platform setup sequence, and do not replace
an existing `.cz.toml` casually (`--force` is an explicit overwrite option).

## Generate a Commit

### Direct CLI

```bash
git add <files>
git-tools commit
# Deterministic release-opening subject (can create an empty commit)
git-tools commit --workflow-kind open-release
```

### Interactive Navigation

1. Stage the intended files with `git add <files>` in the shell.
2. Run `git-tools` → select **commit**.
3. At **Select commit mode**, choose **Conventional Commit** for ordinary work,
   or **chore: open release** only when the flow calls for an RC-opening commit.
4. For ordinary generation, review the staged diff and answer the scope/footer
   questions. Keep **Generate commit message using external providers?** enabled
   to use the configured LLM; select a model and generation parameters when asked.
5. Inspect the resulting subject/body before answering **Commit changes directly?**.
   If you decline, use the generated message yourself. Clipboard prompts depend
   on the selected path and clipboard availability.
6. Push the branch using Git, then follow the platform PR instructions.

Inspect staged files before confirming: this operation can create a real commit.
An empty release-opening commit has no file diff and may not produce a reviewable
PR by itself. Reviewed flows need an actual stabilization change for an inner PR;
see their guide's caveat instead of treating an empty commit as reviewed work.

## Generate a Pull Request or Issue

### Direct CLI

```bash
git-tools pr --base develop --source b
git-tools issue --base develop --source c
git-tools pr --base develop --start-pr --workflow-version 1.7.0
git-tools pr --base master --release-pr
git-tools pr --base master --hotfix-pr
git-tools pr --base develop --backmerge-release-pr --workflow-version 1.6.0
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version 1.6.1
```

`--source d` uses diffs, `c` uses commit messages, and `b` uses both. These
commands compare the checked-out branch with the supplied base. Fixed-title
modes are mutually exclusive. Supply `--workflow-version X.Y.Z` when the desired
Start/backmerge tuple cannot be safely inferred.

### Interactive Navigation

1. Check out the source branch and fetch the latest target refs in the shell.
2. Run `git-tools` → select **pr** (or **issue** for issue-only generation).
3. For PRs, at **Select PR mode**, choose the row matching the purpose below.
4. At **Enter base branch name or commit hash**, confirm the actual target
   branch. Mode-specific validation may set or check the expected base and ask
   for a missing workflow version. Do not accept a guessed target blindly.
5. If commits are available, at **Select input source**, choose **Diffs only**,
   **Commit messages only**, or **Both diffs and commits**. Answer the token limit
   and **Add additional context?** prompts when shown.
6. For PR output, inspect the reported `origin` detection and answer **Apply the
   4000-character PR description limit?**. Choose Yes for Azure DevOps, including
   an Azure Server URL not automatically recognized.
7. Follow the model/generation prompts, inspect the result, and use **Copy to
   clipboard?** if offered.
8. Paste the title and description into GitHub or Azure Repos. Verify the source,
   target, reviewers, and final merge subject before submitting/completing the PR.

| Interactive PR mode | Direct flag | Target / expected title |
| --- | --- | --- |
| Ordinary PR | No fixed-title flag | Intended target; Conventional Commit title |
| Start PR | `--start-pr` | `develop`; `Start X.Y.Z` |
| Release PR | `--release-pr` | `master`; `Release X.Y.Z` |
| Hotfix PR | `--hotfix-pr` | `master`; `Hotfix X.Y.Z` |
| Backmerge Release PR | `--backmerge-release-pr` | `develop`; `Backmerge Release X.Y.Z` |
| Backmerge Hotfix PR | `--backmerge-hotfix-pr` | `develop`; `Backmerge Hotfix X.Y.Z` |

The `pr` and `issue` menu entries already select the output type, so they do not
normally display **Select content to generate**. Generation writes text locally;
it does **not** create issues, submit PRs, or complete merges through hosting APIs.
If a required flag has no menu equivalent, use the direct command.

### Azure Description Limit

Direct PR generation automatically detects common Azure `origin` URLs.
`--azure-limit` forces the limit; `--no-azure-limit` disables it. Use the override
for custom Azure Server URLs or when generating text for a different host than
`origin`. Interactive generation asks with the detected default. The limit is
4,000 UTF-16 units for the generated description before the separately appended
commit-log block; supplementary Unicode characters count as two units.
The tool retries oversized descriptions once, but always check the final pasted
content, especially when including the commit log. See
[Azure setup](azure-devops/setup.md#local-cli-and-pr-descriptions).

## Preview or Run a Local Version Bump

### Direct CLI

```bash
git-tools bump --dry-run
# Only apply once you have checked the decision
git-tools bump --yes --increment MINOR --prerelease alpha --gpg-sign
```

### Interactive Navigation

1. Run `git-tools` → select **bump**.
2. At **Select version increment**, choose **Auto-detect from commits**, **PATCH**,
   **MINOR**, or **MAJOR**.
3. At **Select release channel**, choose **Stable release**, **alpha**, **beta**,
   or **rc**. For prereleases, choose the requested **prerelease increment mode**.
4. Answer the missing-tag and signed-tag questions deliberately.
5. For a safe first check, answer Yes to **Preview only without changing files or
   git state?** and inspect the summary.

A local bump can change version files, create a commit, and create a tag. It does
not replace the CI flow strategy, which applies branch and promotion gates.
Do not race a manual version bump against an active CI versioning pipeline;
follow the selected platform guide and pull CI's version commit before more work.

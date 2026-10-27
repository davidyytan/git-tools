# Azure DevOps Setup

[Azure DevOps guides](README.md) · [Documentation index](../README.md) · [CLI usage](../usage.md)

Set up **one** classic or release-led versioning pipeline in your own Azure Repos repository. Reviewed modes use the same adapter as their base flow; review is enforced through PR policies, not a second pipeline.

Configuring an existing pipeline? Use the copy block below, then check its YAML identity and [permissions](#6-grant-build-service-permissions). **Skip bootstrap if your repository already has release history.** For a fresh repository, follow steps 1–7 or one [complete walkthrough](README.md#full-walkthroughs).

## Already Have an Automation Key? Copy It into CI

**Destination: Azure DevOps → Pipelines → your pipeline → Edit → Variables → New variable → `BOT_GPG_SECRETKEY` → enable “Keep this value secret”.** Use an existing **dedicated automation signing key**, not your personal key. Select its long ID or full fingerprint from the first command and replace `YOUR_GPG_KEY_ID` before running the second:

```bash
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY (secret pipeline variable)
```

Paste the entire armored private-key block with its original line breaks into **`BOT_GPG_SECRETKEY`**. If the pipeline does not exist yet, run this block after [creating it](#4-create-the-azure-pipeline). Do not save an export file. No SSH key, PAT, or bot user is needed on Azure.

The template has **no passphrase input**: use only an approved key that can sign unattended without one. Never log the key, enable tracing around it, or paste it into YAML/chat. Multiline-secret masking does not reliably hide individual lines. Already configured the key? No need to recreate it or register it on a hosting account. [Need a new key?](#2-choose-an-automation-signing-key)

## Before You Start

- Install Git, **Python 3.12**, uv, GnuPG, and [git-tools](../../README.md#install). Keep its source checkout: installation is editable.
- Use your **own name/email** for human commits, your **own Azure organization/project/repository** for the application origin, and a **dedicated automation identity** for signing. The upstream URL `https://github.com/davidyytan/git-tools.git` is the tool source, not your application origin.
- These adapters use `master` and `develop`. You need permission to configure Pipelines and repository security, or an administrator's help.
- In **Organization settings → Pipelines → Settings** or **Project settings → Pipelines → Settings**, enable **Limit job authorization scope to current project for non-release pipelines**. YAML pipelines are non-release pipelines even when managing Git release branches. This selects the project Build Service identity used below; organization-level enforcement cannot be relaxed by a project.
- Versioning CI needs no LLM key, Azure bot user, SSH key, or PAT. Checkout/push use Azure's automatic Build Service job token. Local AI commit/PR generation separately needs a [configured provider](../configuration.md).

## 1. Copy and Configure One Adapter

Work in your application repository, **not the git-tools source checkout**. Initialize a fresh repository on `master` if needed:

```bash
git init -b master
```

Copy one example from your retained upstream checkout into the application, removing `.example`:

| Flow | Source in git-tools | Destination in your application |
| --- | --- | --- |
| Classic / Classic — Reviewed | [Classic example](../../.azure/workflows/version-bump-git-flow-classic.yml.example) | `.azure/workflows/version-bump-git-flow-classic.yml` |
| Release-led / Release-led — Reviewed | [Release-led example](../../.azure/workflows/version-bump-git-flow-variant-release-led.yml.example) | `.azure/workflows/version-bump-git-flow-variant-release-led.yml` |

The steps below use classic filenames. Substitute the release-led filename when choosing that flow. Do not activate both adapters for the same branches.

In the copied YAML, keep the upstream tool URL and select a **supported engine branch or tag**:

```yaml
GIT_TOOLS_REPO: https://github.com/davidyytan/git-tools.git
GIT_TOOLS_REF: develop
```

Verify that the selected ref contains Azure `Merged PR <id>:` subject normalization, your classic/variant strategy, and `git_tools.generators.publish`. Prefer an immutable supported tag for reproducibility. The example uses `git clone --branch`, so a bare commit SHA is not supported. Installing a newer local CLI does not update this remote CI clone.

Replace these values with **your own automation name and email**, matching the GPG identity selected in step 2. They need not represent an Azure user account:

```yaml
GIT_BOT_NAME: YOUR_AUTOMATION_NAME
GIT_BOT_EMAIL: YOUR_AUTOMATION_EMAIL
```

Keep full history, tag fetching, and `persistCredentials: true`. Set `GIT_TOOLS_BUMP_SYNC_AUXILIARY` to `'true'` to sync supported auxiliary version files, or `'false'` for `.cz.toml` only. `git-tools init` creates version configuration; it does not install or authorize a pipeline.

## 2. Choose an Automation Signing Key

**Already have a suitable automation key?** Skip creation and use the [copy block above](#already-have-an-automation-key-copy-it-into-ci) when setting the pipeline secret. It prints the existing key; it does not create or replace one.

### Need a New Key? Optional Create-First Path

Only if you do not have an approved automation key, run this locally:

```bash
gpg --full-generate-key
```

At the prompts:

1. Choose a key type that supports **signing** (for example RSA and RSA). An RSA size of 3072 bits is a reasonable starting point if your policy allows it.
2. Set an expiration matching your organization's rotation policy.
3. Enter **your own dedicated automation name/email**, matching YAML `GIT_BOT_NAME` and `GIT_BOT_EMAIL`, not the upstream author or your personal signing identity.
4. The template has **no passphrase input**. Only under an approved unattended-key policy, leave the new automation key's passphrase empty and confirm any GnuPG warning. If policy requires a protected key, stop and adapt noninteractive signing securely instead; importing it alone does not unlock signing. Do not remove a personal key's passphrase.

Then return to the **same [list/export copy block](#already-have-an-automation-key-copy-it-into-ci)**, select the new automation key, and paste its printed private block into **`BOT_GPG_SECRETKEY`** after the pipeline exists. Azure needs no GitHub-style public-key registration or SSH key for this pipeline. Plan expiration, rotation, revocation, and approved backup storage. Use a trusted, unrecorded terminal and clear clipboard history where practical; no export file or Secure File upload is needed.

## Bootstrap `master` and `develop`

Steps 3–7 bootstrap a **fresh** repository: push once, create/configure the pipeline, run it manually, then create `develop` from the stable bot commit. Do not repeat bootstrap to repair a failure.

## 3. Bootstrap and Push `master`

An empty Azure Repo has no branch or YAML for the pipeline picker. In your application repository, replace the origin URL with **your own Azure organization, project, and repository**. Configure **your own human Git name/email**, not the automation identity:

```bash
git config user.name "YOUR_NAME"
git config user.email "YOUR_EMAIL"
git remote add origin "https://dev.azure.com/YOUR_ORG/YOUR_PROJECT/_git/YOUR_REPOSITORY"
git-tools init --version 0.0.1 --tag-format '$version'
```

If `pyproject.toml` contains `[project].version`, initialize it to `0.0.1` too. Review what you are staging; no credentials belong in this commit:

```bash
git add -A
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```

Set the Azure repository's default branch to `master` after this push. Keep `Release 0.1.0` as the latest subject until bootstrap runs. The engine also accepts `Release 0.0.1`, but the documented sequence uses `Release 0.1.0` to produce stable `0.1.0` from the `0.0.1` seed.

## 4. Create the Azure Pipeline

1. Open **Pipelines → New pipeline → Azure Repos Git** and select your application repository.
2. Choose **Existing Azure Pipelines YAML file**, branch **master**, and `/.azure/workflows/version-bump-git-flow-classic.yml` (or the release-led file).
3. **Save** without running. Give it a recognizable name such as `<your-repo>-version-bump-classic` or `<your-repo>-version-bump-release-led`.

Create a separate pipeline definition for each repository, with only one active versioning adapter per set of branches.

## 5. Set the Signing Secret

In the saved pipeline, open **Edit → Variables → New variable**:

- **Name:** `BOT_GPG_SECRETKEY`
- **Value:** the complete armored private key printed by the [list/export commands](#already-have-an-automation-key-copy-it-into-ci).
- Enable **Keep this value secret**, leave queue-time override disabled, and save.

Preserve the original multiline block. Do not add quotes, flatten it, or replace real newlines with literal `\n`. Azure does not repair multiline formatting; these examples use Bash on `ubuntu-latest`.

The template maps this secret into the import step's environment and imports it through stdin. **If your pipeline uses an older Secure File-based adapter, update its signing step to this template first; adding the variable alone does not change the old adapter.** Do **not** put the secret value or an empty same-named default in YAML. There is no separate secret-authorization step. Configure the secret on **each pipeline definition**, even when reusing an approved automation key. One key per project or repository gives stronger rotation/revocation isolation.

`BOT_GPG_SECRETKEY` signs commits/tags; the Build Service token authenticates pushes. `BOT_SSH_SECRETKEY` is not used on Azure.

## 6. Grant Build Service Permissions

Use the project-scoped identity **`<Your Project> Build Service (<Your Organization>)`**. Under **Project settings → Repositories → your repository → Security**, grant:

- **Read**
- **Contribute**
- **Create branch**
- **Create tag**

Grant permissions per repository for least privilege. Each Azure project has its own identity. Do not use the collection-wide **Project Collection Build Service Accounts** group. If repository access protection prompts for this pipeline's authorization, approve access to this repository.

**Identity missing?** A project's Build Service identity is created when a pipeline first runs, not necessarily when saved. Configure the secret and queue an initial run to materialize it. That attempt may fail at checkout/push. Once the identity appears, grant the permissions and rerun on `master`. Before retrying, check whether a bump commit or tag reached the remote; pull/fetch and inspect any partial publication instead of adding another bootstrap commit.

Protect `master`/`develop` and, for reviewed modes, stabilization branches. Required-PR policies may need a narrowly approved, branch-scoped automation push exception for generated version commits. Do not give humans blanket bypass or grant **Bypass policies when pushing** without explicit administrator approval.

## 7. Run Bootstrap and Create `develop`

After the secret, repository access, and permissions are ready, open your pipeline and choose **Run pipeline → master → Run**. The earlier push is **not retroactive**: it occurred before the pipeline existed.

Wait for the entire run, including publication, to succeed. Expected result:

- signed bot commit `bump: version 0.0.1 → 0.1.0`;
- signed tag **`0.1.0`**.

Pull the bot commit and explicitly fetch tags, then create `develop` from that stable result:

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.1.0
git checkout -b develop
git push -u origin develop
```

Do not create `develop` from the original bootstrap commit. If publication fails, inspect the remote and follow [recovery](../publication.md); do not create a competing bump or tag.

## Merge Settings

Permit **Squash commit** and **Merge (no fast-forward)** as needed by your selected walkthrough. Prohibit rebase completion. The final commit subject on the target must be the documented PR title, not an unrelated generated merge message.

| Target / action | Final subject |
| --- | --- |
| Ordinary feature/bugfix into `develop` | Conventional Commit |
| Open a develop cycle | `Start X.Y.Z` |
| Promote release into `master` | `Release X.Y.Z` |
| Promote hotfix into `master` | `Hotfix X.Y.Z` |
| Release backmerge into `develop` | `Backmerge Release X.Y.Z` |
| Hotfix backmerge into `develop` | `Backmerge Hotfix X.Y.Z` |

For squash, set the final squash subject to the PR title. For merge commits, customize the first line to the PR title. **Synchronization and boundary-backmerge steps marked Merge (no fast-forward) must preserve ancestry and untagged bump anchors; do not squash them.** Reviewed stabilization PRs follow their mode's merge policy.

### Pull Request ID Setting

In **Project settings → Repositories → your repository → Settings**, disable inclusion of the PR ID in completion commit messages if available. This setting arrived in Azure DevOps Services Sprint 270; older Server versions may not expose it. A supported engine also normalizes the optional `Merged PR 42:` prefix. The rest of the subject must still match the intended title.

## Local CLI and PR Descriptions

`git-tools commit` generates **and commits** by default; use `--no-commit` to preview. `git-tools pr` generates text, not a hosted PR: push your source branch and create/complete the PR in **Repos → Pull requests** yourself.

Azure descriptions are limited to **4,000 UTF-16 code units**. Azure origin detection enables the CLI limit automatically; use `--azure-limit` for custom hosts or `--no-azure-limit` for other destinations. Oversized output is regenerated once, then retained with a warning if still too long. Inspect and shorten the final text before pasting. See [CLI usage](../usage.md) and [provider configuration/limitations](../configuration.md).

## Operational Safety and Limitations

- **Trust boundary:** restrict who can edit the pipeline, its secrets, and credential-bearing YAML/branches. These are mutating push pipelines, not PR validation builds. `pr: none` alone does not protect credentials from untrusted YAML. Use a separate read-only test pipeline for PR validation.
- **Never log the key.** Azure masking does not guarantee protection of individual lines/substrings of a multiline secret. Do not enable shell tracing around secrets, print their environment, or include them in diagnostic artifacts. The examples map the secret only into the import step.
- **Agent assumption:** use a fresh disposable Microsoft-hosted agent and one automation signing key. Stdin avoids an extra export file, but GPG still stores the imported key in the agent keyring. Reused/self-hosted agents need isolated keyrings, explicit key selection, and cleanup designed separately. These templates do not provide that hardening or a passphrase input.
- **History and serialization:** retain full history, tags, and remote branch refs. The examples do not serialize concurrent runs; coordinate version-producing pushes and wait/pull/fetch before dependent operations. The generated bump subject skips the next ordinary run, but does not protect against competing pipelines or manual version edits.
- **Triggers:** `master`, `develop`, `release/*`, `hotfix/*`, `feature/*`, and `bugfix/*` are included. Reviewed helpers `release-fix/*` and `hotfix-fix/*` run versioning only when their merge pushes the target branch.
- Reviewed flow is a repository-policy choice, not a compliance certification. Read the [current engine limitations](../versioning.md#current-limitations) before enabling writes.

## Publication and Recovery

The engine dry-runs an atomic push and falls back to separate pushes only when the server explicitly lacks atomic support. Other failures stop. Inspect remote refs and follow [publication and missing-tag recovery](../publication.md). Never force-push a version commit or repeat bootstrap to repair publication; rerunning is not guaranteed to recover a lost local signed tag.

## After Setup

Follow one complete guide: [Classic](classic-walkthrough.md), [Classic — Reviewed](classic-reviewed-walkthrough.md), [Release-led](release-led-walkthrough.md), or [Release-led — Reviewed](release-led-reviewed-walkthrough.md). Each includes its mode policy and edge cases as well as the concrete journey.

# Azure DevOps quickstart — returning-user checklist

**Already have a repository or keys?** Configure the signing secret below and check [YAML/permissions](setup.md); skip fresh-repository bootstrap for existing release history. New to this flow? Use the [complete Classic guide](classic-walkthrough.md) instead. This checklist assumes [git-tools installed](../../README.md#install), Git/GnuPG, and permission to configure Pipelines/security.

## Existing Key → Pipeline Secret

**Destination: Azure DevOps → Pipelines → your pipeline → Edit → Variables → New variable → `BOT_GPG_SECRETKEY` → enable “Keep this value secret”.** Select your **dedicated automation signing key**, not your personal key. Replace `YOUR_GPG_KEY_ID` with its long ID or full fingerprint from the first command before running the second:

```bash
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY (secret pipeline variable)
```

Paste the full armored private-key block with original line breaks; no export file is needed. Existing pipeline users can paste now; fresh-repo users paste after creating the pipeline in step 2. No need to recreate/register keys already configured. [Need a new automation key?](setup.md#2-choose-an-automation-signing-key)

**No GPG passphrase input is configured.** Use only an approved unattended key. Never log or trace it or put it in YAML; multiline masking does not protect individual lines. Azure needs no SSH key, PAT, bot user, or LLM key for versioning CI. The steps below illustrate **fresh-repository bootstrap only**.

## 1. Prepare the repository and pipeline YAML

This example keeps the editable tool checkout at **`$HOME/projects/git-tools`** and the application beside it. If you installed elsewhere, use that checkout's absolute path in `cp`; keep the tool checkout in place. Run these commands in a new application directory, not inside git-tools.

Replace `YOUR_NAME`/`YOUR_EMAIL` with **your own human Git identity**, and the origin's `YOUR_ORG`/`YOUR_PROJECT`/`YOUR_REPOSITORY` with **your own Azure repository**. The upstream git-tools URL is only the tool source.

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
mkdir my-app && cd my-app
git init -b master
git config user.name "YOUR_NAME"
git config user.email "YOUR_EMAIL"
git remote add origin "https://dev.azure.com/YOUR_ORG/YOUR_PROJECT/_git/YOUR_REPOSITORY"
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .azure/workflows
cp "$HOME/projects/git-tools/.azure/workflows/version-bump-git-flow-classic.yml.example" \
  .azure/workflows/version-bump-git-flow-classic.yml
```

Before running CI, follow [Azure setup](setup.md):

- Set YAML `GIT_TOOLS_REPO`, a **supported engine branch/tag** in `GIT_TOOLS_REF`, and **your own automation identity** in `GIT_BOT_NAME`/`GIT_BOT_EMAIL`. Keep full history, tags, and `persistCredentials: true`. A bare engine SHA is not supported by the example clone.
- [Choose an existing automation signing key or create one first](setup.md#2-choose-an-automation-signing-key). In step 2 below, paste its printed armored private key into **pipeline secret variable `BOT_GPG_SECRETKEY`**. No local export file is needed. The adapter has **no passphrase input**; use only an approved unattended automation key, not your personal key.
- Enable **Limit job authorization scope to current project for non-release pipelines** in organization/project **Pipelines → Settings**. Pushes use **`<Your Project> Build Service (<Your Organization>)`**.

Activate **one** version pipeline. Protect `master`/`develop`; Classic permits human stabilization commits on `release/*` and `hotfix/*`. `init` does not install pipelines.

## 2. Bootstrap, then configure and run the pipeline

Review the files before staging; never include credentials. Choose **one** staging command:

```bash
git add -A  # If application files are already present.
# Otherwise, stage only the bootstrap files instead:
# git add .cz.toml .azure/workflows/version-bump-git-flow-classic.yml
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```

Set the repo default branch to `master`. **After this push**, in Azure DevOps:

1. **Pipelines → New pipeline → Azure Repos Git → Existing Azure Pipelines YAML file**: choose `master` and the copied YAML; save.
2. In this pipeline's **Edit → Variables**, create **`BOT_GPG_SECRETKEY`**, enable **Keep this value secret**, and paste the complete armored private key from the copy block above. Preserve original line breaks; do not log the secret or put it in YAML. There is no Secure File upload or separate secret-authorization step.
3. Grant the project Build Service **Read, Contribute, Create branch, Create tag** on this repo, and authorize repository access if prompted. If the identity is missing, follow the [first-run identity caveat](setup.md#6-grant-build-service-permissions). Scope any required protected-branch push exception to automation, not humans.
4. **Run pipeline** manually on `master`. The earlier push is **not retroactive**. Wait for the bot commit and signed tag **`0.1.0`**; do not manually bump/tag or add another bootstrap commit.

Use a fresh disposable hosted agent and restrict changes to authorized YAML/secrets. Azure's masking does not reliably hide individual lines of a multiline key; never print it or enable tracing. GPG imports into the agent keyring, even though no export file is created. See [operational safety](setup.md#operational-safety-and-limitations).

```bash
git pull --ff-only origin master
git fetch origin --tags
git switch -c develop
git push -u origin develop
```

The branch-creation run skips; `develop` starts at `0.1.0`.

## 3. Land the first feature

```bash
git switch -c feature/first
# Make and test a real application change; replace the path placeholder.
git add -- <reviewed-paths>
git commit -m "feat: add first feature"
git push -u origin feature/first
```

In **Repos → Pull requests**, open **`feature/first` → `develop`**, title **`Start 0.2.0`**. Review, pass separate PR validation checks, and **Complete → Squash**, with that final subject. Wait for the push pipeline: **`0.2.0-alpha.0`** and its tag.

After **every** version-producing push/merge, wait for publication, switch to the affected branch, run `git pull --ff-only origin <branch>`, and `git fetch origin --tags`. Permit squash **and Merge (no fast-forward)** in branch policies; prohibit rebase.

## 4. Release, backmerge, hotfix

| Step | Action | Expected result |
| --- | --- | --- |
| Cut release | From updated `develop`, create/push `release/0.2.0` | Branch creation alone does not open RC |
| Open next cycle | Next real PR into `develop`: **`Start 0.3.0`** | `0.3.0-alpha.0` |
| Stabilize | Commit/push a tested `fix: …` on `release/0.2.0` | `0.2.0-rc.0` |
| Promote | Squash PR `release/0.2.0` → `master`: **`Release 0.2.0`** | Stable `0.2.0` + tag |
| Backmerge | Follow [source synchronization](classic-walkthrough.md#11-synchronize-the-promoted-release-source-for-backmerge), then PR to `develop`: **`Backmerge Release 0.2.0`**, **Merge (no fast-forward)** | Preserve fixes and untagged history; no new tag |
| Hotfix | From updated `master`, create `hotfix/name`, commit/push a tested fix; squash PR to `master`: **`Hotfix 0.2.1`** | `0.2.1-rc.0`, then stable `0.2.1` + tag |
| Backmerge hotfix | Follow [hotfix synchronization](classic-walkthrough.md#15-synchronize-the-promoted-hotfix-source-for-backmerge), then PR to `develop`: **`Backmerge Hotfix 0.2.1`**, **Merge (no fast-forward)** | Preserve fixes and untagged history; no new tag |

Keep release/hotfix sources until backmerge finishes. **Do not squash synchronization history or boundary backmerges.** If master advances before promotion, synchronize/revalidate first. Stop on pipeline failures; do not run competing local bumps.

**Other modes:** [Classic reviewed](classic-reviewed-walkthrough.md) requires real inner stabilization/synchronization PRs with the same adapter. [Release-led](release-led-walkthrough.md) and [release-led reviewed](release-led-reviewed-walkthrough.md) use the release-led adapter **instead**, with different release-line selection; do not mix their sequence with Classic.

Before production use: [current versioning limitations](../versioning.md#current-limitations). Failed publication: [recovery](../publication.md), not another bootstrap. Full worked example: [Classic walkthrough](classic-walkthrough.md).

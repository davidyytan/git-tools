# Azure DevOps quickstart

**Fresh repository → first Classic release.** Requires [git-tools installed](../../README.md#install), Git author configured, an empty Azure Repo, and permission to configure Pipelines/security. No LLM account, PAT, bot user, or SSH key is needed for versioning CI.

## 1. Prepare the repository and pipeline YAML

Replace the checkout path and remote:

```bash
GIT_TOOLS_DIR=/path/to/git-tools
mkdir my-app && cd my-app
git init -b master
git remote add origin https://dev.azure.com/ORG/PROJECT/_git/REPOSITORY
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .azure/workflows
cp "$GIT_TOOLS_DIR/.azure/workflows/version-bump-git-flow-classic.yml.example" \
  .azure/workflows/version-bump-git-flow-classic.yml
```

Following [Azure setup](setup.md), prepare these before running CI:

- In YAML, set `GIT_TOOLS_REPO`, a **supported engine branch/tag** in `GIT_TOOLS_REF`, `GIT_BOT_NAME`, `GIT_BOT_EMAIL`, and `GPG_SECURE_FILE`. A bare SHA is not supported by the example clone.
- Generate/export the automation GPG key; keep the private export out of Git. Retain full history, tag fetching, and `persistCredentials: true` in YAML.
- Enable project-scoped job authorization. The pipeline pushes as **`<Project> Build Service (<Organization>)`**, not a personal account.

Activate **one** version pipeline. Protect `master`/`develop`; this Classic path permits human stabilization commits on `release/*` and `hotfix/*`. `init` does not install pipelines.

## 2. Bootstrap, then create and authorize the pipeline

Ensure credentials/private keys are ignored, then choose **one** staging command:

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
2. Upload the private GPG export under **Pipelines → Library → Secure files**, matching `GPG_SECURE_FILE`; authorize this pipeline and its repository access.
3. Grant the project Build Service **Read, Contribute, Create branch, Create tag** on this repo. Scope any required protected-branch push exception to automation, not humans.
4. **Run pipeline** manually on `master`. The earlier push is **not retroactive**. Wait for the bot commit and signed tag **`0.1.0`**; do not manually bump/tag or add another bootstrap commit.

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
